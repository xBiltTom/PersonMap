"""Bounded public-page evidence and optional TinyFetch regression tests."""
import httpx
import pytest
import respx
from pydantic import SecretStr
from app.core.config import settings
from app.tools.base import TargetContext
from app.tools.search_dorker import Dork, SearchDorkerTool
from app.tools.search_reader import read_public_page, read_tinyfish_page, enrich_search_findings, TINYFETCH_URL, MAX_BYTES
URL = 'https://example.test/article'
TEXT = 'Ana Prueba es mencionada en esta publicación pública sobre proyectos universitarios. ' * 4

@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(settings, 'tinyfish_api_key', None)
    monkeypatch.setattr(settings, 'tinyfish_fetch_enabled', False)
    monkeypatch.setattr(settings, 'search_max_pages', 2)

def finding():
    return SearchDorkerTool()._build_finding(url=URL, title='Ana Prueba', snippet='Ana Prueba', dork=Dork('"Ana Prueba"', 'fixture'), engine='tavily', relevance=0.6)

@pytest.mark.asyncio
@respx.mock
async def test_native_excludes_scripts_and_records_public_evidence():
    respx.get(URL).respond(200, text=f'<title>Evento</title><script>secret script</script><article>{TEXT}</article>', headers={'content-type': 'text/html'})
    item = finding()
    confidence = item.confidence
    ctx = TargetContext()
    await enrich_search_findings([item], ctx)
    assert item.metadata_info['page_literal_match'] is True
    assert 'secret script' not in item.metadata_info['page_excerpt']
    assert item.confidence == confidence and item.metadata_info['ownership_status'] == 'unverified'
    route = respx.get(URL).respond(500)
    calls_before = route.call_count
    await enrich_search_findings([item], ctx)
    assert route.call_count == calls_before

@pytest.mark.asyncio
@respx.mock
async def test_missing_term_does_not_become_page_evidence():
    respx.get(URL).respond(200, text='Publicación sin relación con el nombre buscado. ' * 5, headers={'content-type': 'text/plain'})
    item = finding()
    await enrich_search_findings([item], TargetContext())
    assert item.metadata_info['page_literal_match'] is False
    assert 'page_excerpt' not in item.metadata_info

@pytest.mark.parametrize('kind', ['private_redirect', 'login', 'large', 'pdf'])
@pytest.mark.asyncio
@respx.mock
async def test_reader_restrictions(kind):
    responses = {'private_redirect': httpx.Response(302, headers={'location': 'http://127.0.0.1/private'}), 'login': httpx.Response(200, text='<input type="password">', headers={'content-type': 'text/html'}), 'large': httpx.Response(200, content=b'a' * (MAX_BYTES + 1), headers={'content-type': 'text/plain'}), 'pdf': httpx.Response(200, content=b'%PDF', headers={'content-type': 'application/pdf'})}
    respx.get(URL).mock(return_value=responses[kind])
    page = await read_public_page(URL)
    assert page['status'] == {'private_redirect': 'unsafe_redirect', 'login': 'login_required', 'large': 'too_large', 'pdf': 'unsupported_content'}[kind]

@pytest.mark.asyncio
@respx.mock
async def test_native_redirect_retains_final_source():
    respx.get(URL).respond(302, headers={'location': '/final'})
    respx.get('https://example.test/final').respond(200, text=TEXT, headers={'content-type': 'text/plain'})
    item = finding()
    await enrich_search_findings([item], TargetContext())
    assert item.evidence_urls[-1] == 'https://example.test/final'

@pytest.mark.asyncio
@respx.mock
async def test_tinyfetch_keyless_returns_disabled():
    route = respx.post(TINYFETCH_URL).respond(500)
    assert (await read_tinyfish_page(URL))['status'] == 'disabled'
    assert not route.called

@pytest.mark.asyncio
@respx.mock
async def test_thin_js_page_uses_tinyfetch_when_opted_in(monkeypatch):
    monkeypatch.setattr(settings, 'tinyfish_api_key', SecretStr('fixture-tiny'))
    monkeypatch.setattr(settings, 'tinyfish_fetch_enabled', True)
    respx.get(URL).respond(200, text='<div id="app"></div>', headers={'content-type': 'text/html'})
    route = respx.post(TINYFETCH_URL).respond(200, json={'results': [{'url': URL, 'final_url': URL, 'title': 'Evento', 'text': TEXT}], 'errors': []})
    item = finding()
    await enrich_search_findings([item], TargetContext())
    assert item.metadata_info['page_reader'] == 'tinyfish_fetch'
    assert item.metadata_info['page_literal_match'] is True
    assert route.calls[0].request.headers['X-API-Key'] == 'fixture-tiny'

@pytest.mark.parametrize('payload,expected', [({'results': [], 'errors': [{'url': URL, 'code': 'login_required'}]}, 'provider_error'), ({'results': [{'url': URL, 'final_url': 'http://localhost/private', 'text': TEXT}]}, 'unsafe_redirect'), ([], 'invalid_payload'), ({'results': [{'url': 'https://other.test/', 'text': TEXT}]}, 'empty')])
@pytest.mark.asyncio
@respx.mock
async def test_tinyfetch_payload_and_final_url(payload, expected, monkeypatch):
    monkeypatch.setattr(settings, 'tinyfish_api_key', SecretStr('fixture-tiny'))
    monkeypatch.setattr(settings, 'tinyfish_fetch_enabled', True)
    respx.post(TINYFETCH_URL).respond(200, json=payload)
    assert (await read_tinyfish_page(URL))['status'] == expected

@pytest.mark.asyncio
@respx.mock
async def test_fetch_quota_breaker_and_page_budget(monkeypatch):
    monkeypatch.setattr(settings, 'tinyfish_api_key', SecretStr('fixture-tiny'))
    monkeypatch.setattr(settings, 'tinyfish_fetch_enabled', True)
    respx.get(url__startswith='https://example.test/').respond(503)
    route = respx.post(TINYFETCH_URL).respond(402)
    items = [finding() for _ in range(3)]
    for i, item in enumerate(items):
        item.value = URL + str(i)
    ctx = TargetContext()
    await enrich_search_findings(items, ctx)
    assert route.call_count == 1
    assert len(ctx.extra['search_read_urls']) == 2 and ctx.extra['search_fetch_disabled'] is True

@pytest.mark.asyncio
@respx.mock
async def test_search_execute_opt_in_reader_without_tinyfish(monkeypatch):
    monkeypatch.setattr(settings, 'search_read_pages', True)
    monkeypatch.setattr(settings, 'tavily_api_key', 'fixture-key')
    respx.post('https://api.tavily.com/search').respond(200, json={'results': [{'title': 'Ana Prueba', 'url': URL, 'content': 'Ana Prueba'}]})
    respx.post('https://html.duckduckgo.com/html/').respond(500)
    respx.get(URL).respond(200, text=TEXT, headers={'content-type': 'text/plain'})
    tiny = respx.post(TINYFETCH_URL).respond(500)
    findings = await SearchDorkerTool().execute(TargetContext(full_name='Ana Prueba'))
    assert findings[0].metadata_info['page_literal_match'] is True
    assert not tiny.called

@pytest.mark.asyncio
@respx.mock
async def test_auth_redirect_never_becomes_public_evidence(monkeypatch):
    monkeypatch.setattr(settings, 'tinyfish_api_key', SecretStr('fixture-tiny'))
    monkeypatch.setattr(settings, 'tinyfish_fetch_enabled', True)
    respx.post(TINYFETCH_URL).respond(200, json={'results': [{'url': URL, 'final_url': 'https://example.test/login', 'text': TEXT}]})
    assert (await read_tinyfish_page(URL))['status'] == 'unsafe_redirect'
