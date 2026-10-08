import asyncio

import httpx
import pytest
from bs4 import BeautifulSoup

from app.tools import http_client
from app.tools.base import TargetContext
from app.tools.dataset_adapter import SiteCheck, build_catalog
from app.tools.social_profiles import parse_social_profile, core_profile_candidates
from app.tools.social_verifier import SocialVerifierTool
from app.tools.telegram_profiles import observe_telegram_page
from app.tools.username_finder import UsernameFinderTool


GENERIC = '''<title>Telegram: Contact @audituser</title>
<meta property="og:title" content="Telegram: Contact @audituser">
<meta property="og:image" content="https://telegram.org/img/t_logo_2x.png">
<meta property="og:description" content="Contact @audituser right away">
<meta name="robots" content="noindex, nofollow">
<div class="tgme_page_description">If you have Telegram, you can contact
<a href="tg://resolve?domain=audituser">@audituser</a> right away.</div>'''


def peer_html(extra="@audituser", action="Contact", alias="audituser", title="Audit User"):
    return f'''<title>Telegram: {action} @{alias}</title>
    <meta name="robots" content="noindex, nofollow">
    <div class="tgme_page_title"><span>{title}</span></div>
    <div class="tgme_page_extra">{extra}</div>
    <div class="tgme_page_description">A public biography.</div>
    <div class="tgme_page_action"><a href="tg://resolve?domain={alias}">Open Telegram</a></div>'''


@pytest.mark.parametrize("url", [
    "https://t.me/audituser", "https://telegram.me/audituser", "https://telegram.dog/audituser",
    "https://www.telegram.me/audituser", "https://audituser.t.me",
    "https://t.me/s/audituser", "https://t.me/audituser/123", "https://t.me/s/audituser/123",
    "https://t.me/audituser/123/456?single", "https://audituser.t.me/123",
])
def test_public_links_share_peer_identity(url):
    profile = parse_social_profile(url)
    assert profile.platform == "telegram"
    assert profile.username == "audituser"
    assert profile.url == "https://t.me/audituser"


@pytest.mark.parametrize("path", [
    "boost?c=123", "proxy?server=example.com", "addstickers/stickers", "joinchat/hash",
    "+123456789", "+invitehash", "c/123/456", "iv?url=https://example.com",
    "share/url?url=https://example.com", "contact/token", "giftcode/code", "invoice/code",
    "12345", "_audituser", "audit-user", "audituser/not-a-message", "addemoji",
])
def test_service_routes_and_invalid_aliases_are_not_profiles(path):
    assert parse_social_profile("https://t.me/" + path) is None


def test_host_and_username_rules_match_catalog():
    site = next(s for s in build_catalog() if s.name == "Telegram")
    for alias in ["12345", "boost", "a" * 33, "a_user!"]:
        assert not site.accepts_username(alias)
    assert site.accepts_username("audituser")
    assert parse_social_profile("https://boost.t.me") is None
    assert parse_social_profile("https://t.me.evil.test/audituser") is None
    assert parse_social_profile("https://evil.t.me.evil.test/audituser") is None
    assert "https://t.me/audituser" in core_profile_candidates("audituser")
    assert parse_social_profile("https://mobile.t.me").url == "https://t.me/mobile"


@pytest.mark.parametrize("extra,action,kind", [
    ("@audituser", "Contact", "user"), ("@audituser", "Launch", "bot"),
    ("12 345 subscribers", "View", "channel"), ("100 members, 20 online", "View", "group"),
    ("100 suscriptores", "View", "channel"), ("100 miembros", "View", "group"),
    ("100 monthly users", "Contact", "bot"), ("", "View", "unknown"),
])
def test_peer_types_use_page_signals(extra, action, kind):
    observed = observe_telegram_page(BeautifulSoup(peer_html(extra, action), "html.parser"), "audituser")
    assert observed.status == "verified"
    assert observed.peer_type == kind


def test_generic_contact_and_mismatched_resolve_link_are_inconclusive():
    for html in [GENERIC, peer_html(alias="otheruser"), peer_html(title="@audituser")]:
        assert observe_telegram_page(BeautifulSoup(html, "html.parser"), "audituser").status == "inconclusive"


@pytest.mark.asyncio
async def test_both_detectors_reject_generic_contact_and_accept_named_user():
    site = SiteCheck(name="Telegram", url="https://t.me/{account}", presence=("tgme_page_title",))
    for html, expected in [(GENERIC, False), (peer_html(), True)]:
        context = TargetContext()
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html, headers={"content-type": "text/html"}))) as client:
            response = await client.get("https://t.me/audituser")
            assert UsernameFinderTool()._matches(site, response, "audituser") is expected
            result = await SocialVerifierTool().verify_url(client, "https://t.me/audituser", context)
        assert bool(result) is expected
        assert context.extra["social_verifier_results"]["https://t.me/audituser"]["status"] == ("verified" if expected else "inconclusive")
        if result:
            assert result.metadata_info["telegram_peer_type"] == "user"


@pytest.mark.asyncio
async def test_preview_links_fetch_peer_page_and_do_not_repeat_aliases(monkeypatch):
    requests = []
    def respond(request):
        requests.append(str(request.url))
        return httpx.Response(200, text=peer_html(extra="100 subscribers", action="View"), headers={"content-type": "text/html"})
    monkeypatch.setattr(http_client, "build_client", lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    context = TargetContext(extra={"candidate_urls": ["https://telegram.me/audituser/123", "https://t.me/s/audituser", "https://audituser.t.me"]})
    results = await SocialVerifierTool().execute(context)
    assert requests == ["https://t.me/audituser"]
    assert len(results) == 1
    assert results[0].metadata_info["telegram_peer_type"] == "channel"
    assert results[0].evidence_urls == ["https://telegram.me/audituser/123", "https://t.me/audituser"]


@pytest.mark.asyncio
async def test_generic_negative_control_is_unknown(monkeypatch):
    tool = UsernameFinderTool()
    site = SiteCheck(name="Telegram", url="https://t.me/{account}")
    monkeypatch.setattr(tool, "_invented_alias", lambda *args: "audituser")
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=GENERIC))) as client:
        assert await tool._control_matches(client, site, "realuser", asyncio.Semaphore(1)) is None


@pytest.mark.asyncio
async def test_reserved_routes_are_rejected_before_request():
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, text=peer_html())
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        assert await SocialVerifierTool().verify_url(client, "https://t.me/boost", TargetContext()) is None
    assert not calls
