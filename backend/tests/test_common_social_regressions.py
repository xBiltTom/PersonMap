import json
import httpx
import pytest
from app.tools.base import TargetContext
from app.tools.dataset_adapter import SiteCheck, build_catalog
from app.tools.email_enumerator import EmailEnumeratorTool
from app.tools.google_account_osint import GoogleAccountOSINTTool
from app.tools.social_profiles import parse_social_profile, core_profile_candidates
from app.tools.social_url_extractor import SocialUrlExtractorTool
from app.tools.social_verifier import SocialVerifierTool
from app.tools.search_dorker import SearchDorkerTool
from app.tools.username_finder import UsernameFinderTool
from app.engine.pivot_rules import extract_and_apply_pivots

@pytest.mark.parametrize('url,platform,identity,kind', [('https://facebook.com/profile.php?id=123&fbclid=abc', 'facebook', '123', 'profile_id'), ('https://facebook.com/people/Audit-User/456', 'facebook', '456', 'profile_id'), ('https://facebook.com/456', 'facebook', '456', 'profile_id'), ('https://youtube.com/channel/UC0123456789012345678901/about', 'youtube', 'UC0123456789012345678901', 'channel_id'), ('https://youtube.com/@caf%C3%A9.user', 'youtube', 'café.user', 'username'), ('https://youtube.com/c/audit.user/about', 'youtube', 'audit.user', 'username'), ('https://snapchat.com/add/abc1def', 'snapchat', 'abc1def', 'username'), ('https://threads.com/@audit.user', 'threads', 'audit.user', 'username'), ('https://bsky.app/profile/audit.bsky.social', 'bluesky', 'audit.bsky.social', 'username')])
def test_resource_identity(url, platform, identity, kind):
    p = parse_social_profile(url)
    assert (p.platform, p.username, p.resource_kind) == (platform, identity, kind)
    assert parse_social_profile(p.url) == p

def test_facebook_ids_do_not_collapse_and_routes_not_users():
    assert parse_social_profile('https://facebook.com/profile.php?id=123').url != parse_social_profile('https://facebook.com/profile.php?id=456').url
    for route in ['profile.php', 'login.php', 'sharer.php', 'profile.php?id=bad']:
        assert parse_social_profile('https://facebook.com/' + route) is None

def test_structured_checks_bind_the_requested_user():
    tool = UsernameFinderTool()
    x = SiteCheck(name='X', url='https://api.x.com/i/users/username_available.json?username={account}')
    assert tool._matches(x, httpx.Response(200, json={'reason': 'taken'}, request=httpx.Request('GET', x.build_url('audituser'))), 'audituser')
    t = SiteCheck(name='TikTok', url='https://www.tiktok.com/oembed?url=https://www.tiktok.com/@{account}')
    for author, expected in [('audituser', True), ('someoneelse', False)]:
        assert tool._matches(t, httpx.Response(200, json={'author_url': f'https://www.tiktok.com/@{author}'}, request=httpx.Request('GET', t.build_url('audituser'))), 'audituser') is expected

@pytest.mark.asyncio
async def test_derived_urls_and_stable_ids_are_not_alias_evidence():
    urls = core_profile_candidates('audituser')
    context = TargetContext(extra={'candidate_urls': urls, 'derived_profile_candidates': dict.fromkeys(urls, {})})
    assert await SocialUrlExtractorTool().execute(context) == []
    context = TargetContext(extra={'candidate_urls': ['https://facebook.com/profile.php?id=123']})
    results = await SocialUrlExtractorTool().execute(context)
    assert results[0].metadata_info['usernames'] == []
    extract_and_apply_pivots(results, context)
    assert context.all_usernames() == []

@pytest.mark.asyncio
async def test_email_registration_with_unknown_control_never_becomes_profile(monkeypatch):
    tool = EmailEnumeratorTool()

    async def probe(client, email):
        return {'registered': True, 'platform': 'Twitter/X', 'url': 'https://x.com'} if email == 'audit@example.com' else None

    async def nothing(*args):
        return None
    for name in dir(tool):
        if name.startswith('_check_'):
            monkeypatch.setattr(tool, name, probe if name == '_check_twitter' else nothing)
    findings = await tool.execute(TargetContext(email='audit@example.com'))
    assert findings[0].entity_type == 'email_registration'
    assert findings[0].metadata_info['negative_control'] == 'untested'
    assert 'url' not in findings[0].metadata_info
    context = TargetContext()
    extract_and_apply_pivots(findings, context)
    assert context.extra['candidate_urls'] == []

@pytest.mark.asyncio
@pytest.mark.parametrize('platform,url,title,description,state', [('snapchat', 'https://snapchat.com/@teamsnapchat', 'Team Snapchat (@teamsnapchat) | Historias', 'Historias públicas de Team Snapchat', 'verified'), ('instagram', 'https://instagram.com/audituser', 'Instagram', '', 'inconclusive'), ('instagram', 'https://instagram.com/audituser', 'Log in • Instagram', '', 'blocked'), ('twitter', 'https://x.com/NASA', 'NASA (@NASA) / X', 'NASA official account', 'verified')])
async def test_locale_independent_and_inconclusive_profiles(platform, url, title, description, state):
    html = f'<title>{title}</title><meta property="og:title" content="{title}"><meta property="og:description" content="{description}"><meta property="og:image" content="https://example.com/image.png">'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html, headers={'content-type': 'text/html'}))) as client:
        context = TargetContext()
        result = await SocialVerifierTool().verify_url(client, url, context)
    assert context.extra['social_verifier_results'][url]['status'] == state
    assert bool(result) == (state == 'verified')

def test_catalog_corrections_and_spoofed_domains():
    snap = next((s for s in build_catalog() if 'snapchat.com' in s.url))
    assert snap.accepts_username('abc1def')
    assert not snap.accepts_username('abcd1def!')
    assert not snap.accepts_username('abcd_')
    assert SearchDorkerTool()._detect_platform('https://evil.test/?url=https://x.com/NASA') == 'web_search'
    assert SearchDorkerTool()._detect_platform('https://x.com.evil.test/NASA') == 'web_search'

@pytest.mark.asyncio
async def test_youtube_search_uses_channel_results_not_navigation():
    channel = 'UC0123456789012345678901'
    data = {'contents': {'twoColumnSearchResultsRenderer': {'primaryContents': {'sectionListRenderer': {'contents': [{'itemSectionRenderer': {'contents': [{'channelRenderer': {'channelId': channel, 'title': {'simpleText': 'Audit channel'}}}]}}]}}}}}
    html = '<script>var ytInitialData = ' + json.dumps(data) + ';</script><script>{"url":"/@unrelated"}</script>'
    tool = GoogleAccountOSINTTool()
    assert tool.can_run(TargetContext(full_name='Audit channel'))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html, headers={'content-type': 'text/html'}))) as client:
        results = await tool._search_youtube_channel(client, 'audituser', TargetContext())
    assert [f.value for f in results] == [f'https://youtube.com/channel/{channel}']
    assert results[0].metadata_info['verification_status'] == 'candidate'

@pytest.mark.asyncio
async def test_tiktok_embed_binds_author_and_missing_embed_is_inconclusive():
    for author, expected in [('audituser', 'verified'), ('other', 'inconclusive'), (None, 'inconclusive')]:

        def response(request):
            if request.url.path == '/oembed':
                return httpx.Response(200, json={'author_url': f'https://tiktok.com/@{author}', 'author_name': 'Audit'}) if author else httpx.Response(400, json={'code': 400})
            return httpx.Response(200, text='<title>TikTok - Make Your Day</title>', headers={'content-type': 'text/html'})
        context = TargetContext()
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            result = await SocialVerifierTool().verify_url(client, 'https://tiktok.com/@audituser', context)
        assert context.extra['social_verifier_results']['https://tiktok.com/@audituser']['status'] == expected
        assert bool(result) == (expected == 'verified')

@pytest.mark.asyncio
async def test_snapchat_generic_og_with_localized_visible_title():
    html = '<title>Team Snapchat (@teamsnapchat) | Historias</title><meta property="og:title" content="Team Snapchat en Snapchat"><meta property="og:description" content="Historias públicas"><meta property="og:image" content="https://example.com/preview.png">'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html, headers={'content-type': 'text/html'}))) as client:
        assert await SocialVerifierTool().verify_url(client, 'https://snapchat.com/@teamsnapchat', TargetContext()) is not None

@pytest.mark.asyncio
async def test_youtube_channel_id_redirect_requires_observed_same_id():
    channel = 'UC0123456789012345678901'
    for observed, expected in [(channel, True), ('UCotherchannel01234567890', False)]:

        def response(request):
            if request.url.path.startswith('/channel/'):
                return httpx.Response(302, headers={'location': 'https://youtube.com/@audituser'})
            return httpx.Response(200, text=f'<title>Audit User</title><meta itemprop="channelId" content="{observed}">', headers={'content-type': 'text/html'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
            result = await SocialVerifierTool().verify_url(client, f'https://youtube.com/channel/{channel}', TargetContext())
        assert bool(result) == expected

@pytest.mark.asyncio
async def test_catalog_failure_still_schedules_public_profile_verification(monkeypatch):
    from app.engine.rule_engine import RuleEngine
    from app.models.target import Target
    from app.tools.registry import tool_registry
    from app.tools import http_client
    finder = UsernameFinderTool()
    monkeypatch.setattr(finder, '_load_sites', lambda: [SiteCheck(name='X', url='https://api.x.com/i/users/username_available.json?username={account}')])
    monkeypatch.setattr(tool_registry, 'get_all', lambda: [finder, SocialVerifierTool()])

    def response(request):
        if request.url.host == 'api.x.com':
            return httpx.Response(200, json={'reason': 'invalid_username'})
        if request.url.host == 'x.com':
            return httpx.Response(200, text='<title>NASA (@NASA) / X</title><meta name="description" content="NASA official account">', headers={'content-type': 'text/html'})
        return httpx.Response(404)
    monkeypatch.setattr(http_client, 'build_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(response)))
    result = await RuleEngine().collect_findings('core-profile-fallback', Target(username='NASA'))
    assert [f.value for f in result.findings] == ['https://x.com/NASA']
    assert result.rounds >= 2

@pytest.mark.asyncio
async def test_ddg_does_not_attribute_unrelated_search_result(monkeypatch):
    from app.tools.search_dorker import Dork
    from app.core.config import settings
    monkeypatch.setattr(settings, 'tavily_require_literal_match', True)
    html = '<div class="result"><a class="result__a" href="https://instagram.com/anotheruser">Another Person</a><a class="result__snippet">Public profile</a></div>'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=html))) as client:
        seen = set()
        assert await SearchDorkerTool()._search_duckduckgo(client, Dork('"audit@example.com"', 'email'), seen) == []
    assert not seen
