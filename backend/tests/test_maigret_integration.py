"""Real upstream worker against controlled responses; no external scans.

These cover the capabilities lost by the previous catalog-only integration,
and the contracts protecting the other tools and persisted investigations.
"""
import asyncio
import json
import gzip
from collections import Counter

import httpx
import pytest

from app.core.config import settings
from app.engine.persistence import dedupe_findings, detect_relationships
from app.engine.pivot_rules import extract_and_apply_pivots
from app.models.entity import Entity
from app.tools import http_client, maigret_runner
from app.tools.base import TargetContext, ToolFinding
from app.tools.dataset_adapter import SiteCheck, build_catalog as legacy_catalog
from app.tools.maigret_catalog import build_scan_catalog, database_info, native_recipes, platform_hosts
from app.tools.maigret_catalog import build_profile_catalog
from app.tools.username_finder import UsernameFinderTool
from app.tools.social_profiles import parse_social_profile


GITHUB_PROFILE = {
    "login": "audituser", "id": 123, "name": "Audit User", "bio": "Public bio",
    "gists_url": "https://api.github.com/users/audituser/gists",
    "received_events_url": "https://api.github.com/users/audituser/received_events",
    "avatar_url": "https://avatars.githubusercontent.com/audituser",
    "html_url": "https://github.com/audituser", "blog": "https://audit.example.org",
    "twitter_username": "audit_other",
}


@pytest.fixture(autouse=True)
def bounded_worker(monkeypatch):
    monkeypatch.setattr(settings, "maigret_worker_timeout", 30)


@pytest.mark.asyncio
async def test_native_probe_extraction_enrichment_and_complementary_coverage(monkeypatch):
    """Maigret gets a profile via its API even when its HTML page is blocked."""
    queried = []
    def reply(request):
        queried.append(str(request.url))
        if request.url.path == "/users/audituser":
            return httpx.Response(200, json=GITHUB_PROFILE)
        if request.url.path == "/users/audituser/social_accounts":
            return httpx.Response(200, json=[{"provider": "twitter", "url": "https://x.com/audit_other"}])
        if request.url.host == "extra.example.org" and request.url.path == "/audituser":
            return httpx.Response(200, text="<title>Audit Profile</title> audituser", headers={"content-type": "text/html"})
        if request.url.host == "github.com":
            return httpx.Response(403)
        return httpx.Response(404)
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    monkeypatch.setattr(settings, "maigret_enrich", True)
    tool = UsernameFinderTool()
    site = native_recipes()["GitHub"]
    extra = SiteCheck(name="Extra", url="https://extra.example.org/{username}", presence=("Audit Profile",))
    monkeypatch.setattr(tool, "_load_sites", lambda: [site, extra])
    context = TargetContext(username="audituser")
    findings = await tool.execute(context)
    assert len(findings) == 2
    github = next(f for f in findings if f.platform == "github")
    assert github.metadata_info["bio"] == "Public bio"
    assert github.metadata_info["avatar_url"] == GITHUB_PROFILE["avatar_url"]
    assert "audit_other" in github.metadata_info["extracted_usernames"]
    assert "https://x.com/audit_other" in github.metadata_info["linked_profiles"]
    assert "https://audit.example.org" in github.metadata_info["linked_profiles"]
    assert github.metadata_info["negative_control"] == "passed"
    assert github.metadata_info["verification_status"] == "candidate"
    assert github.metadata_info["source_tool"] == "username_finder"
    extract_and_apply_pivots(findings, context)
    assert "audit_other" in context.discovered_usernames
    assert "https://x.com/audit_other" in context.extra["candidate_urls"]
    assert "https://audit.example.org" not in context.extra.get("personal_domain_urls", [])
    before = list(queried)
    context.discovered_usernames.clear()
    assert await tool.execute(context) == []
    assert queried == before
    # Same real legacy recipe and responses: detection is preserved, while
    # native extraction/enrichment contributes data the old checker discarded.
    legacy = next(site for site in legacy_catalog() if site.name == "GitHub (User)")
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        previous = await tool._check_site(client, "audituser", legacy, asyncio.Semaphore(1), None,
                                          {"checked": 0, "control_rejected": 0}, 1)
    assert previous is not None and previous.value == github.value
    assert not previous.metadata_info.get("bio")
    assert not previous.metadata_info.get("linked_profiles")


@pytest.mark.asyncio
async def test_native_engine_headers_post_payload_and_negative_control(monkeypatch, tmp_path):
    database = tmp_path / "recipes.json"
    database.write_text(json.dumps({"sites": {
        "API": {"urlMain": "https://api.example.org", "url": "https://api.example.org/u/{username}",
                "urlProbe": "https://api.example.org/check", "engine": "Test",
                "headers": {"X-Recipe": "required"}, "requestMethod": "POST",
                "requestPayload": {"handle": "{username}"}},
        "CatchAll": {"urlMain": "https://catch.example.org", "url": "https://catch.example.org/{username}",
                     "checkType": "status_code"}},
        "engines": {"Test": {"site": {"checkType": "message", "presenseStrs": ['"exists":true'],
                                       "absenceStrs": ['"exists":false']}}}, "tags": []}))
    monkeypatch.setattr(maigret_runner, "database_path", lambda: database)
    requests = []
    def reply(request):
        requests.append(request)
        if request.url.host == "api.example.org":
            if request.method != "POST":
                return httpx.Response(405)
            assert request.method == "POST"
            assert request.headers["X-Recipe"] == "required"
            return httpx.Response(200, json={"exists": json.loads(request.content)["handle"] == "audituser"})
        return httpx.Response(200, text="Generic landing page")
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    monkeypatch.setattr(settings, "maigret_enrich", False)
    sites = [SiteCheck(name=n, native_name=n, url=f"https://{h}/{{username}}")
             for n, h in [("API", "api.example.org"), ("CatchAll", "catch.example.org")]]
    wires = []
    async def collect(result):
        wires.append(result)
    await maigret_runner.run_maigret("audituser", sites, {s.name: "control123" for s in sites}, collect)
    tool, counter = UsernameFinderTool(), {"control_rejected": 0}
    accepted = [tool._native_finding(next(s for s in sites if s.name == r["site"]), "audituser", r, counter) for r in wires]
    assert len([f for f in accepted if f]) == 1
    assert counter["control_rejected"] == 1
    assert sum(r.method == "POST" for r in requests) == 2
    async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
        assert await tool._check_site(client, "audituser", sites[0], asyncio.Semaphore(1), None,
                                      {"checked": 0, "control_rejected": 0}, 1) is None


@pytest.mark.asyncio
async def test_worker_failure_and_cancellation_do_not_complete_coverage(monkeypatch):
    tool = UsernameFinderTool()
    monkeypatch.setattr(tool, "_load_sites", lambda: [native_recipes()["GitHub"]])
    async def fail(*args, **kwargs):
        raise RuntimeError("fixture failure")
    monkeypatch.setattr("app.tools.username_finder.run_maigret", fail)
    context = TargetContext(username="audituser")
    with pytest.raises(RuntimeError, match="fixture failure"):
        await tool.execute(context)
    assert context.extra["username_finder_coverage"]["audituser"] == 0
    async def cancel(*args, **kwargs):
        raise asyncio.CancelledError
    monkeypatch.setattr("app.tools.username_finder.run_maigret", cancel)
    with pytest.raises(asyncio.CancelledError):
        await tool.execute(context)
    assert context.extra["username_finder_coverage"]["audituser"] == 0


def test_catalog_native_priority_filters_and_domain_exclusions(monkeypatch):
    sites = build_scan_catalog(500)
    assert any(s.name == "GitHub" and s.native_name for s in sites)
    assert any(s.source == "whatsmyname" and not s.native_name for s in sites)
    assert sites == build_scan_catalog(1000)[:500]
    hosts = [s.url.split("://", 1)[-1].removeprefix("www.").split("/", 1)[0] for s in sites]
    assert max(Counter(hosts).values()) == 1
    monkeypatch.setattr(settings, "maigret_site_names", ["GitHub"])
    assert [s.name for s in build_scan_catalog()] == ["GitHub"]
    assert "reddit.com" in platform_hosts()
    assert any(site.name == "Reddit" for site in build_profile_catalog())
    info = database_info()
    assert info["maigret_version"] == "0.6.6"
    assert len(info["maigret_catalog_sha256"]) == 64


@pytest.mark.asyncio
async def test_disqus_native_probe_retains_correct_public_profile_url(monkeypatch):
    site = native_recipes()["Disqus"]
    assert site.url == "https://disqus.com/by/{username}/"
    profile = parse_social_profile("https://www.disqus.com/by/audituser/")
    assert profile.url == "https://disqus.com/by/audituser"
    assert profile.username == "audituser"
    assert parse_social_profile("https://disqus.com/audituser") is None
    queried = []
    def reply(request):
        queried.append(request)
        return httpx.Response(404)
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    results = []
    async def collect(result):
        results.append(result)
    await maigret_runner.run_maigret("audituser", [site], {}, collect)
    assert results[0]["url_user"] == "https://disqus.com/by/audituser/"
    assert any(request.url.host == "disqus.com" and request.url.path == "/api/3.0/users/details" for request in queried)


def test_maigret_observations_merge_with_specialists_without_seed_edges():
    enumerated = ToolFinding(entity_type="social_account", value="https://twitter.com/audituser",
                            metadata_info={"source_tool": "username_finder", "username": "audituser"})
    verified = ToolFinding(entity_type="social_account", value="https://x.com/audituser",
        metadata_info={"source_tool": "social_verifier", "verification_status": "verified", "bio": "Observed bio"})
    merged = dedupe_findings([enumerated, verified])
    assert len(merged) == 1 and merged[0].metadata_info["bio"] == "Observed bio"
    assert set(merged[0].metadata_info["source_tools"]) == {"username_finder", "social_verifier"}
    entities = [Entity(entity_type="social_account", value=url, source_tool="username_finder",
                       metadata_info={"username": "audituser"})
                for url in ["https://x.com/audituser", "https://github.com/audituser"]]
    assert detect_relationships(*entities) == []


def test_tag_filters_apply_to_complementary_sites_too(monkeypatch):
    monkeypatch.setattr(settings, "maigret_site_names", [])
    monkeypatch.setattr(settings, "maigret_tags", [])
    monkeypatch.setattr(settings, "maigret_excluded_tags", ["nsfw"])
    assert not any(site.sensitive for site in build_scan_catalog())
    monkeypatch.setattr(settings, "maigret_excluded_tags", [])
    monkeypatch.setattr(settings, "maigret_tags", ["nsfw"])
    sites = build_scan_catalog()
    assert sites and all(site.sensitive for site in sites)
    assert {site.source for site in sites} == {"maigret", "whatsmyname"}


@pytest.mark.asyncio
async def test_browser_redirects_use_public_dns_and_shared_budget(monkeypatch):
    from types import SimpleNamespace
    from curl_cffi import CurlOpt
    from app.tools.public_network import UnsafePublicURL
    calls = []
    class Browser:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            assert CurlOpt.RESOLVE in kwargs["curl_options"]
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def request(self, method, url, **kwargs):
            assert kwargs["verify"] is True and kwargs["allow_redirects"] is False
            calls.append(url)
            return SimpleNamespace(status_code=302, headers=httpx.Headers({"location": "http://127.0.0.1/private"}), content=b"")
    async def dns(host, port, **kwargs):
        ip = "127.0.0.1" if host == "127.0.0.1" else "8.8.8.8"
        return [(2, 1, 6, "", (ip, port))]
    monkeypatch.setattr("curl_cffi.requests.AsyncSession", Browser)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    http_client.reset_concurrency_gates()
    async with httpx.AsyncClient() as client:
        with pytest.raises(UnsafePublicURL):
            await maigret_runner.browser_request(client, {"method": "GET", "url": "https://public.example.org/u",
                "browser": "chrome", "allow_redirects": True})
    assert calls == ["https://public.example.org/u"]
    assert http_client._get_global_semaphore()._value == settings.http_max_concurrency


@pytest.mark.asyncio
async def test_cancelling_real_worker_releases_transport_and_child(monkeypatch):
    processes, waiting, cancelled = [], asyncio.Event(), asyncio.Event()
    original = asyncio.create_subprocess_exec
    async def spawn(*args, **kwargs):
        process = await original(*args, **kwargs)
        processes.append(process)
        return process
    async def response(request):
        waiting.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(response)))
    async def collect(result):
        pass
    task = asyncio.create_task(maigret_runner.run_maigret("audituser", [native_recipes()["GitHub"]], {}, collect))
    await asyncio.wait_for(waiting.wait(), 15)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()
    assert processes and processes[0].returncode is not None


@pytest.mark.asyncio
async def test_catalog_change_invalidates_coverage_without_erasing_other_tools(monkeypatch):
    tool = UsernameFinderTool()
    monkeypatch.setattr(tool, "_load_sites", lambda: [native_recipes()["GitHub"]])
    invoked = []
    async def scan(username, sites, controls, collect, progress, **kwargs):
        invoked.append(username)
    monkeypatch.setattr("app.tools.username_finder.run_maigret", scan)
    context = TargetContext(username="audituser", extra={"github_checked_usernames": ["audituser"]})
    await tool.execute(context)
    assert await tool.execute(context) == []
    monkeypatch.setattr(settings, "maigret_keywords", ["new keyword"])
    await tool.execute(context)
    assert invoked == ["audituser", "audituser"]
    assert context.extra["github_checked_usernames"] == ["audituser"]


@pytest.mark.asyncio
async def test_synchronous_extractor_requests_also_use_parent_transport(monkeypatch, tmp_path):
    """A real socid Gravatar postprocessor performs a synchronous HEAD."""
    digest = "1234567890abcdef1234567890abcdef"
    database = tmp_path / "recipes.json"
    database.write_text(json.dumps({"sites": {"GravatarNative": {
        "urlMain": "https://gravatar.com", "url": "https://gravatar.com/{username}",
        "urlProbe": "https://en.gravatar.com/{username}.json", "checkType": "status_code"}},
        "engines": {}, "tags": []}))
    monkeypatch.setattr(maigret_runner, "database_path", lambda: database)
    monkeypatch.setattr(settings, "maigret_enrich", False)
    methods = []
    def reply(request):
        methods.append(request.method)
        if request.method == "HEAD":
            return httpx.Response(302, headers={"location": "/audituser"})
        body = json.dumps({"entry": [{"id": "1", "preferredUsername": digest,
            "thumbnailUrl": f"https://gravatar.com/avatar/{digest}", "displayName": "Audited"}]}).replace("/", "\\/")
        return httpx.Response(200, text=body, headers={"content-type": "application/json"})
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    wires = []
    async def collect(result):
        wires.append(result)
    site = SiteCheck(name="GravatarNative", native_name="GravatarNative", url="https://gravatar.com/{username}")
    await maigret_runner.run_maigret(digest, [site], {}, collect)
    assert methods == ["GET", "HEAD"]
    assert wires[0]["ids_data"]["gravatar_username"] == "audituser"


@pytest.mark.asyncio
async def test_compressed_http_responses_survive_rpc_and_native_conversion(monkeypatch):
    def reply(request):
        found = request.url.path == "/users/audituser"
        data = GITHUB_PROFILE if found else {"message": "Not Found"}
        return httpx.Response(200 if found else 404, content=gzip.compress(json.dumps(data).encode()),
            headers={"content-type": "application/json", "content-encoding": "gzip"})
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    monkeypatch.setattr(settings, "maigret_enrich", False)
    wires = []
    async def collect(result):
        wires.append(result)
    site = native_recipes()["GitHub"]
    await maigret_runner.run_maigret("audituser", [site], {"GitHub": "control123"}, collect)
    assert "content-encoding" not in wires[0]["response"]["headers"]
    finding = UsernameFinderTool()._native_finding(site, "audituser", wires[0], {"control_rejected": 0})
    assert finding is not None and finding.metadata_info["bio"] == "Public bio"
    assert finding.metadata_info["negative_control"] == "passed"


@pytest.mark.asyncio
async def test_browser_decoded_body_does_not_get_decompressed_twice(monkeypatch):
    from types import SimpleNamespace
    class Browser:
        def __init__(self, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def request(self, *args, **kwargs):
            # curl has decoded the bytes but preserves the server's header.
            return SimpleNamespace(status_code=200, headers=httpx.Headers({"content-encoding": "gzip",
                "content-length": "40", "content-type": "text/html"}), content=b"<title>Actual profile</title>")
    async def dns(host, port, **kwargs):
        return [(2, 1, 6, "", ("8.8.8.8", port))]
    monkeypatch.setattr("curl_cffi.requests.AsyncSession", Browser)
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", dns)
    async with httpx.AsyncClient() as client:
        response = await maigret_runner.browser_request(client, {"method": "GET", "url": "https://public.example.org/u", "browser": "chrome"})
    assert response.text == "<title>Actual profile</title>"
    assert "content-encoding" not in response.headers
    assert response.headers["content-length"] == str(len(response.content))


@pytest.mark.asyncio
async def test_native_and_complementary_requests_share_one_tool_quota(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "http_max_concurrency", 4)
    monkeypatch.setattr(settings, "tool_concurrency_share", 0.5)
    monkeypatch.setattr(settings, "username_scan_concurrency", 60)
    native = [SiteCheck(name=f"Native{i}", native_name=f"Native{i}", url=f"https://n{i}.example.org/{{username}}") for i in range(4)]
    extra = [SiteCheck(name=f"Extra{i}", url=f"https://e{i}.example.org/{{username}}") for i in range(4)]
    database = tmp_path / "recipes.json"
    database.write_text(json.dumps({"sites": {site.name: {"urlMain": site.url.split("/{")[0], "url": site.url,
        "checkType": "status_code"} for site in native}, "engines": {}, "tags": []}))
    monkeypatch.setattr(maigret_runner, "database_path", lambda: database)
    active, peak = 0, 0
    async def reply(request):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(2 if request.url.host.startswith("e") else 0.05)
            return httpx.Response(404)
        finally:
            active -= 1
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    tool = UsernameFinderTool()
    monkeypatch.setattr(tool, "_load_sites", lambda: [*native, *extra])
    assert await tool.execute(TargetContext(username="audituser")) == []
    assert peak <= settings.tool_concurrency_budget(settings.username_scan_concurrency)
