"""Regressions for social candidates, enrichment, scheduling and public URLs."""

import asyncio
import socket
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.config import settings
from app.engine.pivot_rules import extract_and_apply_pivots
from app.engine.rule_engine import RuleEngine
from app.tools import http_client
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.dataset_adapter import SiteCheck, build_catalog
from app.tools.public_network import PublicNetworkBackend, UnsafePublicURL
from app.tools.social_profiles import parse_social_profile
from app.tools.social_url_extractor import SocialUrlExtractorTool
from app.tools.social_verifier import SocialVerifierTool
from app.tools.username_finder import UsernameFinderTool


PROFILE_HTML = '''<title>Audit User (@audituser)</title>
<meta property="og:type" content="profile">
<meta property="og:description" content="Contact audituser@example.org; also @another.user.">
<meta property="og:image" content="https://images.example/preview.jpg">'''


@pytest.mark.parametrize("url", [
    "https://notgithub.com/audituser", "https://github.com.evil.org/audituser",
    "https://example.org/github.com/audituser",
    "https://example.org/?next=https://github.com/audituser",
    "https://github.com/topics", "https://github.com/topics/security",
    "https://x.com/intent/tweet", "https://instagram.com/accounts/login",
    "https://github.com/audituser/repository", "https://github.com/audituser!suffix",
    "ftp://github.com/audituser", "https://user:password@github.com/audituser",
    "https://github.com:8080/audituser", "https://github.com/audituser%2Frepository",
])
def test_non_profile_urls_are_rejected(url):
    assert parse_social_profile(url) is None


@pytest.mark.asyncio
async def test_query_aliases_deduplicate_without_claiming_existence():
    urls = ["https://www.github.com/audituser/?tab=repositories#readme", "https://github.com/audituser"]
    findings = await SocialUrlExtractorTool().execute(TargetContext(extra={"candidate_urls": urls}))
    assert len(findings) == 1
    assert findings[0].value == "https://github.com/audituser"
    assert findings[0].metadata_info["verification_status"] == "candidate"
    assert findings[0].evidence_urls == [urls[0]]
    assert parse_social_profile("https://twitter.com/audituser").url == "https://x.com/audituser"


def test_verifier_waits_for_urls_and_reruns_when_they_arrive():
    tool = SocialVerifierTool()
    before = TargetContext(username="audituser")
    after = TargetContext(username="audituser", extra={"candidate_urls": ["https://github.com/audituser"]})
    assert not tool.can_run(before)
    assert tool.can_run(TargetContext(extra=after.extra))
    engine = RuleEngine()
    assert engine._get_tool_run_key(tool, before) != engine._get_tool_run_key(tool, after)
    assert UsernameFinderTool().can_run(TargetContext(discovered_usernames=["audituser"]))


@pytest.mark.asyncio
@pytest.mark.parametrize("html,status", [
    ("<title>Log in</title>", "not_profile"),
    ("<title>Page not found</title>", "not_profile"),
    ("<title>Just a moment</title>", "blocked"),
    ("<title>Welcome to GitHub</title>", "not_profile"),
])
async def test_200_is_not_evidence_of_a_profile(html, status):
    context = TargetContext()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html, headers={"content-type": "text/html"}))) as client:
        assert await SocialVerifierTool().verify_url(client, "https://github.com/audituser", context) is None
    assert context.extra["social_verifier_results"]["https://github.com/audituser"]["status"] == status


@pytest.mark.asyncio
@pytest.mark.parametrize("status,expected", [(404, "not_found"), (410, "not_found"), (403, "blocked"), (429, "blocked"), (503, "error")])
async def test_response_outcomes_distinguish_absence_from_failure(status, expected):
    context = TargetContext()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status))) as client:
        assert await SocialVerifierTool().verify_url(client, "https://github.com/audituser", context) is None
    assert context.extra["social_verifier_results"]["https://github.com/audituser"]["status"] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("canonical,accepted", [
    ("https://unrelated.example/other", False),
    ("https://github.com/otheruser", False),
    ("javascript:alert(1)", False),
    ("/audituser", True),
    ("https://www.github.com/audituser/", True),
])
async def test_valid_profile_keeps_safe_identity_and_correct_bio_pivots(canonical, accepted):
    html = PROFILE_HTML + f'<meta property="og:url" content="{canonical}">'
    context = TargetContext(username="audituser")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=html, headers={"content-type": "text/html"}))) as client:
        finding = await SocialVerifierTool().verify_url(client, "https://github.com/audituser", context)
    assert finding.value == "https://github.com/audituser"
    assert finding.metadata_info["canonical_accepted"] is accepted
    assert finding.metadata_info["extracted_emails"] == ["audituser@example.org"]
    assert finding.metadata_info["extracted_usernames"] == ["another.user"]
    assert "avatar_url" not in finding.metadata_info
    extract_and_apply_pivots([finding], context)
    assert context.discovered_usernames == ["another.user"]


@pytest.mark.asyncio
async def test_redirect_to_another_account_is_not_verified():
    def respond(request):
        if request.url.path == "/audituser":
            return httpx.Response(302, headers={"location": "/anotheruser"})
        return httpx.Response(200, text=PROFILE_HTML, headers={"content-type": "text/html"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert await SocialVerifierTool().verify_url(client, "https://github.com/audituser", TargetContext()) is None


@pytest.mark.asyncio
async def test_redirect_to_private_ip_is_blocked_before_request():
    requests = []
    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    context = TargetContext()
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert await SocialVerifierTool().verify_url(client, "https://github.com/audituser", context) is None
    assert requests == ["https://github.com/audituser"]
    assert context.extra["social_verifier_results"][requests[0]]["status"] == "unsafe_url"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500, 503, 999])
async def test_blocked_control_is_inconclusive(status):
    site = SiteCheck(name="Example", url="https://example.org/{username}", presence=("PROFILE",))
    def respond(request):
        return httpx.Response(200, text="PROFILE audituser") if request.url.path == "/audituser" else httpx.Response(status)
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        finding = await UsernameFinderTool()._check_site(client, "audituser", site, asyncio.Semaphore(1), None, {"checked": 0, "control_rejected": 0}, 1)
    assert finding.metadata_info["negative_control"] == "untested"


def test_response_url_checks_status_and_aliases_cannot_change_url_structure():
    site = SiteCheck(name="Example", url="https://example.org/{username}", check_type="response_url", presence=("PROFILE",))
    resp = httpx.Response(500, text="PROFILE audituser", request=httpx.Request("GET", site.build_url("audituser")))
    assert not UsernameFinderTool()._matches(site, resp, "audituser")
    assert site.build_url("user?x=y#z") == "https://example.org/user%3Fx%3Dy%23z"


def test_x_is_available_in_default_short_catalog():
    assert any(site.name == "X" for site in build_catalog(limit=500))


@pytest.mark.asyncio
async def test_verification_is_concurrent_bounded_and_does_not_repeat_completed_urls(monkeypatch):
    monkeypatch.setattr(settings, "social_verify_concurrency", 2)
    monkeypatch.setattr(settings, "social_verify_max_urls", 4)
    inside = peak = requests = 0
    async def respond(request):
        nonlocal inside, peak, requests
        requests += 1
        inside += 1
        peak = max(peak, inside)
        await asyncio.sleep(0.01)
        inside -= 1
        return httpx.Response(200, text=PROFILE_HTML, headers={"content-type": "text/html"})
    def client_factory(**kwargs):
        assert kwargs["public_only"] is True
        assert kwargs["follow_redirects"] is False
        return httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(http_client, "build_client", client_factory)
    tool = SocialVerifierTool()
    context = TargetContext(extra={"candidate_urls": [f"https://github.com/user{i}" for i in range(6)]})
    assert len(await tool.execute(context)) == 4
    assert await tool.execute(context) == []
    assert requests == 4 and peak == 2
    assert context.extra["social_verifier_stats"] == {"verified": 4}


@pytest.mark.asyncio
async def test_errors_and_total_timeouts_are_recorded_and_retries_are_bounded(monkeypatch):
    monkeypatch.setattr(settings, "social_verify_url_timeout", 0.01)
    requests = 0
    async def respond(request):
        nonlocal requests
        requests += 1
        await asyncio.sleep(1)
        return httpx.Response(200, text=PROFILE_HTML, headers={"content-type": "text/html"})
    monkeypatch.setattr(http_client, "build_client", lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    context = TargetContext(extra={"candidate_urls": ["https://github.com/audituser"]})
    tool = SocialVerifierTool()
    for _ in range(3):
        assert await tool.execute(context) == []
    assert requests == 2
    assert context.extra["social_verifier_results"]["https://github.com/audituser"] == {"status": "error", "error": "total_timeout"}


@pytest.mark.asyncio
@pytest.mark.parametrize("addresses", [["127.0.0.1"], ["10.0.0.1"], ["169.254.169.254"], ["::1"], ["::ffff:127.0.0.1"], ["8.8.8.8", "192.168.1.1"]])
async def test_dns_private_or_mixed_addresses_never_reach_socket(monkeypatch, addresses):
    async def resolve(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, 443)) for ip in addresses]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    socket_backend = AsyncMock()
    with pytest.raises(UnsafePublicURL):
        await PublicNetworkBackend(socket_backend).connect_tcp("untrusted.example", 443)
    socket_backend.connect_tcp.assert_not_called()


@pytest.mark.asyncio
async def test_socket_uses_validated_ip_without_second_dns_lookup(monkeypatch):
    resolve = AsyncMock(return_value=[(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("8.8.8.8", 443))])
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    socket_backend = AsyncMock()
    backend = PublicNetworkBackend(socket_backend)
    await backend.connect_tcp("public.example", 443, timeout=1)
    resolve.assert_awaited_once()
    socket_backend.connect_tcp.assert_awaited_once_with("8.8.8.8", 443, timeout=1, local_address=None, socket_options=None)


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect", [False, True])
async def test_real_http_stack_preserves_host_tls_and_blocks_private_dns_redirect(monkeypatch, redirect):
    """Exercise httpx -> httpcore -> guarded sockets without external traffic."""
    class Stream:
        def __init__(self):
            self.written = b""
            self.tls_host = None
            body = PROFILE_HTML.encode()
            self.response = (
                b"HTTP/1.1 302 Found\r\nLocation: https://secret.example/private\r\nContent-Length: 0\r\n\r\n"
                if redirect else b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body
            )

        async def read(self, max_bytes, timeout=None):
            data, self.response = self.response[:max_bytes], self.response[max_bytes:]
            return data

        async def write(self, buffer, timeout=None):
            self.written += buffer

        async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
            self.tls_host = server_hostname
            return self

        async def aclose(self):
            pass

        def get_extra_info(self, name):
            return None

    stream = Stream()
    backend = AsyncMock()
    backend.connect_tcp.return_value = stream
    async def resolve(host, port, **kwargs):
        ip = "10.0.0.1" if host == "secret.example" else "8.8.8.8"
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", (ip, port))]
    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    http_client.reset_concurrency_gates()
    context = TargetContext()
    async with http_client.build_client(public_only=True, follow_redirects=False, max_retries=0) as client:
        client._transport.jitter = 0
        client._transport._pool._network_backend = PublicNetworkBackend(backend)
        finding = await SocialVerifierTool().verify_url(client, "https://github.com/audituser", context)
    assert backend.connect_tcp.await_count == 1
    assert backend.connect_tcp.call_args.args[0] == "8.8.8.8"
    assert stream.tls_host == "github.com"
    assert b"Host: github.com\r\n" in stream.written
    assert (finding is None) is redirect
    assert context.extra["social_verifier_results"]["https://github.com/audituser"]["status"] == ("unsafe_url" if redirect else "verified")
    http_client.reset_concurrency_gates()


@pytest.mark.asyncio
async def test_rule_engine_verifies_a_profile_discovered_in_a_later_round(monkeypatch):
    from app.models.target import Target
    from app.tools.registry import tool_registry

    class SourceTool(BaseTool):
        name = "source"
        description = "Synthetic source for the round integration test"
        category = ToolCategory.SEARCH
        required_inputs = ["full_name"]
        async def execute(self, context):
            return [ToolFinding(entity_type="search_mention", value="https://github.com/audituser")]

    monkeypatch.setattr(tool_registry, "get_all", lambda: [SourceTool(), SocialVerifierTool()])
    monkeypatch.setattr(http_client, "build_client", lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=PROFILE_HTML, headers={"content-type": "text/html"}))))
    result = await RuleEngine().collect_findings("social-test", Target(full_name="Audit User"))
    assert any(f.metadata_info.get("verification_status") == "verified" for f in result.findings)


def test_agent_schema_and_context_accept_candidate_url_arrays():
    from app.agent.tool_dispatch import build_call_context, build_tool_schemas
    from app.models.target import Target
    schema = next(s["function"]["parameters"] for s in build_tool_schemas() if s["function"]["name"] == "social_verifier")
    assert schema["properties"]["candidate_urls"]["type"] == "array"
    url = "https://github.com/audituser"
    context = build_call_context({"candidate_urls": [url], "url": url}, Target())
    assert context.extra["candidate_urls"] == [url]
    assert SocialVerifierTool().can_run(context)


@pytest.mark.asyncio
async def test_catalog_cannot_turn_reserved_routes_into_profiles():
    calls = []
    def respond(request):
        calls.append(str(request.url))
        return httpx.Response(200, text=PROFILE_HTML, headers={"content-type": "text/html"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert await SocialVerifierTool().verify_url(client, "https://github.com/topics", TargetContext()) is None
    assert calls == []


@pytest.mark.asyncio
async def test_verified_profile_is_not_refetched_for_cosmetic_aliases(monkeypatch):
    requests = []
    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, text=PROFILE_HTML, headers={"content-type": "text/html"})
    monkeypatch.setattr(http_client, "build_client", lambda **_: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    context = TargetContext(extra={"candidate_urls": ["https://github.com/audituser", "https://www.github.com/audituser/?tab=repositories"]})
    tool = SocialVerifierTool()
    assert len(await tool.execute(context)) == 1
    context.extra["candidate_urls"].append("https://github.com/audituser?utm_source=share")
    assert await tool.execute(context) == []
    assert requests == ["https://github.com/audituser"]


@pytest.mark.parametrize("reverse", [False, True])
def test_verified_enrichment_survives_deduplication_with_stronger_enumeration(reverse):
    from app.engine.persistence import dedupe_findings
    enumerated = ToolFinding(entity_type="social_account", value="https://github.com/audituser", confidence=0.9,
        metadata_info={"source_tool": "username_finder", "username": "audituser", "verification_status": "candidate", "extracted_emails": ["first@example.org"]},
        evidence_urls=["https://api.github.com/users/audituser"])
    verified = ToolFinding(entity_type="social_account", value="https://github.com/audituser/", confidence=0.5,
        metadata_info={"source_tool": "social_verifier", "bio": "Public bio", "verification_status": "verified", "extracted_emails": ["second@example.org"], "og_image": "https://images.example/preview.jpg"},
        evidence_urls=["https://github.com/audituser/"])
    findings = [enumerated, verified]
    result = dedupe_findings(list(reversed(findings)) if reverse else findings)
    assert len(result) == 1 and result[0].confidence == 0.9
    assert result[0].metadata_info["bio"] == "Public bio"
    assert result[0].metadata_info["verification_status"] == "verified"
    assert set(result[0].metadata_info["extracted_emails"]) == {"first@example.org", "second@example.org"}
    assert set(result[0].metadata_info["source_tools"]) == {"username_finder", "social_verifier"}
    assert set(result[0].evidence_urls) == {"https://api.github.com/users/audituser", "https://github.com/audituser/"}


@pytest.mark.asyncio
async def test_catalog_profiles_preserve_query_identifiers_and_account_placeholders(monkeypatch):
    from app.tools import social_verifier
    site = SiteCheck(name="Forum", url="https://forum.example/member.php?username={account}")
    monkeypatch.setattr(social_verifier, "build_catalog", lambda: [site])
    social_verifier._catalog_routes.cache_clear()
    try:
        url = "https://forum.example/member.php?username=audituser&utm_source=search"
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, text=PROFILE_HTML, headers={"content-type": "text/html"}))) as client:
            finding = await SocialVerifierTool().verify_url(client, url, TargetContext())
        assert finding.value == "https://forum.example/member.php?username=audituser"
        assert finding.metadata_info["username"] == "audituser"
        assert finding.metadata_info["requested_url"] == url
    finally:
        social_verifier._catalog_routes.cache_clear()
