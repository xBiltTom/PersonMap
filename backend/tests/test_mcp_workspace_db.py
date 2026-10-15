"""Real PostgreSQL migrations and MCP/REST interoperability in a disposable schema.

Run explicitly: .venv/bin/python -m pytest tests/test_mcp_workspace_db.py -m db -q
No external OSINT requests; tools use controlled fixtures. Existing dossiers are untouched.
"""
import asyncio
import json
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from alembic import command
from alembic.config import Config
from pydantic import SecretStr
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.database import get_db
from app.core.events import event_bus
from app.models.entity import Entity
from app.models.entity_observation import EntityObservation
from app.models.investigation import Investigation
from app.models.investigation_session import InvestigationSession
from app.models.tool_execution import ToolExecution
from app.models.analysis_note import AnalysisNote
from app.models.relationship import Relationship
from app.models.correlation_group import CorrelationGroup
from app.core.fingerprint import run_fingerprint
from fastapi import HTTPException
from app.schemas.investigation import InvestigationCreate
from app.schemas.target import TargetCreate
from app.schemas.external_evidence import ExternalEvidence, ExternalEvidenceBatch
from app.schemas.workspace import CorrelationAssessmentCreate, NoteCreate, PivotPlan, SearchQuery, SessionCreate, ToolInputs, ToolRequest
from app.services.workspace import EXTERNAL_TOOLS, WorkspaceService, call_fingerprint
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding

pytestmark = pytest.mark.db


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["doi", "orcid"])
async def test_academic_mcp_typed_search_dedupes_persists_and_can_refresh(isolated_workspace, monkeypatch, kind):
    import app.mcp.server as mcp_module
    from app.mcp.auth import MCPTokenGate
    from app.tools import http_client
    service, _ = isolated_workspace
    doi = "https://doi.org/10.5555/test.123"
    orcid = "https://orcid.org/0000-0002-1825-0097"
    monkeypatch.setattr(settings, "crossref_enabled", True)
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.host == "api.crossref.org":
            work = {"DOI": "10.5555/TEST.123", "title": ["Observed paper"],
                "author": [{"given": "Ana", "family": "Perez", "ORCID": orcid}]}
            return httpx.Response(200, json={"status": "ok", "message": work if kind == "doi" else {"items": [work]}})
        if request.url.path == "/authors":
            return httpx.Response(200, json={"results": [{"id": "https://openalex.org/A1", "display_name": "Ana Perez", "orcid": orcid}]})
        return httpx.Response(200, json={"results": [{"id": "https://openalex.org/W1", "doi": doi,
            "title": "Observed paper", "authorships": [{"author": {"id": "https://openalex.org/A1", "display_name": "Ana Perez", "orcid": orcid}}]}]})
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(mcp_module, "workspace", service)
    monkeypatch.setattr(mcp_module.mcp, "_session_manager", None)
    app = MCPTokenGate(mcp_module.mcp.streamable_http_app())
    async with mcp_module.mcp.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
            headers={"Authorization": "Bearer integration-token", "Accept": "application/json, text/event-stream"}) as client:
            counter = 0
            async def call(name, arguments):
                nonlocal counter
                counter += 1
                response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": counter, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}})
                assert response.status_code == 200
                result = response.json()["result"]
                assert not result.get("isError"), result
                return result["structuredContent"]
            created = await call("create_investigation", {"target": {"username": "seed"}})
            inv_id = uuid.UUID(created["id"])
            opened = await call("open_session", {"investigation_id": str(inv_id), "client": "academic-audit"})
            inputs = {"candidate_urls": [doi]} if kind == "doi" else {"identifiers": [{"id_type": "orcid", "value": orcid.rsplit("/", 1)[-1]}]}
            args = {"investigation_id": str(inv_id), "session_id": opened["id"], "inputs": inputs, "rationale": "Inspect explicit scholarly identifier"}
            started = await call("academic_finder", args)
            await service.tasks[uuid.UUID(started["id"])]
            execution = await call("get_execution", {"investigation_id": str(inv_id), "execution_id": started["id"]})
            assert execution["status"] == "completed"
            assert execution["input_summary"]["academic"]["requests"] == (2 if kind == "doi" else 3)
            service.contexts.clear()
            context = await call("get_investigation_context", {"investigation_id": str(inv_id)})
            assert len(context["academic"]["queries"]) == 1
            assert all(item["status"] == "ok" for item in context["academic"]["diagnostics"])
            before = len(calls)
            reused = await call("academic_finder", args)
            assert reused["reused"] and reused["id"] == started["id"] and len(calls) == before
            repeated = await call("academic_finder", {**args, "force": True})
            await service.tasks[uuid.UUID(repeated["id"])]
            assert len(calls) == before * 2
            detail = await service.detail(inv_id)
            papers = [entity for entity in detail["entities"] if entity["platform"] == "research_paper"]
            assert len(papers) == 1 and papers[0]["value"] == doi
            assert set(papers[0]["metadata_info"]["academic_sources"]) == {"crossref", "openalex"}
            assert papers[0]["metadata_info"]["ownership_status"] == "unverified"


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_name", ["google_account_osint", "email_checker"])
async def test_public_profile_evidence_survives_workspace_reload_and_reuses(isolated_workspace, monkeypatch, tool_name):
    from app.tools import http_client
    service, _ = isolated_workspace
    scholar = "https://scholar.google.com/citations?user=AbcdEF12GhIJ"
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.host == "scholar.google.com":
            return httpx.Response(200, text='<div id="gsc_prf_in">Observed Author</div>'
                '<table id="gsc_rsb_st"><tr><td>Citations</td><td>1234</td><td>10</td></tr></table>')
        if request.url.path == "/search/users":
            return httpx.Response(200, json={"items": [{"login": "observed-user"}]})
        return httpx.Response(200, json={"login": "observed-user", "email": "audit@example.org"})
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    async with service.session_factory() as db:
        inv = await service.create(InvestigationCreate(target=TargetCreate(
            identifiers=[{"value": "0000-0002-1825-0097", "id_type": "orcid"}]), execution_mode="external"), db)
    opened = await service.open_session(inv.id, SessionCreate(client="public-profile-audit"))
    sid = uuid.UUID(opened["id"])
    inputs = ToolInputs(candidate_urls=[scholar]) if tool_name == "google_account_osint" else ToolInputs(email="audit@example.org")
    payload = ToolRequest(tool_name=tool_name, inputs=inputs, rationale="Verify observed public profile")
    started = await service.submit_tool(inv.id, sid, payload)
    await service.tasks[uuid.UUID(started["id"])]
    async with service.session_factory() as db:
        execution = await db.get(ToolExecution, uuid.UUID(started["id"]))
        assert execution.status == "completed" and execution.findings_count >= 1
        if tool_name == "google_account_osint":
            assert execution.input_summary["google_public"]["statuses"] == {"observed": 1}
    service.contexts.clear()
    context = await service.context(inv.id)
    if tool_name == "google_account_osint":
        assert context["google_public"]["scholar_profiles"][scholar] == "observed"
    else:
        assert context["email_checker"]["diagnostics"]["audit@example.org"]["status"] == "public_email_match"
    count = len(calls)
    reused = await service.submit_tool(inv.id, sid, payload)
    assert reused["reused"] and reused["id"] == started["id"] and len(calls) == count
    detail = await service.detail(inv.id)
    profiles = [e for e in detail["entities"] if e["entity_type"] in {"academic_profile", "social_account"}]
    assert len(profiles) == 1 and profiles[0]["metadata_info"]["ownership_status"] == "unverified"
    if tool_name == "google_account_osint":
        assert profiles[0]["metadata_info"]["citations"] == 1234


@pytest.mark.asyncio
async def test_email_enumerator_mcp_persists_partial_coverage_reuses_and_can_force(isolated_workspace, monkeypatch):
    from app.mcp import server as mcp_module
    from app.mcp.auth import MCPTokenGate
    from app.tools import http_client
    service, _ = isolated_workspace
    monkeypatch.setattr(settings, "email_enum_sites", ["firefox", "twitter"])
    calls = []
    def respond(request):
        calls.append(request)
        if "twitter" in request.url.host:
            return httpx.Response(429)
        return httpx.Response(200, json={"exists": json.loads(request.content)["email"] == "audit@example.org"})
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    monkeypatch.setattr(mcp_module, "workspace", service)
    monkeypatch.setattr(mcp_module.mcp, "_session_manager", None)
    app = MCPTokenGate(mcp_module.mcp.streamable_http_app())
    async with mcp_module.mcp.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
            headers={"Authorization": "Bearer integration-token", "Accept": "application/json, text/event-stream"}) as client:
            counter = 0
            async def call(name, arguments):
                nonlocal counter
                counter += 1
                response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": counter, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}})
                assert response.status_code == 200, response.text
                result = response.json()["result"]
                assert not result.get("isError"), result
                return result["structuredContent"]
            created = await call("create_investigation", {"target": {"email": "audit@example.org"}})
            inv_id = uuid.UUID(created["id"])
            session = await call("open_session", {"investigation_id": str(inv_id), "client": "email-audit"})
            args = {"investigation_id": str(inv_id), "session_id": session["id"], "rationale": "Check selected email services"}
            started = await call("email_enumerator", args)
            await service.tasks[uuid.UUID(started["id"])]
            execution = await call("get_execution", {"investigation_id": str(inv_id), "execution_id": started["id"]})
            assert execution["status"] == "completed" and execution["findings_count"] == 1
            assert execution["input_summary"]["email_enumerator"]["counts"] == {"rate_limited": 1, "registered": 1}
            service.contexts.clear()  # The next read reconstructs coverage from PostgreSQL.
            context = await call("get_investigation_context", {"investigation_id": str(inv_id)})
            assert context["email_enumerator"]["diagnostics"]["audit@example.org"]["twitter"]["status"] == "rate_limited"
            reused = await call("email_enumerator", args)
            assert reused["reused"] and reused["id"] == started["id"]
            assert len(calls) == 3
            repeated = await call("email_enumerator", {**args, "force": True})
            await service.tasks[uuid.UUID(repeated["id"])]
            assert len(calls) == 6
            web = await service.detail(inv_id)
            assert len(web["entities"]) == 1
            assert web["entities"][0]["entity_type"] == "email_registration"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["gaia", "email"])
async def test_ghunt_typed_mcp_input_persists_diagnostics_and_reuses_coverage(isolated_workspace, monkeypatch, tmp_path, kind):
    import base64
    import app.tools.ghunt as ghunt_adapter
    import app.mcp.server as mcp_module
    from app.mcp.auth import MCPTokenGate
    gaia = "123456789012345678901"
    creds = tmp_path / "creds.m"
    creds.write_bytes(base64.b64encode(json.dumps({"android": {"master_token": "fixture-master"}}).encode()))
    monkeypatch.setattr(settings, "ghunt_credentials_file", str(creds))
    monkeypatch.setattr(settings, "ghunt_enabled", True)
    calls = []
    async def lookup(query, services):
        calls.append(query)
        return {"status": "observed", "requests": 2, "profile": {"gaia_id": gaia}, "services": {}}
    monkeypatch.setattr(ghunt_adapter, "run_ghunt", lookup)
    service, _ = isolated_workspace
    monkeypatch.setattr(mcp_module, "workspace", service)
    monkeypatch.setattr(mcp_module.mcp, "_session_manager", None)
    app = MCPTokenGate(mcp_module.mcp.streamable_http_app())
    # The test uses the same registry/ToolInputs/submit path as a real MCP call.
    async with mcp_module.mcp.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000",
            headers={"Authorization": "Bearer integration-token", "Accept": "application/json, text/event-stream"}) as client:
            counter = 0
            async def call(name, arguments):
                nonlocal counter
                counter += 1
                response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": counter, "method": "tools/call",
                    "params": {"name": name, "arguments": arguments}})
                assert response.status_code == 200, response.text
                result = response.json()["result"]
                assert not result.get("isError"), result
                return result["structuredContent"]
            inputs = {"identifiers": [{"value": gaia, "id_type": "gaia_id"}]} if kind == "gaia" else {"email": "audit@example.org"}
            created = await call("create_investigation", {"target": inputs})
            inv_id = uuid.UUID(created["id"])
            session = await call("open_session", {"investigation_id": str(inv_id), "client": "ghunt-audit"})
            arguments = {"investigation_id": str(inv_id), "session_id": session["id"],
                "inputs": inputs, "rationale": "Inspect explicit identifier"}
            started = await call("ghunt", arguments)
            await service.tasks[uuid.UUID(started["id"])]
            result = await call("get_execution", {"investigation_id": str(inv_id), "execution_id": started["id"]})
            assert result["status"] == "completed" and result["findings_count"] == 1
            assert result["input_summary"]["ghunt"]["statuses"] == ["observed"]
            context = await call("get_investigation_context", {"investigation_id": str(inv_id)})
            key = "gaia:" + gaia if kind == "gaia" else "email:audit@example.org"
            assert context["ghunt"]["diagnostics"][key]["requests"] == 2
            reused = await call("ghunt", arguments)
            assert reused["reused"] and reused["id"] == started["id"]
            assert len(calls) == 1
            web = await service.detail(inv_id)
            assert web["entities"][0]["metadata_info"]["gaia_id"] == gaia
            assert web["entities"][0]["source_tool"] == "ghunt"


@pytest_asyncio.fixture
async def isolated_workspace(monkeypatch):
    schema = "mcp_test_" + uuid.uuid4().hex
    bootstrap = create_async_engine(settings.database_url, poolclass=NullPool, connect_args={"timeout": 5})
    async with bootstrap.begin() as conn:
        await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_async_engine(settings.database_url, poolclass=NullPool,
                                connect_args={"timeout": 5, "server_settings": {"search_path": schema}})
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "migrations"))

    def migrate(conn, revision):
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, revision)

    service = WorkspaceService(async_sessionmaker(engine, expire_on_commit=False))
    try:
        async with engine.begin() as conn:
            await conn.run_sync(migrate, "bc71a90de452")
            target_id, inv_id = uuid.uuid4(), uuid.uuid4()
            await conn.execute(text("INSERT INTO targets (id, username, created_at) VALUES (:id, 'legacy', now())"), {"id": target_id})
            await conn.execute(text("INSERT INTO investigations (id, target_id, strategy, status, created_at) VALUES (:id, :target, 'rule_based', 'pending', now())"), {"id": inv_id, "target": target_id})
            await conn.run_sync(migrate, "head")
        monkeypatch.setattr(settings, "mcp_api_key", SecretStr("integration-token"))
        monkeypatch.setattr(settings, "mcp_enabled", True)
        yield service, inv_id
    finally:
        await service.shutdown()
        await engine.dispose()
        async with bootstrap.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await bootstrap.dispose()


class FixtureTool(BaseTool):
    name = "username_finder"
    description = "Controlled username fixture"
    category = ToolCategory.USERNAME
    required_inputs = ["username"]

    async def execute(self, context: TargetContext):
        if context.extra.get("username_finder_fixture_scanned"):
            return []
        context.extra["username_finder_fixture_scanned"] = True
        return [ToolFinding(entity_type="social_account", platform="github", value="https://github.com/fixture",
                            metadata_info={"username": "fixture", "bio": "Public fixture biography"},
                            evidence_urls=["https://example.test/source"])]


@pytest.mark.asyncio
async def test_external_evidence_enters_map_trace_updates_and_preserves_provenance(isolated_workspace):
    service, _ = isolated_workspace
    async with service.session_factory() as db:
        inv = await service.create(InvestigationCreate(target=TargetCreate(username="seed"), execution_mode="external"), db)
    session = await service.open_session(inv.id, SessionCreate(client="browser-fixture"))
    sid = uuid.UUID(session["id"])
    observed = datetime.now(timezone.utc) - timedelta(minutes=2)
    page = ExternalEvidence(entity_type="document", url="https://example.test/roll", source_url="https://example.test/roll",
        title="Public academic roll", acquisition_method="agent_browser", evidence_level="page_content", observed_at=observed,
        excerpt="Pérez Rojas Ana María, public_alias, Ingeniería.", locator="Page 22, relevant row",
        identifiers=[{"kind":"name", "value":"Pérez Rojas Ana María"}, {"kind":"username", "value":"public_alias"}])
    snippet = ExternalEvidence(**{**page.model_dump(), "acquisition_method":"agent_search", "evidence_level":"search_result",
        "identifiers": [], "excerpt":"Pérez Rojas Ana María appears in a search snippet", "query":'"Pérez Rojas Ana María"'})
    batch = ExternalEvidenceBatch(rationale="Read document and distinguish indexed snippet", records=[page,snippet], idempotency_key="fixture-batch")
    imported = await service.import_evidence(inv.id, sid, batch)
    assert len(imported["findings"]) == 1 and not imported["server_fetched_sources"]
    entity_id = uuid.UUID(imported["entity_ids"][0])
    assert "excerpt" not in imported["findings"][0]["metadata_info"]["external_reports"][0]
    detail = await service.detail(inv.id)
    assert len(detail["entities"]) == 1 and len(detail["correlation_groups"]) == 1
    full = await service.findings(inv.id, 1, entity_id=entity_id, include_content=True)
    reports = full["findings"][0]["metadata_info"]["external_reports"]
    assert {report["evidence_level"] for report in reports} == {"page_content","search_result"}
    assert all(report["reported_by"] == "browser-fixture" and report["server_verified"] is False for report in reports)
    async with service.session_factory() as db:
        observations = list((await db.scalars(select(EntityObservation).where(EntityObservation.investigation_id == inv.id))).all())
        assert len(observations) == 2 and all(obs.observed_at == observed for obs in observations)
        assert {str(obs.id) for obs in observations} == {report["observation_id"] for report in reports}
        execution = await db.get(ToolExecution, uuid.UUID(imported["execution_id"]))
        assert execution.engine_layer == "external_import" and execution.input_summary["duration_scope"] == "persistence_only"
        assert "excerpt" not in json.dumps(execution.input_summary)
    reused = await service.import_evidence(inv.id, sid, batch)
    assert reused["reused"] and reused["execution_id"] == imported["execution_id"]
    assert reused["entity_ids"] == imported["entity_ids"]
    assert set(reused["observation_ids"]) == set(imported["observation_ids"])
    with pytest.raises(HTTPException) as exc:
        await service.import_evidence(inv.id, sid, batch.model_copy(update={"rationale":"Changed content"}))
    assert exc.value.status_code == 409
    context = await service.context(inv.id)
    assert len(context["reported_candidates"]) == 2
    assert context["known_identifiers"]["discovered_usernames"] == []
    assert context["known_identifiers"]["discovered_names"] == []
    updates = await service.updates(inv.id, 0)
    assert any(change["kind"] == "finding" and change["data"]["id"] == str(entity_id) for change in updates["changes"])
    with pytest.raises(HTTPException) as exc:
        await service.import_evidence(inv.id, sid, batch.model_copy(update={"source_entity_ids":[uuid.uuid4()], "idempotency_key":"new"}))
    assert exc.value.status_code == 422
    await service.close_session(inv.id, sid, "finish")
    async with service.session_factory() as db:
        completed = await db.get(Investigation, inv.id)
        assert completed.metrics["tools_executed"] == 0 and completed.metrics["tool_execution_seconds"] == 0
        assert completed.metrics["external_import_batches"] == 1 and completed.metrics["external_import_observations"] == 2
    with pytest.raises(HTTPException) as exc:
        await service.import_evidence(inv.id, sid, batch)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_updates_paginate_refresh_existing_findings_and_survive_restart(isolated_workspace, monkeypatch):
    from app.services.workspace_updates import encode_cursor

    service, _ = isolated_workspace
    monkeypatch.setitem(EXTERNAL_TOOLS, "username_finder", FixtureTool())
    async with service.session_factory() as db:
        inv = await service.create(InvestigationCreate(target=TargetCreate(username="fixture"), execution_mode="external"), db)
    session = await service.open_session(inv.id, SessionCreate(client="updates-fixture"))
    session_id = uuid.UUID(session["id"])
    first = await service.submit_tool(inv.id, session_id, ToolRequest(tool_name="username_finder"))
    await service.tasks[uuid.UUID(first["id"])]
    note = await service.add_note(inv.id, NoteCreate(title="Analysis", content="Fixture conclusion"), session_id)
    cursor, changes = None, []
    # Resume with a fresh service after every page: no in-memory cursor history is required.
    for _ in range(20):
        resumed = WorkspaceService(service.session_factory)
        page = await resumed.updates(inv.id, 0, cursor=cursor, limit=1)
        assert len(page["changes"]) <= 1
        changes.extend(page["changes"])
        cursor = page["next_cursor"]
        if not page["has_more"]:
            break
    else:
        pytest.fail("Pagination did not terminate")
    finding = next(change["data"] for change in changes if change["kind"] == "finding")
    assert any(change["kind"] == "execution" for change in changes)
    assert any(change["kind"] == "note" and change["data"]["id"] == note["id"] for change in changes)
    assert not (await service.updates(inv.id, 0, cursor=cursor))["changes"]

    gate = asyncio.Event()
    class EnrichmentTool(FixtureTool):
        async def execute(self, context):
            await gate.wait()
            return [ToolFinding(entity_type="social_account", platform="github", value="https://github.com/fixture",
                metadata_info={"username": "fixture", "bio": "Additional evidence", "page_text": "Captured text " * 1000})]
    monkeypatch.setitem(EXTERNAL_TOOLS, "username_finder", EnrichmentTool())
    second = await service.submit_tool(inv.id, session_id, ToolRequest(tool_name="username_finder", force=True))
    context = await service.context(inv.id)
    since = context["investigation"]["revision"]
    asyncio.get_running_loop().call_later(0.05, gate.set)
    page = await service.updates(inv.id, since, wait_seconds=1)
    refreshed = next(change["data"] for change in page["changes"] if change["kind"] == "finding")
    assert refreshed["id"] == finding["id"]
    assert refreshed["metadata_info"]["content_available"] is True
    assert "page_text" not in refreshed["metadata_info"]
    assert any(change["kind"] == "execution" and change["data"]["id"] == second["id"]
               and change["data"]["status"] == "completed" for change in page["changes"])
    full = await service.findings(inv.id, 1, entity_id=uuid.UUID(finding["id"]), include_content=True)
    assert "page_text" in full["findings"][0]["metadata_info"]
    with pytest.raises(HTTPException) as exc:
        await service.updates(inv.id, 0, cursor=encode_cursor(uuid.uuid4(), 0))
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await service.updates(inv.id, since + 1000)
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await service.updates(inv.id, 0, cursor=encode_cursor(inv.id, since, 100000))
    assert exc.value.status_code == 422
    class FailingTool(FixtureTool):
        async def execute(self, context):
            raise RuntimeError("Controlled fixture failure")
    monkeypatch.setitem(EXTERNAL_TOOLS, "username_finder", FailingTool())
    failed = await service.submit_tool(inv.id, session_id, ToolRequest(tool_name="username_finder", force=True))
    await service.tasks[uuid.UUID(failed["id"])]
    failures = await service.updates(inv.id, 0, cursor=page["next_cursor"])
    assert any(change["kind"] == "execution" and change["data"]["status"] == "failed"
               for change in failures["changes"])
    assert not any(change["kind"] == "finding" for change in failures["changes"])
    await service.close_session(inv.id, session_id, "finish", "Final fixture summary")
    final = await service.updates(inv.id, 0, cursor=failures["next_cursor"])
    assert final["status"] == "completed"
    assert any(change["kind"] == "note" for change in final["changes"])


@pytest.mark.asyncio
async def test_review_import_preserves_baseline_and_graph(isolated_workspace):
    service, source_id = isolated_workspace
    first_id, second_id, execution_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with service.session_factory() as db:
        source = await db.get(Investigation, source_id)
        source.status = "completed"
        source.metrics = {"engine_used": "rules", "tools_executed": 1,
            "collection_runtime": {"username_finder_coverage": {"legacy": 500}, "search_queries_used": 5},
            **{f"config_{key}": value for key, value in run_fingerprint().items()}}
        baseline_metrics = dict(source.metrics)
        db.add_all([
            Entity(id=first_id, investigation_id=source_id, entity_type="social_account", value="https://github.com/legacy", source_tool="username_finder", metadata_info={}),
            Entity(id=second_id, investigation_id=source_id, entity_type="website", value="https://example.test", source_tool="domain_finder", metadata_info={}),
            ToolExecution(id=execution_id, investigation_id=source_id, tool_name="username_finder", engine="rules", status="completed",
                input_fingerprint=call_fingerprint("username_finder", TargetContext(username="legacy")))])
        await db.flush()
        db.add_all([
            EntityObservation(investigation_id=source_id, entity_id=first_id, tool_execution_id=execution_id, evidence_urls=["https://github.com/legacy"]),
            Relationship(investigation_id=source_id, source_entity_id=first_id, target_entity_id=second_id, evidence={"entity_id": str(first_id)}),
            CorrelationGroup(investigation_id=source_id, label="Grupo 01", entity_ids=[str(first_id), str(second_id)], evidence={"execution_id": str(execution_id)})])
        await db.commit()
    created = await service.create_review(source_id)
    review_id = uuid.UUID(created["id"])
    assert review_id != source_id and created["coverage_known"]
    assert created["imported_findings"] == 2 and created["imported_executions"] == 1
    context = await service.context(review_id)
    assert context["execution_policy"]["new_execution_requires_pivot"] is True
    assert context["review_baseline"]["metrics"] == baseline_metrics
    assert context["execution_policy"]["search_queries_remaining"] == max(0, min(settings.tavily_max_queries, settings.mcp_review_max_queries))
    async with service.session_factory() as db:
        source = await db.get(Investigation, source_id)
        review = await db.get(Investigation, review_id)
        assert source.metrics == baseline_metrics and source.status == "completed"
        assert source.target_id != review.target_id
        entities = list((await db.scalars(select(Entity).where(Entity.investigation_id == review_id))).all())
        ids = {entity.id for entity in entities}
        assert ids.isdisjoint({first_id, second_id})
        observation = (await db.scalars(select(EntityObservation).where(EntityObservation.investigation_id == review_id))).one()
        execution = await db.get(ToolExecution, observation.tool_execution_id)
        assert observation.entity_id in ids and execution.id != execution_id and execution.engine == "rules"
        edge = (await db.scalars(select(Relationship).where(Relationship.investigation_id == review_id))).one()
        assert edge.source_entity_id in ids and edge.target_entity_id in ids
        assert edge.evidence["entity_id"] == str(edge.source_entity_id)
        group = (await db.scalars(select(CorrelationGroup).where(CorrelationGroup.investigation_id == review_id))).one()
        assert set(group.entity_ids) == {str(value) for value in ids}
        assert group.evidence["execution_id"] == str(execution.id)
    session = await service.open_session(review_id, SessionCreate(client="review-fixture"))
    candidate = await service.add_assessment(review_id, uuid.UUID(session["id"]), CorrelationAssessmentCreate(
        entity_ids=list(ids), verdict="candidate", reasoning="A possible link needs a reciprocal source"))
    supported = await service.add_assessment(review_id, uuid.UUID(session["id"]), CorrelationAssessmentCreate(
        entity_ids=list(ids), verdict="supported", reasoning="The profile publishes a direct link",
        supporting_urls=["https://github.com/legacy"], supersedes_note_id=uuid.UUID(candidate["id"])))
    assert candidate["id"] != supported["id"]
    assert supported["details"]["supersedes_note_id"] == candidate["id"]
    async with service.session_factory() as db:
        prior = await db.get(AnalysisNote, uuid.UUID(candidate["id"]))
        assert prior.details["verdict"] == "candidate"
        assert (await db.scalars(select(Relationship).where(Relationship.investigation_id == review_id))).one().id == edge.id
        assert (await db.scalars(select(CorrelationGroup).where(CorrelationGroup.investigation_id == review_id))).one().id == group.id
    updates = await service.updates(review_id, 0)
    assert any(change["kind"] == "note" and change["data"].get("assessment", {}).get("verdict") == "supported"
               for change in updates["changes"])
    with pytest.raises(HTTPException) as exc:
        await service.add_assessment(review_id, uuid.UUID(session["id"]), CorrelationAssessmentCreate(
            entity_ids=[first_id, second_id], verdict="candidate", reasoning="Foreign references"))
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        await service.add_assessment(review_id, uuid.UUID(session["id"]), CorrelationAssessmentCreate(
            entity_ids=list(ids), verdict="inconclusive", reasoning="Invalid predecessor", supersedes_note_id=uuid.uuid4()))
    assert exc.value.status_code == 422
    reused = await service.submit_tool(review_id, uuid.UUID(session["id"]),
        ToolRequest(tool_name="username_finder", inputs=ToolInputs(username="legacy", scan_mode="deep")))
    assert reused["reused"] and reused["engine"] == "rules"
    with pytest.raises(HTTPException) as exc:
        await service.submit_tool(review_id, uuid.UUID(session["id"]), ToolRequest(tool_name="username_finder"))
    assert exc.value.status_code == 409
    with pytest.raises(HTTPException) as exc:
        await service.submit_tool(review_id, uuid.UUID(session["id"]), ToolRequest(tool_name="username_finder",
            inputs=ToolInputs(username="new_pivot"), force=True))
    assert exc.value.status_code == 422
    plan = PivotPlan(question="Does a second profile publish the same link?", expected_signal="A direct link",
                     stop_condition="Stop after this profile")
    async def reviewed_lookup(context):
        return []
    from unittest.mock import AsyncMock
    original_tool = EXTERNAL_TOOLS["username_finder"]
    from pytest import MonkeyPatch
    with MonkeyPatch.context() as patch:
        lookup = AsyncMock(side_effect=reviewed_lookup)
        patch.setattr(original_tool, "execute", lookup)
        planned = await service.submit_tool(review_id, uuid.UUID(session["id"]), ToolRequest(tool_name="username_finder",
            inputs=ToolInputs(username="new_pivot"), source_entity_ids=[observation.entity_id], rationale="Follow observed alias", pivot=plan))
        await service.tasks[uuid.UUID(planned["id"])]
        lookup.assert_awaited_once()
        recorded = await service.execution(review_id, uuid.UUID(planned["id"]))
        assert recorded["input_summary"]["pivot"] == plan.model_dump()
    async with service.session_factory() as db:
        source = await db.get(Investigation, source_id)
        source.metrics = {"engine_used": "rules"}
        await db.commit()
    legacy_review = await service.create_review(source_id)
    assert not legacy_review["coverage_known"]
    context = await service.context(uuid.UUID(legacy_review["id"]))
    assert context["scan_coverage"] == {}
    await service.close_session(review_id, uuid.UUID(session["id"]), "finish")
    async with service.session_factory() as db:
        review = await db.get(Investigation, review_id)
        assert review.metrics["tools_executed"] == 1
        assert review.metrics["tool_execution_seconds"] >= 0
        assert review.metrics["new_findings"] == 0
    with pytest.raises(HTTPException) as exc:
        await service.create_review(review_id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_mcp_results_notes_and_sessions_are_visible_in_web_api(isolated_workspace, monkeypatch):
    import app.api.v1.investigations as investigations_api
    import app.api.v1.workspace as notes_api
    import app.mcp.server as mcp_module
    import app.main as main
    import app.api.v1.stream as stream_api
    from app.api.v1.metrics import engine_of

    service, legacy_id = isolated_workspace
    async with service.session_factory() as db:
        legacy = await db.get(Investigation, legacy_id)
        assert legacy.execution_mode == "internal" and legacy.revision == 0
    monkeypatch.setattr(mcp_module, "workspace", service)
    monkeypatch.setattr(investigations_api, "workspace", service)
    monkeypatch.setattr(notes_api, "workspace", service)
    monkeypatch.setattr(stream_api, "async_session_maker", service.session_factory)
    monkeypatch.setitem(EXTERNAL_TOOLS, "username_finder", FixtureTool())
    async def get_test_db():
        async with service.session_factory() as db:
            yield db
    main.app.dependency_overrides[get_db] = get_test_db

    try:
        async with mcp_module.mcp.session_manager.run():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://127.0.0.1:8000",
                headers={"Authorization": "Bearer integration-token", "Accept": "application/json, text/event-stream"}) as client:
                counter = 0
                async def call(name, arguments):
                    nonlocal counter
                    counter += 1
                    response = await client.post("/mcp", json={"jsonrpc": "2.0", "id": counter, "method": "tools/call",
                                                              "params": {"name": name, "arguments": arguments}})
                    assert response.status_code == 200, response.text
                    result = response.json()["result"]
                    assert not result.get("isError"), result
                    return result["structuredContent"]

                created = await call("create_investigation", {"target": {"username": "fixture"}})
                inv_id = created["id"]
                assert created["execution_mode"] == "external" and created["status"] == "pending"
                assert created["web_url"].endswith(inv_id)
                session = await call("open_session", {"investigation_id": inv_id, "client": "codex-fixture", "model": "declared-test-model"})
                args = {"investigation_id": inv_id, "session_id": session["id"], "inputs": {"username": "fixture"}, "rationale": "Verify public candidate"}
                execution = await call("username_finder", args)
                await service.tasks[uuid.UUID(execution["id"])]
                status = await call("get_execution", {"investigation_id": inv_id, "execution_id": execution["id"]})
                assert status["status"] == "completed" and len(status["entity_ids"]) == 1
                entity_id = status["entity_ids"][0]
                reused = await call("username_finder", args)
                assert reused["id"] == execution["id"] and reused["reused"] is True
                refreshed = await call("username_finder", {**args, "force": True})
                await service.tasks[uuid.UUID(refreshed["id"])]
                async with service.session_factory() as db:
                    entities = list((await db.scalars(select(Entity).where(Entity.investigation_id == uuid.UUID(inv_id)))).all())
                    observations = list((await db.scalars(select(EntityObservation).where(EntityObservation.investigation_id == uuid.UUID(inv_id)))).all())
                    assert len(entities) == 1 and str(entities[0].id) == entity_id and len(observations) == 2

                note = await call("add_analysis_note", {"investigation_id": inv_id, "session_id": session["id"],
                    "note": {"kind": "insight", "title": "Evidence worth reviewing", "content": "A public biography gives a useful next step.",
                             "entity_ids": [entity_id], "execution_ids": [execution["id"]], "evidence_urls": ["https://example.test/source"],
                             "details": {"next_question": "Does the public profile link another account?"}}})
                assert note["author"] == "codex-fixture" and note["author_type"] == "agent"
                web = (await client.get(f"/api/v1/investigations/{inv_id}")).json()
                assert len(web["entities"]) == 1 and web["analysis_notes"][0]["id"] == note["id"]
                assert web["revision"] >= 5 and web["sessions"][0]["model"] == "declared-test-model"
                graph = (await client.get(f"/api/v1/investigations/{inv_id}/graph")).json()
                assert len(graph["nodes"]) == 2
                trace = (await client.get(f"/api/v1/investigations/{inv_id}/trace")).json()
                assert len(trace["observations"]) == 2
                assert all(item["session_id"] == session["id"] for item in trace["executions"])
                analyst = await client.post(f"/api/v1/investigations/{inv_id}/notes", json={"title": "Human review", "content": "Review recorded."})
                assert analyst.status_code == 201 and analyst.json()["author_type"] == "analyst"
                await call("finish_session", {"investigation_id": inv_id, "session_id": session["id"], "summary": "Authored summary with public evidence."})
                completed = (await client.get(f"/api/v1/investigations/{inv_id}")).json()
                assert completed["status"] == "completed" and completed["metrics"]["engine_used"] == "external"
                assert completed["summary"] == "Authored summary with public evidence."
                assert completed["metrics"]["external_sessions"] == 1
                assert 0 <= completed["metrics"]["execution_time_seconds"] <= completed["metrics"]["elapsed_wall_seconds"]
                async with service.session_factory() as db:
                    assert engine_of(await db.get(Investigation, uuid.UUID(inv_id))) == "external"

                # A completed external dossier stays subscribed: a new session can update an open web page.
                streamed = await stream_api.stream_investigation_events(uuid.UUID(inv_id))
                generator = streamed.body_iterator
                assert '"connected"' in await anext(generator)
                assert '"workspace_snapshot"' in await anext(generator)
                for _ in range(len(event_bus.get_history(inv_id))):
                    await anext(generator)
                continued = await call("open_session", {"investigation_id": inv_id, "client": "claude-fixture"})
                assert continued["id"] != session["id"]
                assert '"session_start"' in await asyncio.wait_for(anext(generator), timeout=2)
                await generator.aclose()
                await call("pause_session", {"investigation_id": inv_id, "session_id": continued["id"]})
                reopened = await call("get_investigation_context", {"investigation_id": inv_id})
                assert reopened["total_findings"] == 1 and len(reopened["notes"]) == 3
                assert reopened["investigation"]["status"] == "paused"
                assert reopened["investigation"]["metrics"]["external_sessions"] == 2
    finally:
        main.app.dependency_overrides.pop(get_db, None)


@pytest.mark.asyncio
async def test_session_conflicts_reference_isolation_and_restart_recovery(isolated_workspace, monkeypatch):
    from fastapi import HTTPException
    service, _ = isolated_workspace
    async with service.session_factory() as db:
        one = await service.create(InvestigationCreate(target=TargetCreate(username="one"), execution_mode="external"), db)
        two = await service.create(InvestigationCreate(target=TargetCreate(username="two"), execution_mode="external"), db)
    session = await service.open_session(one.id, SessionCreate(client="codex"))
    with pytest.raises(HTTPException) as conflict:
        await service.open_session(one.id, SessionCreate(client="claude"))
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException) as missing:
        await service.add_note(one.id, NoteCreate(title="Invalid reference", content="Must not cross dossiers.", entity_ids=[uuid.uuid4()]), uuid.UUID(session["id"]))
    assert missing.value.status_code == 422
    with pytest.raises(HTTPException) as cross:
        await service.submit_tool(two.id, uuid.UUID(session["id"]), ToolRequest(tool_name="username_finder"))
    assert cross.value.status_code == 404

    class SlowTool(FixtureTool):
        async def execute(self, context):
            await asyncio.Event().wait()
    monkeypatch.setitem(EXTERNAL_TOOLS, "username_finder", SlowTool())
    execution = await service.submit_tool(one.id, uuid.UUID(session["id"]), ToolRequest(tool_name="username_finder"))
    with pytest.raises(HTTPException) as busy:
        await service.close_session(one.id, uuid.UUID(session["id"]), "finish")
    assert busy.value.status_code == 409
    await asyncio.sleep(0)  # Allow the background coroutine to enter its cancellation handler.
    await service.shutdown()
    persisted = await service.execution(one.id, uuid.UUID(execution["id"]))
    assert persisted["status"] == "failed" and persisted["completed_at"]
    async with service.session_factory() as db:
        assert (await db.get(Investigation, one.id)).status == "paused"
        assert (await db.get(InvestigationSession, uuid.UUID(session["id"]))).status == "paused"
    assert (await service.open_session(one.id, SessionCreate(client="codex")))["id"] != session["id"]


@pytest.mark.asyncio
async def test_parallel_batch_preserves_evidence_runtime_and_web_state(isolated_workspace, monkeypatch):
    from fastapi import HTTPException
    service, _ = isolated_workspace
    monkeypatch.setattr(settings, "mcp_max_parallel_tools", 3)
    async with service.session_factory() as db:
        inv = await service.create(InvestigationCreate(target=TargetCreate(username="fixture"), execution_mode="external"), db)
    session = await service.open_session(inv.id, SessionCreate(client="codex"))
    session_id = uuid.UUID(session["id"])
    release = asyncio.Event()
    ready = asyncio.Event()
    started = set()

    class ConcurrentTool(FixtureTool):
        def __init__(self, name):
            self.name = name
        async def execute(self, context):
            started.add(self.name)
            if len(started) == 3:
                ready.set()
            await release.wait()
            context.extra[f"{self.name}_cache"] = {"done": 1}
            if self.name == "username_finder":
                assert context.extra["username_scan_mode"] == "fast"
                context.extra["username_finder_coverage"] = {"fixture": 2}
                context.extra["username_finder_scanned"] = {"fixture"}
            if self.name == "search_dorker":
                q = context.extra["search_queries"][0]
                assert q["include_domains"] == ["github.com"]
                context.extra["search_queries_executed"] = [[q["query"], q["include_domains"]]]
                context.extra["search_queries_used"] = 1
            return [ToolFinding(entity_type="social_account", platform="github", value="https://github.com/fixture",
                                metadata_info={f"from_{self.name}": True, "page_text": "Captured public body", "page_excerpt": "Public excerpt"},
                                evidence_urls=[f"https://example.test/{self.name}"])]

    for name in ("username_finder", "social_verifier", "search_dorker", "email_checker"):
        monkeypatch.setitem(EXTERNAL_TOOLS, name, ConcurrentTool(name))
    requests = [ToolRequest(tool_name="username_finder"), ToolRequest(tool_name="social_verifier"),
                ToolRequest(tool_name="search_dorker", inputs=ToolInputs(queries=[
                    SearchQuery(query='"fixture" publication', rationale="Follow observed profile", include_domains=["github.com"])]))]
    batch = await service.submit_batch(inv.id, session_id, requests)
    assert all(item["accepted"] for item in batch["results"])
    execution_ids = [uuid.UUID(item["execution"]["id"]) for item in batch["results"]]
    await asyncio.wait_for(ready.wait(), 2)  # All three execute concurrently, not just queued.
    pending = await service.executions(inv.id, execution_ids)
    assert pending["running_count"] == 3
    reused = await service.submit_tool(inv.id, session_id, requests[0])
    assert reused["reused"] and uuid.UUID(reused["id"]) == execution_ids[0]
    rejected = await service.submit_batch(inv.id, session_id, [ToolRequest(tool_name="email_checker")])
    assert rejected["results"][0]["accepted"] is False and rejected["results"][0]["status_code"] == 409
    with pytest.raises(HTTPException) as busy:
        await service.close_session(inv.id, session_id, "finish")
    assert busy.value.status_code == 409
    await service.add_note(inv.id, NoteCreate(title="Work in progress", content="Reviewing evidence while tools run."), session_id)
    waiting = asyncio.create_task(service.executions(inv.id, execution_ids, wait_seconds=2))
    tasks = [service.tasks[execution_id] for execution_id in execution_ids]
    release.set()
    await asyncio.gather(*tasks)
    await waiting
    completed = await service.executions(inv.id, execution_ids)
    assert completed["running_count"] == 0 and all(item["status"] == "completed" for item in completed["executions"])

    web = await service.detail(inv.id)
    assert len(web["entities"]) == 1
    entity = web["entities"][0]
    assert set(entity["metadata_info"]["source_tools"]) == {request.tool_name for request in requests}
    assert len(entity["metadata_info"]["evidence_urls"]) == 3
    assert web["analysis_notes"][0]["title"] == "Work in progress"
    assert web["metrics"]["external_peak_parallel_tools"] == 3
    async with service.session_factory() as db:
        observations = list((await db.scalars(select(EntityObservation).where(EntityObservation.investigation_id == inv.id))).all())
        assert len(observations) == 3 and len({item.entity_id for item in observations}) == 1
    runtime = service.contexts[inv.id].extra
    assert all(runtime[f"{name}_cache"]["done"] == 1 for name in started)
    compact = (await service.findings(inv.id))["findings"][0]["metadata_info"]
    assert "page_text" not in compact and compact["content_available"]
    full = await service.findings(inv.id, entity_id=uuid.UUID(entity["id"]), include_content=True)
    assert full["findings"][0]["metadata_info"]["page_text"] == "Captured public body"
    await service.close_session(inv.id, session_id, "pause")
    service.contexts.clear()  # Simulate losing in-memory caches on restart.
    resumed = await service.context(inv.id)
    assert resumed["scan_coverage"] == {"fixture": 2}
    assert resumed["execution_policy"]["search_queries_remaining"] == settings.tavily_max_queries - 1
    assert not resumed["execution_policy"]["active_tools"]

    # When there is free capacity, overlapping the same tool is still rejected.
    second = await service.open_session(inv.id, SessionCreate(client="codex"))
    release.clear()
    next_job = await service.submit_tool(inv.id, uuid.UUID(second["id"]), ToolRequest(tool_name="username_finder", inputs=ToolInputs(username="another")))
    with pytest.raises(HTTPException) as same_tool:
        await service.submit_tool(inv.id, uuid.UUID(second["id"]), ToolRequest(tool_name="username_finder", inputs=ToolInputs(username="different")))
    assert same_tool.value.status_code == 409
    release.set()
    await service.tasks[uuid.UUID(next_job["id"])]
