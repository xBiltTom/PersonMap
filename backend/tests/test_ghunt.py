"""Native GHunt worker exercised through mocked HTTP, without real credentials."""
import asyncio
import base64
import json
import sys
import subprocess
from pathlib import Path

import httpx
import pytest

from app.agent.tool_dispatch import build_call_context, build_tool_schemas
from app.core.config import settings
from app.core.runtime import durable_runtime
from app.engine.pivot_rules import extract_and_apply_pivots
from app.engine.rule_engine import RuleEngine
from app.models.target import Target
from app.services.workspace import call_fingerprint
from app.tools import ghunt as adapter, ghunt_runner, http_client
from app.tools.base import TargetContext
from app.tools.ghunt import GHuntTool
from app.tools.ghunt_runtime import ROOT, capabilities, config_id, drive_resource, python_path, queries
from app.tools.google_account_osint import GoogleAccountOSINTTool

GAIA = "123456789012345678901"
EMAIL = "audit@example.org"
FILE_ID = "audit_document_12345"


@pytest.fixture
def session(monkeypatch, tmp_path):
    path = tmp_path / "creds.m"
    creds = {"cookies": {"SAPISID": "audit-cookie-secret", "SID": "audit-session-secret"},
             "osids": {},
             "android": {"master_token": "audit-master-secret", "authorization_tokens": {
                 "drive": {"token": "audit-drive-secret", "expiry": 4102444800},
                 "playgames": {"token": "audit-player-secret", "expiry": 4102444800}}}}
    path.write_bytes(base64.b64encode(json.dumps(creds).encode()))
    path.chmod(0o600)
    monkeypatch.setattr(settings, "ghunt_enabled", True)
    monkeypatch.setattr(settings, "ghunt_credentials_file", str(path))
    monkeypatch.setattr(settings, "ghunt_python", None)
    monkeypatch.setattr(settings, "ghunt_worker_timeout", 30)
    return path


def native_runtime():
    if not (ROOT / "integrations/ghunt/.venv/lib/python3.12/site-packages/ghunt").is_dir():
        pytest.skip("Install the isolated GHunt runtime to exercise upstream code")


def profile_payload(container="PROFILE"):
    return {"personId": GAIA, "metadata": {"identityInfo": {"sourceIds": [{"container": container}]}},
            "email": [{"value": EMAIL, "metadata": {"container": container}}]}


def stats_payload():
    data = [None] * 17
    data[16] = [None] * 9
    data[16][8] = [[[None] * 6 + [name, value] for name, value in [("Reviews", 2), ("Ratings", 1), ("Photos", 0)]]]
    return ")]}'\n" + json.dumps(data)


def bridge_http(monkeypatch, responder):
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(responder), follow_redirects=False))


def authenticated_response(request):
    if request.url.path == "/CheckCookie":
        return httpx.Response(302, headers={"location": "https://www.google.com/robots.txt"})
    if request.url.path == "/v2/people/lookup":
        return httpx.Response(200, json={"people": {"audit": profile_payload()}})
    if request.url.path == "/v2/people":
        return httpx.Response(200, json={"personResponse": [{"status": "SUCCESS", "person": profile_payload()}]})
    if request.url.path == "/locationhistory/preview/mas":
        return httpx.Response(200, text=stats_payload())
    return httpx.Response(404, json={"error": {"code": 404}})


@pytest.mark.asyncio
async def test_native_email_profile_maps_and_gaia_pivot(session, monkeypatch):
    native_runtime()
    bridge_http(monkeypatch, authenticated_response)
    monkeypatch.setattr(settings, "ghunt_services", ["maps"])
    context = TargetContext(email=EMAIL)
    signature = config_id()
    findings = await GHuntTool().execute(context)
    assert len(findings) == 1, context.extra
    assert findings[0].entity_type == "google_account"
    assert findings[0].metadata_info["maps_statistics"]["Reviews"] == 2
    assert findings[0].metadata_info["ownership_status"] == "unverified"
    assert "emails" not in findings[0].metadata_info
    assert extract_and_apply_pivots(findings, context)
    assert {"value": GAIA, "id_type": "gaia_id"} in context.extra["maigret_identifiers"]
    assert context.all_usernames() == []
    assert not GHuntTool().can_run(context)  # Do not query the same profile again after the email -> GAIA pivot.
    assert config_id() == signature  # Cookie refresh must not reset per-investigation budgets.
    assert session.stat().st_mode & 0o777 == 0o600
    assert "audit-cookie-secret" not in json.dumps(durable_runtime(context.extra))
    assert not any(name == "ghunt" or name.startswith("ghunt.") for name in sys.modules)


@pytest.mark.asyncio
async def test_native_gaia_input(session, monkeypatch):
    native_runtime()
    bridge_http(monkeypatch, authenticated_response)
    monkeypatch.setattr(settings, "ghunt_services", [])
    context = TargetContext(extra={"maigret_identifiers": [{"value": GAIA, "id_type": "gaia_id"}]})
    findings = await GHuntTool().execute(context)
    assert len(findings) == 1
    assert findings[0].metadata_info["query_kind"] == "gaia"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["email", "gaia"])
@pytest.mark.parametrize("public_cover", [False, True])
async def test_native_incomplete_cover_keeps_profile_and_container_boundaries(session, monkeypatch, kind, public_cover):
    native_runtime()
    payload = profile_payload()
    payload["coverPhoto"] = [
        {"imageUrl": "https://lh3.googleusercontent.com/unscoped-secret=w100", "metadata": {}},
        {"imageUrl": "https://lh3.googleusercontent.com/contact-secret=w100",
         "metadata": {"container": "CONTACT"}},
        {"metadata": {"container": "PROFILE"}},
    ]
    if public_cover:
        payload["coverPhoto"].append({"imageUrl": "https://lh3.googleusercontent.com/public-cover=w100",
                                      "metadata": {"container": "PROFILE"}})
    def response(request):
        if request.url.path == "/v2/people/lookup":
            return httpx.Response(200, json={"people": {"audit": payload}})
        if request.url.path == "/v2/people":
            return httpx.Response(200, json={"personResponse": [{"status": "SUCCESS", "person": payload}]})
        return authenticated_response(request)
    bridge_http(monkeypatch, response)
    monkeypatch.setattr(settings, "ghunt_services", [])
    context = (TargetContext(email=EMAIL) if kind == "email" else
               TargetContext(extra={"maigret_identifiers": [{"value": GAIA, "id_type": "gaia_id"}]}))
    findings = await GHuntTool().execute(context)
    assert len(findings) == 1, context.extra
    if public_cover:
        assert findings[0].metadata_info["cover_url"] == "https://lh3.googleusercontent.com/public-cover"
    else:
        assert "cover_url" not in findings[0].metadata_info
    assert context.extra["ghunt_diagnostics"][kind + ":" + (EMAIL if kind == "email" else GAIA)]["warnings"] == ["incomplete_cover_ignored"]
    exported = json.dumps([finding.metadata_info for finding in findings])
    assert "unscoped-secret" not in exported
    assert "contact-secret" not in exported


@pytest.mark.asyncio
@pytest.mark.parametrize("container", ["CONTACT", "AFFINITY"])
async def test_native_operator_contacts_are_not_public_profiles(session, monkeypatch, container):
    native_runtime()
    def response(request):
        if request.url.path == "/v2/people/lookup":
            return httpx.Response(200, json={"people": {"audit": profile_payload(container)}})
        return authenticated_response(request)
    bridge_http(monkeypatch, response)
    context = TargetContext(email=EMAIL)
    assert await GHuntTool().execute(context) == []
    assert context.extra["ghunt_diagnostics"]["email:" + EMAIL]["status"] == "no_public_profile"


@pytest.mark.asyncio
@pytest.mark.parametrize("code,status", [(200, "upstream_error"), (401, "session_expired"), (429, "rate_limited")])
async def test_native_generic_login_and_failures_never_prove_existence(session, monkeypatch, code, status):
    native_runtime()
    def response(request):
        if request.url.path == "/v2/people/lookup":
            return httpx.Response(code, text="<html>Generic login page</html>" * 20)
        return authenticated_response(request)
    bridge_http(monkeypatch, response)
    context = TargetContext(email=EMAIL)
    assert await GHuntTool().execute(context) == []
    assert context.extra["ghunt_diagnostics"]["email:" + EMAIL]["status"] == status


@pytest.mark.asyncio
async def test_native_calendar_is_anonymous_bounded_and_survives_other_service_error(session, monkeypatch):
    native_runtime()
    seen = []
    def response(request):
        seen.append(request)
        if "/calendar/v3/calendars/" in request.url.path:
            assert "authorization" not in request.headers
            assert "cookie" not in request.headers
            if request.url.path.endswith("/events"):
                assert request.url.params["maxResults"] == "2"
                return httpx.Response(200, json={"nextPageToken": "more", "items": [
                    {"summary": "Public event", "start": {"dateTime": "2026-10-20T12:00:00Z"},
                     "end": {"dateTime": "2026-10-20T13:00:00Z"}}]})
            return httpx.Response(200, json={"id": EMAIL, "summary": "Public calendar", "timeZone": "UTC"})
        if request.url.path == "/locationhistory/preview/mas":
            return httpx.Response(429, text="rate limit")
        return authenticated_response(request)
    bridge_http(monkeypatch, response)
    monkeypatch.setattr(settings, "ghunt_services", ["maps", "calendar"])
    monkeypatch.setattr(settings, "ghunt_max_events", 2)
    context = TargetContext(email=EMAIL)
    findings = await GHuntTool().execute(context)
    assert len(findings) == 2, context.extra
    calendar = next(item for item in findings if item.platform == "google_calendar")
    assert calendar.metadata_info["access_context"] == "anonymous"
    assert calendar.metadata_info["truncated"]
    assert calendar.metadata_info["events"][0]["summary"] == "Public event"
    assert context.extra["ghunt_diagnostics"]["email:" + EMAIL]["services"]["maps"] == "rate_limited"


@pytest.mark.asyncio
@pytest.mark.parametrize("public", [True, False])
async def test_native_drive_public_boundary_and_collaborators_do_not_pivot(session, monkeypatch, public):
    native_runtime()
    def response(request):
        if request.url.path == "/drive/v2internal/files/" + FILE_ID:
            return httpx.Response(200, json={"id": FILE_ID, "title": "Audit document", "mimeType": "application/pdf",
                "permissions": ([{"id": "anyoneWithLink", "type": "anyone", "role": "reader"}] if public else []) + [
                    {"id": GAIA, "type": "user", "role": "owner", "emailAddress": EMAIL, "name": "Audit owner", "userId": GAIA}]})
        return authenticated_response(request)
    bridge_http(monkeypatch, response)
    context = TargetContext(extra={"candidate_urls": [f"https://drive.google.com/file/d/{FILE_ID}/view"]})
    findings = await GHuntTool().execute(context)
    assert len(findings) == int(public), context.extra
    if public:
        assert findings[0].metadata_info["participants"][0]["email"] == EMAIL
        extract_and_apply_pivots(findings, context)
        assert context.discovered_emails == []
        assert context.extra.get("maigret_identifiers", []) == []


@pytest.mark.asyncio
async def test_missing_and_invalid_sessions_are_visible_without_remote_requests(session, monkeypatch):
    native_runtime()
    monkeypatch.setattr(settings, "ghunt_credentials_file", None)
    context = TargetContext(email=EMAIL)
    assert await GHuntTool().execute(context) == []
    assert context.extra["ghunt_diagnostics"]["email:" + EMAIL]["status"] == "session_not_configured"
    assert not GHuntTool().can_run(context)
    monkeypatch.setattr(settings, "ghunt_credentials_file", str(session))
    session.write_text("invalid-session-do-not-log")
    assert GHuntTool().can_run(context)
    assert await GHuntTool().execute(context) == []
    assert context.extra["ghunt_diagnostics"]["email:" + EMAIL]["status"] == "session_invalid"
    assert "invalid-session-do-not-log" not in json.dumps(context.extra)


@pytest.mark.asyncio
async def test_account_budget_is_durable_across_pivots(session, monkeypatch):
    calls = []
    async def lookup(query, services):
        calls.append(query)
        return {"status": "not_found"}
    monkeypatch.setattr(adapter, "run_ghunt", lookup)
    monkeypatch.setattr(settings, "ghunt_max_queries", 1)
    context = TargetContext(email=EMAIL)
    await GHuntTool().execute(context)
    context.discovered_emails.append("other@example.org")
    assert not GHuntTool().can_run(context)
    assert len(calls) == 1
    assert durable_runtime(context.extra)["ghunt_checked"] == ["email:" + EMAIL]


@pytest.mark.asyncio
async def test_expired_session_stops_batch_and_timeout_does_not_break_other_tool(session, monkeypatch):
    async def expired(query, services):
        return {"status": "session_expired"}
    monkeypatch.setattr(adapter, "run_ghunt", expired)
    context = TargetContext(email=EMAIL, discovered_emails=["second@example.org"])
    assert await GHuntTool().execute(context) == []
    assert len(context.extra["ghunt_checked"]) == 2
    async def timeout(query, services):
        raise asyncio.TimeoutError()
    monkeypatch.setattr(adapter, "run_ghunt", timeout)
    context = TargetContext(email=EMAIL)
    assert await GHuntTool().execute(context) == []
    assert context.extra["ghunt_diagnostics"]["email:" + EMAIL]["status"] == "timeout"


@pytest.mark.asyncio
async def test_public_discovery_never_posts_account_recovery_and_scholar_runs_once(monkeypatch):
    seen = []
    def response(request):
        seen.append(request)
        return httpx.Response(200, text="<html>Generic login page</html>" * 30)
    bridge_http(monkeypatch, response)
    context = TargetContext(email="audit@gmail.com", full_name="Audit User", discovered_emails=["other@gmail.com"])
    tool = GoogleAccountOSINTTool()
    assert await tool.execute(context) == []
    assert await tool.execute(context) == []
    assert all(request.method == "GET" for request in seen)
    assert sum(request.url.host == "scholar.google.com" for request in seen) == 1


@pytest.mark.parametrize("url", ["http://drive.google.com/file/d/audit_document_12345/view",
    "https://drive.google.com.evil.test/file/d/audit_document_12345/view", "https://localhost/file/d/audit_document_12345/view",
    "https://drive.google.com@evil.test/file/d/audit_document_12345/view", "https://drive.google.com/unknown/audit_document_12345"])
def test_drive_inputs_reject_unrelated_and_spoofed_urls(url):
    assert drive_resource(url) is None


def test_schemas_and_fingerprints_allow_gaia_without_aliases(session):
    context = build_call_context({"identifiers": [{"value": GAIA, "id_type": "gaia_id"}]}, Target(extra_data={}))
    other = TargetContext(extra={"maigret_identifiers": [{"value": "987654321098765432109", "id_type": "gaia_id"}]})
    assert GHuntTool().can_run(context)
    assert queries(context) == [{"kind": "gaia", "value": GAIA}]
    assert call_fingerprint("ghunt", context) != call_fingerprint("ghunt", other)
    assert RuleEngine()._get_tool_run_key(GHuntTool(), context) != RuleEngine()._get_tool_run_key(GHuntTool(), other)
    schema = next(item["function"]["parameters"] for item in build_tool_schemas() if item["function"]["name"] == "ghunt")
    assert {"required": ["identifiers"]} in schema["anyOf"]
    assert "audit-master-secret" not in json.dumps(capabilities())


@pytest.mark.asyncio
@pytest.mark.parametrize("url", ["https://127.0.0.1/x", "https://google.com.evil.test/x", "http://www.google.com/x"])
async def test_transport_rejects_non_google_destinations(url):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: pytest.fail("Unexpected request"))) as client:
        with pytest.raises(ValueError):
            await ghunt_runner.perform_request(client, {"url": url, "method": "GET"})


@pytest.mark.asyncio
async def test_redirect_rejected_and_child_owns_cookies():
    seen = []
    def response(request):
        seen.append(request)
        assert "cookie" not in request.headers
        return httpx.Response(302, headers={"location": "https://evil.test/steal"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response), cookies={"secret": "operator"}) as client:
        with pytest.raises(ValueError):
            await ghunt_runner.perform_request(client, {"url": "https://www.google.com/", "method": "GET"})
    assert len(seen) == 1


@pytest.mark.asyncio
async def test_native_cookie_validation_reads_regional_setsid_without_following(session, monkeypatch):
    native_runtime()
    seen = []
    def response(request):
        seen.append(request)
        assert request.url.host == "accounts.google.com"
        assert request.url.path == "/CheckCookie"
        return httpx.Response(302, headers={"location": "https://accounts.google.com.pe/accounts/SetSID?ssdc=synthetic-secret"})
    bridge_http(monkeypatch, response)
    result = await ghunt_runner.run_ghunt({"kind": "status", "value": ""}, [])
    assert result["status"] == "authenticated", result
    assert result["requests"] == 1 and len(seen) == 1
    assert "synthetic-secret" not in json.dumps(result)
    assert not ghunt_runner.allowed_url("https://accounts.google.com.pe/accounts/SetSID")


@pytest.mark.parametrize("source,destination", [
    ("https://accounts.google.com/CheckCookie", "https://accounts.google.com.pe.evil.test/accounts/SetSID"),
    ("https://accounts.google.com/CheckCookie", "https://evil.test/accounts/SetSID"),
    ("https://accounts.google.com/CheckCookie", "https://accounts.google.com.pe/other"),
    ("https://accounts.google.com/other", "https://accounts.google.com.pe/accounts/SetSID"),
    ("https://accounts.google.com/CheckCookie", "http://accounts.google.com.pe/accounts/SetSID"),
])
def test_regional_callback_exception_is_narrow(source, destination):
    assert not ghunt_runner.cookie_validation_redirect(source, destination)


@pytest.mark.asyncio
async def test_traditional_engine_continues_without_session(session, monkeypatch):
    from app.tools.registry import tool_registry
    from app.tools.base import BaseTool, ToolCategory, ToolFinding
    class IndependentTool(BaseTool):
        name, description, category, required_inputs = "independent", "Audit", ToolCategory.EMAIL, ["email"]
        async def execute(self, context):
            return [ToolFinding(entity_type="email", value=EMAIL, metadata_info={"source_tool": self.name})]
    monkeypatch.setattr(settings, "ghunt_credentials_file", None)
    monkeypatch.setattr(tool_registry, "get_all", lambda: [GHuntTool(), IndependentTool()])
    result = await RuleEngine().collect_findings("ghunt-audit", Target(email=EMAIL, extra_data={}))
    assert [item.value for item in result.findings] == [EMAIL]
    assert result.context.extra["ghunt_diagnostics"]["runtime"]["status"] == "session_not_configured"


@pytest.mark.asyncio
async def test_native_play_games_binary_rpc_keeps_search_result_as_candidate(session, monkeypatch):
    native_runtime()
    # Serialized using GHunt's original PlayerSearchResultsProto, containing a synthetic player.
    payload = base64.b64decode("AAAAAGUKY7KUqt4FXQpbClnSvd74BlMaMAouaHR0cHM6Ly9saDMuZ29vZ2xldXNlcmNvbnRlbnQuY29tL2F1ZGl0LWF2YXRhcjIfChBwbGF5ZXItYXVkaXQtMTIzGgtBdWRpdFBsYXllcg==")
    def response(request):
        if request.url.host == "playgateway-pa.googleapis.com":
            assert request.method == "POST"
            assert EMAIL.encode() in request.content
            assert request.headers["authorization"] == "OAuth audit-player-secret"
            return httpx.Response(200, content=payload, headers={"content-type": "application/grpc"})
        return authenticated_response(request)
    bridge_http(monkeypatch, response)
    monkeypatch.setattr(settings, "ghunt_services", ["play_games"])
    context = TargetContext(email=EMAIL)
    findings = await GHuntTool().execute(context)
    player = next(item for item in findings if item.platform == "google_play_games")
    assert player.display_name == "AuditPlayer"
    assert player.metadata_info["association"] == "search_candidate"
    assert player.metadata_info["verification_status"] == "candidate"
    extract_and_apply_pivots([player], context)
    assert context.all_usernames() == []


@pytest.mark.asyncio
async def test_worker_cancellation_reaps_child_and_releases_session_lock(session, monkeypatch):
    native_runtime()
    started = asyncio.Event()
    processes = []
    spawn = asyncio.create_subprocess_exec
    async def remember(*args, **kwargs):
        process = await spawn(*args, **kwargs)
        processes.append(process)
        return process
    async def hang(client, message):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(ghunt_runner.asyncio, "create_subprocess_exec", remember)
    monkeypatch.setattr(ghunt_runner, "perform_request", hang)
    task = asyncio.create_task(ghunt_runner.run_ghunt({"kind": "email", "value": EMAIL}, []))
    await asyncio.wait_for(started.wait(), 10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert processes[0].returncode is not None
    assert not ghunt_runner.session_lock().locked()


@pytest.mark.asyncio
async def test_http_capabilities_and_mcp_contract_do_not_expose_session(session):
    from app.main import app
    from app.mcp.server import mcp
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8000") as client:
        response = await client.get("/api/v1/ghunt/capabilities")
    assert response.status_code == 200
    assert response.json()["status"] == "configured"
    assert str(session) not in response.text and "audit-master-secret" not in response.text
    tools = {tool.name: tool for tool in await mcp.list_tools()}
    assert tools["get_ghunt_capabilities"].annotations.readOnlyHint
    assert tools["ghunt"].inputSchema["required"] == ["investigation_id", "session_id"]


def test_operator_login_commits_complete_session_privately_without_echo(session, tmp_path):
    native_runtime()
    destination = tmp_path / "new-session" / "creds.m"
    code = '''
import asyncio, getpass, importlib.util, sys
from pathlib import Path
from ghunt.helpers import auth
spec = importlib.util.spec_from_file_location("personmap_ghunt_worker", sys.argv[1])
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
getpass.getpass = lambda prompt: "aas_et/test-master-must-not-print"
async def generate(client, creds, osids):
    assert osids == [], "Unused service OSIDs must not block native API authentication"
    creds.android.authorization_tokens["accounts"] = {"token": "secret", "expiry": 4102444800}
    creds.save_creds(silent=True)
    assert not Path(sys.argv[2]).exists(), "Incomplete session saved during authentication"
    creds.cookies, creds.osids = {"SAPISID": "test-cookie"}, {}
async def valid(client, cookies):
    return cookies.get("SAPISID") == "test-cookie"
auth.gen_cookies_and_osids = generate
auth.check_cookies = valid
assert asyncio.run(worker.login(sys.argv[2])) == 0
assert asyncio.run(worker.login(sys.argv[2])) == 2
'''
    result = subprocess.run([str(python_path()), "-I", "-c", code, str(ROOT / "app/tools/ghunt_worker.py"), str(destination)],
        text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert destination.stat().st_mode & 0o777 == 0o600
    data = json.loads(base64.b64decode(destination.read_bytes()))
    assert data["android"]["master_token"] == "aas_et/test-master-must-not-print"
    assert data["cookies"]["SAPISID"] == "test-cookie"
    assert "test-master-must-not-print" not in result.stdout + result.stderr


def test_login_resumes_after_exchange_without_reusing_oauth_or_echoing_errors(session, tmp_path):
    native_runtime()
    destination = tmp_path / "resume-session" / "creds.m"
    code = '''
import asyncio, base64, getpass, importlib.util, json, sys
from pathlib import Path
import httpx
from ghunt.helpers import auth
spec = importlib.util.spec_from_file_location("personmap_worker", sys.argv[1])
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
calls = {"exchange": 0, "check": 0, "prompt": 0}
def prompt(message):
    calls["prompt"] += 1
    return base64.b64encode(json.dumps({"oauth_token": "oauth2_4/synthetic-never-print",
        "cookies": {"SID": "synthetic-sid", "SAPISID": "synthetic-sapisid"}}).encode()).decode()
getpass.getpass = prompt
async def exchange(client, oauth):
    calls["exchange"] += 1
    assert calls["exchange"] == 1
    return "aas_et/synthetic-master-never-print", [], "", ""
async def check(client, cookies):
    calls["check"] += 1
    if calls["check"] == 1:
        raise httpx.ConnectError("synthetic-sensitive-error-must-not-print")
    return cookies["SAPISID"] == "synthetic-sapisid"
async def generate(*args, **kwargs):
    raise AssertionError("Companion cookies should be validated and preserved")
auth.android_master_auth, auth.check_cookies, auth.gen_cookies_and_osids = exchange, check, generate
destination = Path(sys.argv[2])
checkpoint = destination.with_name(destination.name + ".ghunt-pending")
assert asyncio.run(worker.login(str(destination))) == 1
assert not destination.exists()
assert checkpoint.stat().st_mode & 0o777 == 0o600
pending = json.loads(base64.b64decode(checkpoint.read_bytes()))
assert pending["_person_map"]["state"] == "pending"
assert asyncio.run(worker.login(str(destination), resume=True)) == 0
assert not checkpoint.exists()
assert calls == {"exchange": 1, "check": 2, "prompt": 1}
assert destination.stat().st_mode & 0o777 == 0o600
assert json.loads(base64.b64decode(destination.read_bytes()))["osids"] == {}
'''
    result = subprocess.run([str(python_path()), "-I", "-c", code, str(ROOT / "app/tools/ghunt_worker.py"), str(destination)],
        text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "resume" in result.stdout
    for secret in ("synthetic-never-print", "synthetic-master-never-print", "synthetic-sensitive-error-must-not-print"):
        assert secret not in result.stdout + result.stderr


def test_rejected_oauth_has_safe_stage_diagnostic_and_no_ready_session(session, tmp_path):
    native_runtime()
    destination = tmp_path / "rejected" / "creds.m"
    code = '''
import asyncio, getpass, importlib.util, sys
from pathlib import Path
from ghunt.helpers import auth
from ghunt.errors import GHuntAndroidMasterAuthError
spec = importlib.util.spec_from_file_location("personmap_worker", sys.argv[1])
worker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worker)
getpass.getpass = lambda message: "oauth2_4/synthetic-rejected-secret"
async def reject(client, oauth):
    raise GHuntAndroidMasterAuthError("sensitive-auth-response-must-not-print")
auth.android_master_auth = reject
assert asyncio.run(worker.login(sys.argv[2])) == 1
assert not Path(sys.argv[2]).exists()
assert not list(Path(sys.argv[2]).parent.glob("*.ghunt-pending"))
'''
    result = subprocess.run([str(python_path()), "-I", "-c", code, str(ROOT / "app/tools/ghunt_worker.py"), str(destination)],
        text=True, capture_output=True, timeout=15)
    assert result.returncode == 0, result.stderr
    assert "intercambio_oauth" in result.stdout
    assert "autenticación nueva" in result.stdout
    assert "synthetic-rejected-secret" not in result.stdout + result.stderr
    assert "sensitive-auth-response-must-not-print" not in result.stdout + result.stderr


@pytest.mark.asyncio
async def test_native_cookie_refresh_does_not_bootstrap_unused_service_osids(session, monkeypatch):
    native_runtime()
    requests = []
    def response(request):
        requests.append(request)
        assert request.url.path not in {"/ServiceLogin", "/accounts/SetOSID"}
        if request.url.path == "/CheckCookie":
            location = "https://www.google.com/robots.txt" if "fresh-sapisid" in request.headers.get("cookie", "") else "https://accounts.google.com/CookieMismatch"
            return httpx.Response(302, headers={"location": location})
        if request.url.host == "android.googleapis.com" and request.url.path == "/auth":
            return httpx.Response(200, text="Auth=synthetic-chrome\nExpiry=4102444800\ngrantedScopes=https://www.google.com/accounts/OAuthLogin")
        if request.url.path == "/OAuthLogin":
            return httpx.Response(200, text="synthetic-uber-auth")
        if request.url.path == "/MergeSession":
            return httpx.Response(200, headers=[("set-cookie", "SAPISID=fresh-sapisid; Secure; Path=/"),
                                               ("set-cookie", "SID=fresh-sid; Secure; Path=/")])
        return authenticated_response(request)
    bridge_http(monkeypatch, response)
    result = await ghunt_runner.run_ghunt({"kind": "email", "value": EMAIL}, [])
    assert result["status"] == "observed", result
    saved = json.loads(base64.b64decode(session.read_bytes()))
    assert saved["cookies"]["SAPISID"] == "fresh-sapisid"
    assert saved["osids"] == {}
    assert any(request.url.path == "/MergeSession" for request in requests)
