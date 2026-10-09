"""MCP transport, input validation and public page evidence without network/DB."""
import hashlib
import uuid

import pytest
import respx
import httpx
from pydantic import SecretStr, ValidationError

from app.core.config import settings
from app.engine.persistence import persist_findings
from app.models.entity import Entity
from app.models.target import Target
from app.schemas.workspace import NoteCreate, ToolInputs
from app.services.workspace import call_fingerprint
from app.tools.base import TargetContext, ToolFinding
from app.tools.public_page_reader import PublicPageReaderTool


@pytest.fixture
def mcp_app(monkeypatch):
    from app.mcp.server import mcp
    from app.mcp.auth import MCPTokenGate
    monkeypatch.setattr(mcp, "_session_manager", None)
    monkeypatch.setattr(settings, "mcp_api_key", SecretStr("test-mcp-token"))
    monkeypatch.setattr(settings, "mcp_enabled", True)
    return MCPTokenGate(mcp.streamable_http_app()), mcp


async def rpc(client, method, params=None, *, host=None):
    headers = {"Authorization": "Bearer test-mcp-token", "Accept": "application/json, text/event-stream"}
    if host:
        headers["Host"] = host
    return await client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}})


@pytest.mark.asyncio
async def test_http_mcp_requires_token_and_exposes_registry(mcp_app):
    app, mcp = mcp_app
    async with mcp.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
            assert (await client.post("/mcp", json={})).status_code == 401
            assert (await client.post("/mcp", headers={"Authorization": "Bearer wrong"}, json={})).status_code == 401
            initialized = await rpc(client, "initialize", {"protocolVersion": "2025-11-25", "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"}})
            assert initialized.status_code == 200
            assert initialized.json()["result"]["serverInfo"]["name"] == "PersonMap"
            response = await rpc(client, "tools/list")
            tools = {t["name"]: t for t in response.json()["result"]["tools"]}
            assert {"create_investigation", "username_finder", "social_verifier", "public_page_reader", "add_analysis_note", "finish_session"} <= tools.keys()
            assert tools["username_finder"]["inputSchema"]["required"] == ["investigation_id", "session_id"]
            assert tools["add_analysis_note"]["annotations"]["readOnlyHint"] is False
            assert tools["get_finding"]["annotations"]["readOnlyHint"] is True
            assert tools["create_investigation"]["outputSchema"]["type"] == "object"


@pytest.mark.asyncio
async def test_mcp_rejects_rebinding_host(mcp_app):
    app, mcp = mcp_app
    async with mcp.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
            response = await rpc(client, "tools/list", host="evil.example")
            assert response.status_code in {400, 421}


@pytest.mark.asyncio
async def test_mcp_disabled_or_unconfigured_does_not_open_bridge(mcp_app, monkeypatch):
    app, _ = mcp_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        monkeypatch.setattr(settings, "mcp_api_key", None)
        assert (await client.post("/mcp")).status_code == 503
        monkeypatch.setattr(settings, "mcp_enabled", False)
        assert (await client.post("/mcp")).status_code == 404


def test_notes_and_inputs_reject_unsafe_urls_and_consent_override():
    for url in ["http://localhost/private", "http://127.0.0.1/", "https://example.org/?api_key=secret", "javascript:alert(1)"]:
        with pytest.raises(ValidationError):
            NoteCreate(title="Análisis", content="Texto", evidence_urls=[url])
        with pytest.raises(ValidationError):
            ToolInputs(candidate_urls=[url])
    with pytest.raises(ValidationError):
        ToolInputs(self_consent=True)
    with pytest.raises(ValidationError):
        NoteCreate(title=" ", content="Texto")
    with pytest.raises(ValidationError):
        NoteCreate(title="Análisis", content="Texto", details={"value": float("nan")})


def test_fingerprint_is_input_specific_and_does_not_depend_on_runtime_cache():
    first = TargetContext(username="alpha", extra={"self_consent": False, "cache": "one"})
    second = TargetContext(username="alpha", extra={"self_consent": False, "cache": "two"})
    assert call_fingerprint("username_finder", first) == call_fingerprint("username_finder", second)
    assert call_fingerprint("username_finder", first) != call_fingerprint("username_finder", TargetContext(username="beta"))


@pytest.mark.asyncio
@respx.mock
async def test_reader_captures_text_and_public_links_without_scripts(monkeypatch):
    monkeypatch.setattr(settings, "tinyfish_fetch_enabled", False)
    url = "https://example.test/about"
    text = "Publicly documented information about this profile. " * 4
    respx.get(url).respond(200, text=f'<title>About</title><script>do not retain</script><p>{text}</p><a href="https://github.com/example">GitHub</a><a href="http://localhost/private">private</a>', headers={"content-type": "text/html"})
    findings = await PublicPageReaderTool().execute(TargetContext(extra={"candidate_urls": [url]}))
    meta = findings[0].metadata_info
    assert "do not retain" not in meta["page_text"]
    assert meta["linked_profiles"] == ["https://github.com/example"]
    assert meta["content_sha256"] == hashlib.sha256(meta["page_text"].encode()).hexdigest()
    assert findings[0].evidence_urls == [url]


@pytest.mark.asyncio
async def test_incremental_findings_keep_id_metadata_and_all_sources():
    class MemorySession:
        def add(self, item):
            raise AssertionError("Existing entity must be updated, not duplicated")
        async def flush(self):
            pass
    inv_id = uuid.uuid4()
    original = Entity(id=uuid.uuid4(), investigation_id=inv_id, entity_type="social_account", platform="github",
        value="https://github.com/example", display_name="example", source_tool="username_finder",
        metadata_info={"username": "example", "source_tool": "username_finder", "source_tools": ["username_finder"],
                       "evidence_urls": ["https://example.test/first"]})
    finding = ToolFinding(entity_type="social_account", platform="GitHub (User)", value="https://www.github.com/example/",
        metadata_info={"bio": "Observed biography", "source_tool": "social_verifier"}, evidence_urls=["https://example.test/second"])
    rows = await persist_findings(str(inv_id), [finding], Target(), MemorySession(), existing_entities=[original])
    assert rows == [original]
    assert original.metadata_info["username"] == "example"
    assert original.metadata_info["bio"] == "Observed biography"
    assert set(original.metadata_info["source_tools"]) == {"username_finder", "social_verifier"}
    assert set(original.metadata_info["evidence_urls"]) == {"https://example.test/first", "https://example.test/second"}
