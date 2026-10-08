"""False-positive, per-query fallback and optional-provider regressions."""
import asyncio
import json
import httpx
import pytest
import respx
from pydantic import SecretStr
from app.core.config import settings
from app.tools.base import TargetContext
from app.tools.search_dorker import Dork, SearchDorkerTool, SearchBackend, _matches_literally
TAVILY = 'https://api.tavily.com/search'
TINY = 'https://api.search.tinyfish.ai'
DDG = 'https://html.duckduckgo.com/html/'
HTML = '<div class="result"><a class="result__a" href="https://github.com/alpha">alpha</a></div>'

@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    for key, value in dict(tinyfish_api_key=None, tavily_api_key='fixture-key', search_read_pages=False, tavily_max_queries=5, search_max_queries_per_round=5).items():
        monkeypatch.setattr(settings, key, value)

@pytest.mark.parametrize('term,title,url,expected', [('ana', 'banana', 'https://example.test/', False), ('person@example.test', 'otherperson@example.test', 'https://example.test/', False), ('alias', 'Página', 'https://example.test/?q=alias', False), ('José', 'Josh', 'https://example.test/', False), ('José', 'Jose.', 'https://example.test/', True), ('Juan Perez', 'Juan Perez.', 'https://example.test/', True), ('alias', '@alias', 'https://example.test/', True), ('ana', 'ana.otro', 'https://example.test/', False), ('ana', 'x@ana', 'https://example.test/', False), ('ana', 'ana.', 'https://example.test/', True), ('王明', '王明', 'https://example.test/', True), ('王明', '王明伟', 'https://example.test/', False), ('Juan Perez', 'Perfil', 'https://example.test/juan-perez', True), ('Juan Perez', 'Perfil', 'https://example.test/otro-juan-perez', False)])
def test_whole_identifiers(term, title, url, expected):
    assert _matches_literally(Dork(f'"{term}"', 'fixture'), title, '', url) is expected

def test_query_classes_and_discovered_seeds():
    tool = SearchDorkerTool()
    ctx = TargetContext(email='seed@example.test', phone='+51987654321', dni='00123456', username='seedalias', full_name='Ana Prueba', discovered_emails=['pivot@example.test'], discovered_usernames=['pivotalias'])
    queries = [d.query for d in tool._generate_dorks(ctx)]
    assert 'seedalias' in queries[3] and 'Ana Prueba' in queries[4]
    assert any(('pivot@example.test' in q for q in queries))
    assert any(('pivotalias' in q for q in queries))
    assert tool.can_run(TargetContext(discovered_emails=['pivot@example.test']))
    assert tool.can_run(TargetContext(discovered_usernames=['pivotalias']))

@pytest.mark.asyncio
@respx.mock
async def test_partial_primary_success_still_falls_back():

    def primary(request):
        q = json.loads(request.content)['query']
        results = [{'title': 'alpha', 'url': 'https://example.test/alpha', 'content': 'alpha'}] if q == '"alpha"' else []
        return httpx.Response(200, json={'results': results})
    respx.post(TAVILY).mock(side_effect=primary)
    backup = respx.post(DDG).respond(200, text=HTML.replace('alpha', 'beta'))
    findings = await SearchDorkerTool().execute(TargetContext(username='alpha', discovered_usernames=['beta']))
    assert backup.called
    assert {f.value for f in findings} == {'https://example.test/alpha', 'https://github.com/beta'}

@pytest.mark.asyncio
@respx.mock
async def test_duplicates_budget_and_later_pivots(monkeypatch):
    monkeypatch.setattr(settings, 'tavily_max_queries', 3)
    monkeypatch.setattr(settings, 'search_max_queries_per_round', 1)
    primary = respx.post(TAVILY).respond(200, json={'results': [{'title': 'alpha beta', 'url': 'https://github.com/alpha', 'content': 'alpha beta'}]})
    backup = respx.post(DDG).respond(500)
    ctx = TargetContext(username='alpha')
    tool = SearchDorkerTool()
    assert len(await tool.execute(ctx)) == 1
    ctx.discovered_usernames.append('beta')
    assert await tool.execute(ctx) == []
    assert ctx.extra['search_queries_executed'][1][0] == '"beta"'
    await tool.execute(ctx)
    await tool.execute(ctx)
    assert primary.call_count == 3 and (not backup.called)

@pytest.mark.asyncio
@respx.mock
async def test_keyless_tinyfish_never_called(monkeypatch):
    monkeypatch.setattr(settings, 'tavily_api_key', None)
    tiny = respx.get(TINY).respond(500)
    backup = respx.post(DDG).respond(200, text=HTML)
    assert await SearchDorkerTool().execute(TargetContext(username='alpha'))
    assert backup.called and (not tiny.called)

@pytest.mark.asyncio
@respx.mock
async def test_tinyfish_success_and_request_shape(monkeypatch):
    monkeypatch.setattr(settings, 'tinyfish_api_key', SecretStr('fixture-tiny'))
    respx.post(TAVILY).respond(500)
    tiny = respx.get(TINY).respond(200, json={'results': [{'title': 'alpha', 'snippet': 'Public alpha profile', 'url': 'https://github.com/alpha'}]})
    backup = respx.post(DDG).respond(500)
    findings = await SearchDorkerTool().execute(TargetContext(username='alpha'))
    assert findings[0].metadata_info['engine'] == 'tinyfish'
    assert tiny.calls[0].request.headers['X-API-Key'] == 'fixture-tiny'
    assert tiny.calls[-1].request.url.params['include_domains'].startswith('linkedin.com,')
    assert not backup.called

@pytest.mark.parametrize('status', [401, 402, 429, 500])
@pytest.mark.asyncio
@respx.mock
async def test_tinyfish_errors_preserve_backup(status, monkeypatch):
    monkeypatch.setattr(settings, 'tinyfish_api_key', SecretStr('fixture-tiny'))
    respx.post(TAVILY).respond(432)
    tiny = respx.get(TINY).respond(status)
    respx.post(DDG).respond(200, text=HTML)
    ctx = TargetContext(username='alpha')
    findings = await SearchDorkerTool().execute(ctx)
    assert findings[0].metadata_info['engine'] == 'duckduckgo'
    if status != 500:
        assert tiny.call_count == 1
    assert 'fixture-tiny' not in str(ctx.extra['search_diagnostics'])

@pytest.mark.parametrize('payload', [[], {'results': {}}, {'results': [None, 5, {'url': 'https://github.com/alpha', 'title': 'alpha', 'score': 'broken'}]}])
@pytest.mark.asyncio
@respx.mock
async def test_bad_schemas_and_scores(payload):
    respx.post(TAVILY).respond(200, json=payload)
    respx.post(DDG).respond(500)
    findings = await SearchDorkerTool().execute(TargetContext(username='alpha'))
    assert len(findings) == (1 if isinstance(payload, dict) and isinstance(payload.get('results'), list) else 0)

@pytest.mark.parametrize('engine', ['tavily', 'tinyfish', 'duckduckgo'])
@pytest.mark.asyncio
@respx.mock
async def test_local_domain_restrictions(engine, monkeypatch):
    monkeypatch.setattr(settings, 'tinyfish_api_key', SecretStr('fixture-tiny'))
    item = {'title': 'alpha', 'content': 'alpha', 'snippet': 'alpha', 'url': 'https://github.com.evil.test/alpha'}
    respx.post(TAVILY).respond(200, json={'results': [item]})
    respx.get(TINY).respond(200, json={'results': [item]})
    respx.post(DDG).respond(200, text=HTML.replace('github.com/', 'github.com.evil.test/'))
    tool = SearchDorkerTool()
    backend = next((b for b in tool._backends() if b.name == engine))
    async with backend.build_client() as client:
        assert await backend.search(client, Dork('"alpha"', 'fixture', include_domains=['github.com']), set()) == []

@pytest.mark.parametrize('url', ['http-not-a-url', 'https://user:pass@example.test/', 'https://localhost/a', 'https://127.0.0.1/a'])
def test_invalid_evidence_urls(url):
    assert SearchDorkerTool()._build_finding(url=url, title='alpha', snippet='', dork=Dork('"alpha"', 'fixture'), engine='tavily', relevance=float('nan')) is None

@pytest.mark.asyncio
async def test_deadline(monkeypatch):

    async def slow(client, dork, seen):
        await asyncio.sleep(2)
        return []
    monkeypatch.setattr(settings, 'search_timeout_seconds', 1)
    tool = SearchDorkerTool()
    monkeypatch.setattr(tool, '_backends', lambda: [SearchBackend('fixture', lambda: True, lambda: httpx.AsyncClient(), slow)])
    ctx = TargetContext(username='alpha')
    assert await tool.execute(ctx) == []
    assert ctx.extra['search_diagnostics'][-1]['status'] == 'deadline_exceeded'

@pytest.mark.parametrize('failure', ['timeout', 'redirect'])
@pytest.mark.asyncio
@respx.mock
async def test_tinyfish_transport_failures_keep_backup(failure, monkeypatch):
    monkeypatch.setattr(settings, 'tinyfish_api_key', SecretStr('fixture-tiny'))
    monkeypatch.setattr(settings, 'tavily_api_key', None)
    route = respx.get(TINY)
    if failure == 'timeout':
        route.mock(side_effect=httpx.ReadTimeout('fixture timeout'))
    else:
        route.respond(302, headers={'location': 'https://other.test/stolen'})
    other = respx.get('https://other.test/stolen').respond(200, json={'results': []})
    respx.post(DDG).respond(200, text=HTML)
    findings = await SearchDorkerTool().execute(TargetContext(username='alpha'))
    assert findings[0].metadata_info['engine'] == 'duckduckgo'
    assert not other.called

@pytest.mark.asyncio
async def test_paid_clients_have_no_automatic_retries_or_redirects():
    for backend in SearchDorkerTool()._backends()[:2]:
        async with backend.build_client() as client:
            assert client.follow_redirects is False
            assert client._transport.max_retries == 0
