"""Extended Maigret capabilities exercised through the real isolated worker."""
import asyncio
import base64
import json
from types import SimpleNamespace
from urllib.parse import urlsplit

import httpx
import pytest
from pydantic import SecretStr, ValidationError

from app.core.config import settings
from app.core.runtime import durable_runtime
from app.engine.pivot_rules import extract_and_apply_pivots
from app.engine.rule_engine import RuleEngine
from app.engine.persistence import dedupe_findings
from app.models.target import Target
from app.schemas.identifiers import PublicIdentifier
from app.schemas.workspace import MaigretOptions, ToolInputs
from app.services.workspace import call_fingerprint
from app.agent.tool_dispatch import build_call_context, build_tool_schemas
from app.tools import http_client, maigret_runner
from app.tools.base import TargetContext, ToolFinding
from app.tools.dataset_adapter import SiteCheck
from app.tools.maigret_catalog import build_identifier_catalog, build_scan_catalog, execution_config, native_recipes
from app.tools.maigret_enricher import MaigretEnricherTool, identifier_control
from app.tools.maigret_ids import identifiers_from_url
from app.tools.public_network import UnsafePublicURL
from app.tools.username_finder import UsernameFinderTool
from app.schemas.investigation import InvestigationCreate
from app.schemas.target import TargetCreate


@pytest.fixture(autouse=True)
def worker_settings(monkeypatch):
    monkeypatch.setattr(settings, "maigret_worker_timeout", 45)
    monkeypatch.setattr(settings, "maigret_enrich", False)


def test_typed_urls_are_exact_and_do_not_create_aliases():
    assert identifiers_from_url("https://vk.com/id12345") == [{"value": "12345", "id_type": "vk_id"}]
    assert identifiers_from_url("https://steamcommunity.com/profiles/76561198012345678/") == [
        {"value": "76561198012345678", "id_type": "steam_id"}]
    assert identifiers_from_url("https://orcid.org/0000-0002-1825-0097") == [
        {"value": "0000-0002-1825-0097", "id_type": "orcid"}]
    for url in ("https://github.com/login", "https://github.com/audituser/repositories",
                "https://github.com.evil.test/audituser", "https://steamcommunity.com/profiles/123/not-a-profile"):
        assert identifiers_from_url(url) == []
    context = TargetContext(username="seed")
    findings = [ToolFinding(entity_type="academic", value="https://openalex.org/A123", metadata_info={
        "source_tool": "academic_finder", "orcid": "https://orcid.org/0000-0002-1825-0097",
        "discovered_identifiers": {"12345": "vk_id"}})]
    assert extract_and_apply_pivots(findings, context)
    assert context.extra["maigret_identifiers"] == [{"value": "12345", "id_type": "vk_id"},
        {"value": "0000-0002-1825-0097", "id_type": "orcid"}]
    assert context.all_usernames() == ["seed"]
    assert context.extra["maigret_identifier_sources"]["vk_id:12345"][0]["url"] == "https://openalex.org/A123"
    assert "maigret_identifiers" in durable_runtime(context.extra)


@pytest.mark.parametrize("item", [{"value": "http://localhost/x", "id_type": "vk_id"},
    {"value": "mail@example.org", "id_type": "username"}, {"value": "abc", "id_type": "gaia_id"},
    {"value": "0000-0002-1825-0098", "id_type": "orcid"}, {"value": "123", "id_type": "unknown"}])
def test_identifiers_reject_wrong_types_and_routes(item):
    with pytest.raises(ValidationError):
        ToolInputs(identifiers=[item])


def test_orcid_controls_have_valid_checksum():
    site = native_recipes("orcid")["ORCID"]
    item = {"value": "0000-0002-1825-0097", "id_type": "orcid"}
    controlled = identifier_control(site, item)
    assert controlled != item["value"]
    PublicIdentifier(value=controlled, id_type="orcid")


def test_catalogue_all_and_explicit_variant_selection(monkeypatch):
    ordinary = build_scan_catalog()
    exhaustive = build_scan_catalog(include_variants=True)
    assert exhaustive[:len(ordinary)] == ordinary
    assert len(exhaustive) > len(ordinary)
    assert {site.id_type for site in build_identifier_catalog("gaia_id")} == {"gaia_id"}
    selected = next(site for site in exhaustive[len(ordinary):] if not site.sensitive)
    monkeypatch.setattr(settings, "maigret_site_names", [selected.name])
    assert [site.name for site in build_scan_catalog()] == [selected.name]
    assert selected.name in {site.name for site in build_scan_catalog(apply_filters=False)} or selected in native_recipes().values()


def test_schema_options_and_identifier_fingerprints_are_exposed():
    ctx = TargetContext(extra={"maigret_identifiers": [{"value": "12345", "id_type": "vk_id"}]})
    other = TargetContext(extra={"maigret_identifiers": [{"value": "12345", "id_type": "qq_id"}]})
    tool = MaigretEnricherTool()
    assert call_fingerprint(tool.name, ctx) != call_fingerprint(tool.name, other)
    assert RuleEngine()._get_tool_run_key(tool, ctx) != RuleEngine()._get_tool_run_key(tool, other)
    target = Target(username="seed", extra_data={})
    call = build_call_context({"scan_mode": "all", "maigret_options": {"names": ["GitHub"], "enrich": False},
                              "identifiers": [{"value": "12345", "id_type": "vk_id"}]}, target)
    assert call.extra["username_scan_mode"] == "all"
    assert call.extra["maigret_options"]["enrich"] is False
    assert call.extra["maigret_identifiers"] == ctx.extra["maigret_identifiers"]
    schemas = {item["function"]["name"]: item["function"]["parameters"] for item in build_tool_schemas()}
    assert "all" in schemas["username_finder"]["properties"]["scan_mode"]["enum"]
    assert schemas["maigret_enricher"]["properties"]["identifiers"]["type"] == "array"
    with pytest.raises(ValidationError):
        MaigretOptions(permutation_parts=["a", "b", "c", "d"])
    with pytest.raises(ValidationError):
        MaigretOptions(proxy="http://127.0.0.1")


def test_id_only_target_and_plan_are_real_inputs():
    payload = InvestigationCreate(target=TargetCreate(identifiers=[{"value": "0000-0002-1825-0097", "id_type": "orcid"}]),
                                  strategy="rule_based", maigret_plan={"scan_mode": "all", "options": {"enrich": False}})
    assert payload.target.full_name is None and payload.maigret_plan.scan_mode == "all"
    target = Target(extra_data={"identifiers": [item.model_dump() for item in payload.target.identifiers],
                                "maigret_plan": payload.maigret_plan.model_dump(exclude_none=True)})
    ctx = build_call_context({}, target)
    assert MaigretEnricherTool().can_run(ctx)
    assert ctx.extra["maigret_options"]["enrich"] is False
    assert ctx.extra["username_scan_mode"] == "all"


def test_typed_duplicates_and_unicode_aliases_keep_their_semantics():
    from app.tools.maigret_ids import identifier_values
    ctx = TargetContext()
    finding = ToolFinding(entity_type="social_account", value="https://public.example.org/user", metadata_info={
        "extracted_identifiers": [{"value": "12345", "id_type": "vk_id"}, {"value": "12345", "id_type": "ok_id"}],
        "extracted_usernames": ["niño", "ユーザー"]})
    extract_and_apply_pivots([finding], ctx)
    assert len(ctx.extra["maigret_identifiers"]) == 2
    assert ctx.all_usernames() == ["niño", "ユーザー"]
    assert identifier_values([{"value": 12345, "id_type": "vk_id"}]) == [{"value": "12345", "id_type": "vk_id"}]
    a = ToolFinding(entity_type="social_account", value="https://www.yelp.com/user_details?userid=AbCdEf")
    b = ToolFinding(entity_type="social_account", value="https://www.yelp.com/user_details?userid=abcdef")
    assert len(dedupe_findings([a, b])) == 2


def test_verifier_recognizes_ids_and_variants_without_exposing_them_as_usernames():
    from app.tools.social_verifier import _candidate_profile, _catalog_routes
    _catalog_routes.cache_clear()
    assert _candidate_profile("https://orcid.org/0000-0002-1825-0097").resource_kind == "orcid"
    assert _candidate_profile("https://vk.com/id12345").resource_kind == "vk_id"
    assert _candidate_profile("https://www.yelp.com/user_details?userid=AbCdEf").resource_kind == "yelp_userid"


@pytest.mark.asyncio
async def test_all_extends_configured_prefix_without_repeating(monkeypatch):
    sites = [SiteCheck(name=f"Extra{i}", url=f"https://e{i}.example.org/{{username}}") for i in range(3)]
    monkeypatch.setattr("app.tools.username_finder.build_catalog", lambda **kwargs: sites)
    monkeypatch.setattr(settings, "username_scan_max_sites", 1)
    checked = []
    async def check(client, user, site, *args): checked.append(site.name)
    tool = UsernameFinderTool()
    monkeypatch.setattr(tool, "_check_site", check)
    context = TargetContext(username="audituser")
    assert await tool.execute(context) == []
    assert checked == ["Extra0"]
    context.extra["username_scan_mode"] = "all"
    assert await tool.execute(context) == []
    assert checked == ["Extra0", "Extra1", "Extra2"]
    assert context.extra["username_finder_coverage"]["audituser"] == 3


@pytest.mark.asyncio
async def test_opaque_id_redirect_to_different_case_is_not_verified(monkeypatch):
    from app.tools.social_verifier import SocialVerifierTool
    first = "https://www.yelp.com/user_details?userid=AbCdEf"
    last = "https://www.yelp.com/user_details?userid=abcdef"
    def reply(request):
        if str(request.url) == first:
            return httpx.Response(302, headers={"location": last})
        return httpx.Response(200, text='<title>Public profile</title><meta property="profile:username" content="abcdef"><meta property="og:description" content="Public biography">')
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply), follow_redirects=True))
    context = TargetContext(extra={"candidate_urls": [first]})
    assert await SocialVerifierTool().execute(context) == []
    assert context.extra["social_verifier_results"][first]["status"] == "not_profile"


@pytest.mark.asyncio
async def test_identifier_types_select_recipes_and_keep_separate_coverage(monkeypatch, tmp_path):
    sites = [SiteCheck(name=kind, native_name=kind, id_type=kind, url=f"https://{kind.replace('_', '-')}.example.org/{{username}}")
             for kind in ("vk_id", "qq_id")]
    path = tmp_path / "database.json"
    path.write_text(json.dumps({"sites": {site.name: {"urlMain": site.url.split("/{")[0], "url": site.url,
        "type": site.id_type, "checkType": "status_code"} for site in sites}, "engines": {}, "tags": []}))
    monkeypatch.setattr(maigret_runner, "database_path", lambda: path)
    monkeypatch.setattr("app.tools.maigret_enricher.build_identifier_catalog", lambda kind, **kwargs: [site for site in sites if site.id_type == kind])
    requests = []
    def reply(request):
        requests.append(request)
        return httpx.Response(200 if request.url.path == "/12345" else 404, text="Profile")
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    context = TargetContext(extra={"maigret_identifiers": [{"value": "12345", "id_type": site.id_type} for site in sites]})
    tool = MaigretEnricherTool()
    findings = await tool.execute(context)
    assert len(findings) == 2
    assert {f.metadata_info["queried_identifier"]["id_type"] for f in findings} == {"vk_id", "qq_id"}
    assert all("username" not in f.metadata_info and f.metadata_info["negative_control"] == "passed" for f in findings)
    assert set(context.extra["maigret_enricher_scanned"]) == {"vk_id:12345", "qq_id:12345"}
    before = len(requests)
    assert await tool.execute(context) == [] and len(requests) == before


@pytest.mark.asyncio
async def test_url_extraction_uses_native_extractor_and_pivots(monkeypatch):
    url = "https://api.github.com/users/audituser"
    def reply(request):
        return httpx.Response(200, json={"login": "audituser", "id": 123, "name": "Public Name", "bio": "Public bio",
            "avatar_url": "https://avatars.githubusercontent.com/audituser",
            "html_url": "https://github.com/audituser", "blog": "https://orcid.org/0000-0002-1825-0097",
            "gists_url": "https://api.github.com/users/audituser/gists",
            "received_events_url": "https://api.github.com/users/audituser/received_events"})
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    monkeypatch.setattr(settings, "maigret_max_identifiers", 0)
    context = TargetContext(extra={"candidate_urls": [url]})
    findings = await MaigretEnricherTool().execute(context)
    assert len(findings) == 1
    assert findings[0].entity_type == "search_mention"
    assert findings[0].metadata_info["bio"] == "Public bio"
    assert findings[0].metadata_info["maigret_data"]["_extractor"] == "GitHub API"
    assert findings[0].metadata_info["ownership_status"] == "unverified"
    extract_and_apply_pivots(findings, context)
    assert "audituser" in context.all_usernames()
    assert {"value": "0000-0002-1825-0097", "id_type": "orcid"} in context.extra["maigret_identifiers"]


@pytest.mark.asyncio
async def test_generated_or_missing_url_never_becomes_a_page_finding(monkeypatch):
    url = "https://github.com/missinguser"
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(404))))
    context = TargetContext(extra={"candidate_urls": [url]})
    assert await MaigretEnricherTool().execute(context) == []
    assert context.all_usernames() == ["missinguser"]
    assert context.extra["maigret_url_identifiers"][url] == [{"value": "missinguser", "id_type": "username"}]


@pytest.mark.asyncio
async def test_native_permutations_are_bounded_and_remain_candidates():
    results = []
    async def collect(result):
        results.append(result)
    await maigret_runner.run_maigret("", [], {}, collect, operation="permute", parts=["audit", "user"], limit=3)
    assert results[0]["usernames"] == ["audituser", "_audituser", "audituser_"]


@pytest.mark.asyncio
async def test_proxy_pins_public_destination_and_blocks_private_redirect(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "maigret_proxy", SecretStr("http://proxy.example.org:8080"))
    class Browser:
        def __init__(self, **kwargs):
            self.options = kwargs
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def request(self, method, url, **kwargs):
            calls.append((self.options, kwargs))
            return SimpleNamespace(status_code=302, headers=httpx.Headers({"location": "http://127.0.0.1/private"}), content=b"")
    async def dns(host, port, **kwargs):
        return [(2, 1, 6, "", ("127.0.0.1" if host == "127.0.0.1" else "8.8.8.8", port))]
    monkeypatch.setattr("curl_cffi.requests.AsyncSession", Browser)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    async with httpx.AsyncClient() as client:
        with pytest.raises(UnsafePublicURL):
            await maigret_runner.perform_request(client, {"method": "GET", "url": "https://public.example.org/a"})
    from curl_cffi import CurlOpt
    assert calls[0][0]["curl_options"][CurlOpt.CONNECT_TO] == ["public.example.org:443:8.8.8.8:443"]
    assert len(calls) == 1


def test_hidden_services_require_config_and_catalogue(monkeypatch):
    monkeypatch.setattr(settings, "maigret_tor_proxy", None)
    with pytest.raises(UnsafePublicURL):
        maigret_runner.hidden_proxy("http://unknown.onion/u")
    monkeypatch.setattr(settings, "maigret_tor_proxy", SecretStr("socks5://127.0.0.1:9050"))
    site = SiteCheck(name="Hidden", url="http://trusted.onion/{username}", protocol="tor")
    monkeypatch.setattr(maigret_runner, "native_recipes", lambda **kwargs: {"Hidden": site})
    assert maigret_runner.hidden_proxy("http://trusted.onion/audituser") == "socks5h://127.0.0.1:9050"
    with pytest.raises(UnsafePublicURL):
        maigret_runner.hidden_proxy("http://unknown.onion/u")
    assert "127.0.0.1" not in json.dumps(execution_config())


@pytest.mark.asyncio
async def test_dns_checks_use_parent_resolution_and_domain_semantics(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "maigret_check_domains", True)
    path = tmp_path / "dns.json"
    path.write_text(json.dumps({"sites": {"DNS": {"urlMain": "https://example.org", "url": "{username}.example.org",
        "protocol": "dns", "checkType": "status_code"}}, "engines": {}, "tags": []}))
    monkeypatch.setattr(maigret_runner, "database_path", lambda: path)
    async def dns(host, port, **kwargs):
        if host != "audituser.example.org":
            import socket
            raise socket.gaierror(-2, "not found")
        return [(2, 1, 6, "", ("8.8.8.8", port))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    tool = UsernameFinderTool()
    site = SiteCheck(name="DNS", native_name="DNS", url="https://{username}.example.org", protocol="dns")
    monkeypatch.setattr(tool, "_load_sites", lambda: [site])
    findings = await tool.execute(TargetContext(username="audituser"))
    assert len(findings) == 1
    assert findings[0].entity_type == "domain"
    assert findings[0].value == "https://audituser.example.org"
    assert findings[0].metadata_info["negative_control"] == "passed"


@pytest.mark.asyncio
async def test_solver_uses_original_status_and_keeps_response_for_native_adjudication(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "maigret_solver_url", "http://127.0.0.1:8191/v1")
    path = tmp_path / "solver.json"
    path.write_text(json.dumps({"sites": {"Protected": {"urlMain": "https://public.example.org", "url": "https://public.example.org/{username}",
        "protection": ["cf_js_challenge"], "checkType": "status_code"}}, "engines": {}, "tags": []}))
    monkeypatch.setattr(maigret_runner, "database_path", lambda: path)
    async def dns(host, port, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", port))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    original_client = httpx.AsyncClient
    def reply(request):
        assert str(request.url) == settings.maigret_solver_url
        data = json.loads(request.content)
        return httpx.Response(200, json={"status": "ok", "solution": {"url": data["url"],
            "status": 200 if data["url"].endswith("/audituser") else 404,
            "response": "<title>Actual profile</title>", "headers": {"content-type": "text/html"}}})
    monkeypatch.setattr(maigret_runner.httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(reply)))
    site = SiteCheck(name="Protected", native_name="Protected", url="https://public.example.org/{username}")
    wires = []
    async def collect(result): wires.append(result)
    await maigret_runner.run_maigret("audituser", [site], {"Protected": "control123"}, collect)
    assert wires[0]["status"] == "Claimed"
    assert wires[0]["response"]["status"] == 200
    assert wires[0]["control"]["response"]["status"] == 404
    finding = UsernameFinderTool()._native_finding(site, "audituser", wires[0], {"control_rejected": 0})
    assert finding is not None and finding.metadata_info["negative_control"] == "passed"


@pytest.mark.asyncio
async def test_cookie_file_is_domain_scoped_in_native_transport(monkeypatch, tmp_path):
    jar = tmp_path / "cookies.txt"
    jar.write_text("# Netscape HTTP Cookie File\nsite.example.org\tFALSE\t/\tTRUE\t2147483647\tauth\tfixture-secret\n")
    monkeypatch.setattr(settings, "maigret_cookie_file", str(jar))
    path = tmp_path / "cookies.json"
    path.write_text(json.dumps({"sites": {name: {"urlMain": f"https://{host}", "url": f"https://{host}/{{username}}", "checkType": "status_code"}
        for name, host in (("Cookie", "site.example.org"), ("Other", "other.example.org"))}, "engines": {}, "tags": []}))
    monkeypatch.setattr(maigret_runner, "database_path", lambda: path)
    requested = []
    def reply(request):
        requested.append(request)
        return httpx.Response(200 if request.url.path == "/audituser" else 404)
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    sites = [SiteCheck(name=name, native_name=name, url=f"https://{host}/{{username}}")
        for name, host in (("Cookie", "site.example.org"), ("Other", "other.example.org"))]
    async def collect(result): pass
    await maigret_runner.run_maigret("audituser", sites, {}, collect)
    assert {request.url.host for request in requested} == {"site.example.org", "other.example.org"}
    assert all(request.headers.get("cookie") == "auth=fixture-secret" for request in requested if request.url.host == "site.example.org")
    assert all("cookie" not in request.headers for request in requested if request.url.host == "other.example.org")
    assert "fixture-secret" not in json.dumps(execution_config())


@pytest.mark.asyncio
async def test_native_catalogue_self_check_never_changes_snapshot(monkeypatch, tmp_path):
    path = tmp_path / "self-check.json"
    path.write_text(json.dumps({"sites": {"Test": {"urlMain": "https://public.example.org", "url": "https://public.example.org/{username}",
        "checkType": "status_code", "usernameClaimed": "audituser", "usernameUnclaimed": "unknown123"}}, "engines": {}, "tags": []}))
    before = path.read_bytes()
    monkeypatch.setattr(maigret_runner, "database_path", lambda: path)
    def reply(request): return httpx.Response(200 if request.url.path == "/audituser" else 404)
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    results = []
    async def collected(result): results.append(result)
    site = SiteCheck(name="Test", native_name="Test", url="https://public.example.org/{username}")
    await maigret_runner.run_maigret("", [site], {}, collected, operation="self_check")
    assert results[0]["total_issues"] == 0
    assert path.read_bytes() == before


@pytest.mark.asyncio
@pytest.mark.parametrize("fmt", ["json", "ndjson", "csv", "txt", "markdown", "html", "pdf", "xmind", "graph", "neo4j"])
async def test_all_native_report_formats_work_without_network(monkeypatch, fmt):
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(500)
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    record = {"site": "GitHub", "value": "audituser", "id_type": "username", "url": "https://github.com/audituser",
              "data": {"fullname": "Public Name", "bio": "<script>alert(1)</script>", "image": "file:///etc/passwd"},
              "ids": {}, "links": [], "http_status": 200, "verification_status": "candidate",
              "negative_control": "passed", "sources": ["username_finder"]}
    results = []
    async def collected(result): results.append(result)
    await maigret_runner.run_maigret("", [], {}, collected, operation="report", records=[record], report_format=fmt)
    exported = results[0]
    content = base64.b64decode(exported["body"])
    assert exported["records"] == 1 and content
    assert calls == []
    if fmt == "pdf":
        from pypdf import PdfReader
        assert "Public Name" in " ".join(page.extract_text() for page in PdfReader(__import__("io").BytesIO(content)).pages)
    elif fmt == "xmind":
        assert content.startswith(b"PK")
    elif fmt in {"html", "graph"}:
        assert "Content-Security-Policy" in content.decode()
        assert "<script>alert(1)</script>" not in content.decode()
