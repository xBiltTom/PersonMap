import json

import httpx
import pytest

from app.core.runtime import durable_runtime
from app.engine.pivot_rules import extract_and_apply_pivots
from app.tools import http_client
from app.tools.base import TargetContext
from app.tools.email_checker import EmailCheckerTool
from app.tools.google_account_osint import GoogleAccountOSINTTool
from app.tools.google_profiles import observe_scholar, scholar_url
from app.tools.social_verifier import SocialVerifierTool

SCHOLAR = "https://scholar.google.com/citations?user=AbcdEF12GhIJ"
ORCID = "0000-0002-1825-0097"
CHANNEL = "UC0123456789012345678901"


def bridge(monkeypatch, responder):
    monkeypatch.setattr(http_client, "build_client", lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(responder), follow_redirects=False))


def scholar_page(url=SCHOLAR):
    return f'''<title>Observed Author - Google Scholar</title><link rel="canonical" href="{url}">
    <div id="gsc_prf_i"><div id="gsc_prf_in">Observed Author</div>
    <div class="gsc_prf_il">Observed University</div>
    <div class="gsc_prf_il">Verified email at example.edu</div>
    <a href="https://orcid.org/{ORCID}">ORCID</a>
    <a href="https://orcid.org.evil.example/{ORCID}">Not ORCID</a></div>
    <table id="gsc_rsb_st"><tr><td>Citations</td><td>1,234</td><td>78</td></tr>
    <tr><td>h-index</td><td>12</td><td>5</td></tr></table>
    <div>Unrelated paper: Citado por 99999</div>'''


@pytest.mark.asyncio
async def test_scholar_reads_author_metrics_and_links_without_claiming_target_ownership(monkeypatch):
    bridge(monkeypatch, lambda request: httpx.Response(200, text=scholar_page()))
    context = TargetContext(extra={"candidate_urls": [SCHOLAR]})
    tool = GoogleAccountOSINTTool()
    findings = await tool.execute(context)
    assert len(findings) == 1
    record = findings[0]
    assert record.display_name == "Observed Author"
    assert record.metadata_info["citations"] == 1234
    assert record.metadata_info["h_index"] == 12
    assert record.metadata_info["institutions"] == ["Observed University"]
    assert record.metadata_info["ownership_status"] == "unverified"
    assert record.metadata_info["linked_profiles"] == ["https://orcid.org/" + ORCID]
    assert record.metadata_info["verified_email_domain"] == "example.edu"
    extract_and_apply_pivots(findings, context)
    assert {"value": ORCID, "id_type": "orcid"} in context.extra["maigret_identifiers"]
    assert context.all_usernames() == []
    assert not tool.can_run(context)
    assert durable_runtime(context.extra)["google_public_scholar_profiles"][SCHOLAR] == "observed"


@pytest.mark.parametrize("url", [
    SCHOLAR.replace("scholar.google.com", "scholar.google.com.evil.test"),
    SCHOLAR + "&user=OtherAuthor", SCHOLAR + "&view_op=view_citation",
    SCHOLAR.replace("https", "http"), "https://scholar.google.com@evil.test/citations?user=AbcdEF12GhIJ",
])
def test_scholar_profile_urls_do_not_accept_other_resources_or_hosts(url):
    assert scholar_url(url) is None


def test_scholar_wrong_author_and_generic_pages_never_become_observed_profiles():
    assert observe_scholar(scholar_page(SCHOLAR.replace("AbcdEF12GhIJ", "OtherAuthorID")), SCHOLAR)["status"] == "identity_mismatch"
    assert observe_scholar("<title>Google Scholar</title> Citado por 1000", SCHOLAR)["status"] == "unexpected_response"


@pytest.mark.asyncio
async def test_scholar_author_search_visits_card_profiles_and_keeps_blocked_candidates(monkeypatch):
    seen = []
    def respond(request):
        seen.append(request)
        if request.url.host == "www.youtube.com":
            return httpx.Response(403)
        if request.url.params.get("view_op") == "search_authors":
            return httpx.Response(200, text='<div class="gs_ai_chpr"><h3 class="gs_ai_name">'
                '<a href="/citations?user=AbcdEF12GhIJ&hl=en">Actual Card Author</a></h3></div> Citado por 999')
        return httpx.Response(429)
    bridge(monkeypatch, respond)
    context = TargetContext(full_name="Queried Person", university="Queried University")
    findings = await GoogleAccountOSINTTool().execute(context)
    assert len(findings) == 1
    assert findings[0].display_name == "Actual Card Author"
    assert findings[0].metadata_info["profile_status"] == "blocked"
    assert findings[0].metadata_info["ownership_status"] == "unverified"
    assert "citations" not in findings[0].metadata_info and "institutions" not in findings[0].metadata_info
    assert len([r for r in seen if r.url.params.get("user")]) == 1
    assert any(r.url.params.get("view_op") == "search_authors" for r in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize("observed,expected", [(CHANNEL, True), ("UC9999999999999999999999", False)])
async def test_youtube_structured_metadata_binds_channel_id_through_redirect(observed, expected):
    data = {"metadata": {"channelMetadataRenderer": {"externalId": observed, "title": "Observed Channel",
            "description": "Observed channel biography", "avatar": {"thumbnails": [{"url": "https://example.org/photo.png"}]}}}}
    def response(request):
        if request.url.path.startswith("/channel/"):
            return httpx.Response(302, headers={"location": "https://youtube.com/@observedhandle"})
        return httpx.Response(200, text="<title>YouTube</title><script>var ytInitialData = " + json.dumps(data) + ";</script>", headers={"content-type": "text/html"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        finding = await SocialVerifierTool().verify_url(client, "https://youtube.com/channel/" + CHANNEL, TargetContext())
    assert bool(finding) == expected
    if finding:
        assert finding.metadata_info["channel_id"] == CHANNEL
        assert finding.metadata_info["bio"] == "Observed channel biography"


@pytest.mark.asyncio
@pytest.mark.parametrize("public_email,expected", [("audit+tag@example.org", True), (None, False), ("another@example.org", False)])
async def test_github_email_attribution_requires_exact_observed_public_email(monkeypatch, public_email, expected):
    seen = []
    def respond(request):
        seen.append(request)
        if request.url.path == "/search/users":
            assert request.url.params["q"] == '"audit+tag@example.org" in:email'
            return httpx.Response(200, json={"items": [{"login": "observed-user", "html_url": "https://evil.test/user"}]})
        return httpx.Response(200, json={"login": "observed-user", "email": public_email})
    bridge(monkeypatch, respond)
    context = TargetContext(email="audit+tag@example.org")
    tool = EmailCheckerTool()
    findings = await tool.execute(context)
    profiles = [finding for finding in findings if finding.entity_type == "social_account"]
    assert bool(profiles) == expected
    if profiles:
        assert profiles[0].value == "https://github.com/observed-user"
        assert profiles[0].metadata_info["technique"] == "github_public_profile_email"
        assert profiles[0].metadata_info["ownership_status"] == "unverified"
    assert len(seen) == 2
    assert not tool.can_run(context)
    assert await tool.execute(context) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("contents", [None, [], {"twoColumnSearchResultsRenderer": None},
    {"twoColumnSearchResultsRenderer": {"primaryContents": {"sectionListRenderer": {"contents": [None, {"itemSectionRenderer": {"contents": [None, {"channelRenderer": []}]}}]}}}}])
async def test_malformed_youtube_keeps_already_observed_scholar_profiles(monkeypatch, contents):
    def respond(request):
        if request.url.host == "www.youtube.com":
            return httpx.Response(200, text='<script>var ytInitialData = ' + json.dumps({"contents": contents}) + ';</script>')
        return httpx.Response(200, text=scholar_page())
    bridge(monkeypatch, respond)
    context = TargetContext(username="fixture", extra={"candidate_urls": [SCHOLAR]})
    findings = await GoogleAccountOSINTTool().execute(context)
    assert len(findings) == 1 and findings[0].metadata_info["profile_status"] == "observed"
    assert not GoogleAccountOSINTTool().can_run(context)


@pytest.mark.parametrize("prefix", ["google_public_", "email_checker_"])
def test_upgrading_coverage_preserves_other_tools_concurrent_work(prefix):
    from app.services.workspace import merge_runtime
    baseline = {prefix + "version": 1, prefix + "checked": ["old"], "ghunt_checked": ["first"]}
    latest = {**baseline, "ghunt_checked": ["first", "concurrent"]}
    incoming = {prefix + "version": 2, prefix + "checked": ["new"], "ghunt_checked": ["first"]}
    merged = merge_runtime(latest, baseline, incoming)
    assert merged[prefix + "checked"] == ["new"]
    assert merged["ghunt_checked"] == ["first", "concurrent"]
