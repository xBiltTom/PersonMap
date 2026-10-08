import json
import shutil

import httpx
import pytest
import respx

from app.core.config import settings
from app.schemas.target import TargetCreate
from app.tools.base import TargetContext, ToolFinding
from app.tools.dni_lookup import DniLookupTool
from app.tools.dni_public import normalize_dni, matches_dni, parse_public_document, publisher, public_source_url
from app.tools.search_dorker import Dork, SearchDorkerTool, _matches_literally
from app.engine.pivot_rules import extract_and_apply_pivots
from app.engine.rule_engine import RuleEngine

DNI = '00123456'
URL = 'https://www.reniec.gob.pe/publicacion.csv'
CSV = f'dni,nombres,apellidoPaterno,apellidoMaterno\n87654321,OTRA,PERSONA,PRUEBA\n{DNI},ANA,PRUEBA,SINTETICA\n'

@pytest.fixture(autouse=True)
def public_settings(monkeypatch):
    monkeypatch.setattr(settings, 'dni_public_source_urls', [])
    monkeypatch.setattr(settings, 'dni_max_public_sources', 4)

@pytest.mark.parametrize('raw,expected', [(DNI,DNI), (' '+DNI+' ', DNI), ('abc'+DNI,None), ('1234-5678',None), ('１２３４５６７８',None), ('123456789',None), ('',None), (None,None)])
def test_dni_validation(raw, expected):
    assert normalize_dni(raw) == expected
    assert DniLookupTool().can_run(TargetContext(dni=raw)) is (expected is not None)
    if raw is None or raw == '':
        assert TargetCreate(username='fixture', dni=raw).dni is None
    elif expected is None:
        with pytest.raises(ValueError):
            TargetCreate(dni=raw)
    else:
        assert TargetCreate(dni=raw).dni == expected

@pytest.mark.parametrize('text,expected', [(f'DNI: {DNI}',True), (f'99{DNI}99',False), ('00 12 34 56',False), (f'https://example.test/?q={DNI}',False), ('DNI: 87654321',False), ('abc'+DNI,False)])
def test_exact_dni_matching(text, expected):
    assert matches_dni(DNI, text) is expected
    assert _matches_literally(Dork(f'"{DNI}"', 'DNI', dni=DNI), '', text, f'https://example.test/?q={DNI}') is expected

@pytest.mark.asyncio
@respx.mock
async def test_no_private_lookup_even_with_old_token(monkeypatch):
    monkeypatch.setattr(settings, 'apis_net_pe_token', 'unused-test-token')
    assert await DniLookupTool().execute(TargetContext(dni=DNI)) == []
    assert len(respx.calls) == 0

@pytest.mark.asyncio
@respx.mock
async def test_public_reniec_dataset_only_exact_record_and_cache():
    respx.get(URL).respond(200, text=CSV, headers={'content-type':'text/csv'})
    context = TargetContext(dni=DNI, extra={'dni_source_urls':[URL]})
    tool = DniLookupTool()
    findings = await tool.execute(context)
    assert len(findings) == 1
    f = findings[0]
    assert f.platform == 'reniec_public'
    assert f.evidence_urls == [URL]
    assert f.metadata_info['full_name'] == 'ANA PRUEBA SINTETICA'
    assert f.metadata_info['ownership_status'] == 'unverified'
    assert 'OTRA' not in str(f.metadata_info)
    before = RuleEngine()._get_tool_run_key(SearchDorkerTool(), context)
    assert extract_and_apply_pivots(findings, context)
    assert context.full_name is None
    assert context.discovered_names == ['ANA PRUEBA SINTETICA']
    assert RuleEngine()._get_tool_run_key(SearchDorkerTool(), context) != before
    assert any('ANA PRUEBA SINTETICA' in d.query for d in SearchDorkerTool()._generate_dorks(context))
    assert await tool.execute(context) == []
    assert len(respx.calls) == 1

@pytest.mark.parametrize('status', [401,403,404,429,503])
@pytest.mark.asyncio
@respx.mock
async def test_public_failures_do_not_create_identity(status):
    respx.get(URL).respond(status)
    context=TargetContext(dni=DNI, extra={'dni_source_urls':[URL]})
    assert await DniLookupTool().execute(context) == []
    assert context.extra['dni_public_results'][DNI+'|'+URL]['http_status'] == status

@pytest.mark.asyncio
@respx.mock
async def test_stream_limit_and_investigation_budget(monkeypatch):
    monkeypatch.setattr(settings,'dni_max_public_sources',1)
    respx.get(URL).respond(200, content=b'x', headers={'content-length':'2000001'})
    context=TargetContext(dni=DNI, extra={'dni_source_urls':[URL,'https://example.test/next.csv']})
    assert await DniLookupTool().execute(context) == []
    assert context.extra['dni_public_results'][DNI+'|'+URL]['status'] == 'too_large'
    assert len(respx.calls) == 1

@pytest.mark.parametrize('url', ['http://127.0.0.1/file','http://localhost/file','http://192.168.1.1/file','https://user:pass@example.test/file','https://api.apis.net.pe/v1/dni','https://dniruc.apisperu.com/api/dni/12345678','file:///tmp/dataset'])
def test_non_public_and_lookup_routes_excluded(url):
    assert public_source_url(url) is None


def test_publisher_not_inferred_from_domain_substring():
    assert publisher('https://reniec.gob.pe.evil.test/file') != 'reniec_public'
    assert publisher(URL) == 'reniec_public'

@pytest.mark.parametrize('kind,body', [('text/csv',CSV), ('application/json',json.dumps([{'dni':DNI,'primerNombre':'ANA','segundoNombre':'MARIA','apellidoPaterno':'PRUEBA'}])), ('text/html',f'<table><tr><th>DNI</th><th>Nombre completo</th></tr><tr><td>87654321</td><td>OTRA PERSONA</td></tr><tr><td>{DNI}</td><td>ANA PRUEBA</td></tr></table>')])
def test_names_require_same_structured_record(kind,body):
    rows, _ = parse_public_document(body.encode(),kind,'https://example.test/file',DNI)
    assert len(rows) == 1
    assert rows[0]['full_name'].startswith('ANA')
    assert rows[0]['name_association'] == 'structured_same_record'


def test_text_nearby_name_not_associated():
    rows, _ = parse_public_document(f'OTRA PERSONA DNI {DNI}'.encode(),'text/plain','https://example.test/file',DNI)
    assert len(rows) == 1
    assert not rows[0].get('full_name')
    assert rows[0]['name_association'] == 'unverified'
    assert parse_public_document(f'<script>DNI {DNI}</script><p>sin evidencia</p>'.encode(),'text/html',URL,DNI)[0] == []


def test_invalid_or_aggregate_json_not_identity():
    assert parse_public_document(b'{broken','application/json',URL,DNI)[0] == []
    assert parse_public_document(json.dumps([{'dni':'87654321','nombreCompleto':'OTRA PERSONA'}]).encode(),'application/json',URL,DNI)[0] == []
    assert parse_public_document(json.dumps([{'dni':DNI,'numeroDocumento':'87654321','nombreCompleto':'OTRA PERSONA'}]).encode(),'application/json',URL,DNI)[0] == []


def test_search_mention_only_pivots_to_public_source():
    context=TargetContext(dni=DNI)
    finding=SearchDorkerTool()._build_finding(url=URL,title='Datos públicos',snippet=f'DNI {DNI}',dork=Dork(f'"{DNI}"','DNI',dni=DNI),engine='fixture',relevance=None)
    before=RuleEngine()._get_tool_run_key(DniLookupTool(),context)
    assert extract_and_apply_pivots([finding],context)
    assert context.extra['dni_source_urls'] == [URL]
    assert context.discovered_names == []
    assert RuleEngine()._get_tool_run_key(DniLookupTool(),context) != before

@pytest.mark.asyncio
@respx.mock
async def test_dni_filter_cannot_be_disabled_or_match_url_only(monkeypatch):
    monkeypatch.setattr(settings,'tavily_api_key','test-key')
    monkeypatch.setattr(settings,'tavily_require_literal_match',False)
    respx.post('https://api.tavily.com/search').respond(200,json={'results':[{'url':f'https://example.test/?q={DNI}','title':None,'content':'unrelated','score':0.99}]})
    async with httpx.AsyncClient() as client:
        assert await SearchDorkerTool()._search_tavily(client,Dork(f'"{DNI}"','DNI',dni=DNI),set()) == []


def test_dni_queries_keep_reniec_as_public_publisher():
    dorks=SearchDorkerTool()._generate_dorks(TargetContext(dni=DNI))
    assert any(d.include_domains == ['reniec.gob.pe'] for d in dorks)
    assert all(d.dni == DNI for d in dorks)


def test_name_conflicts_never_replace_input_name():
    context=TargetContext(dni=DNI,full_name='NOMBRE APORTADO')
    finding=ToolFinding(entity_type='document',value='fixture',metadata_info={'dni':DNI,'full_name':'OTRO NOMBRE','source_kind':'public_document','name_association':'structured_same_record','source_url':URL})
    assert extract_and_apply_pivots([finding],context)
    assert context.full_name == 'NOMBRE APORTADO'
    assert context.extra['dni_name_candidates'][0]['status'] == 'candidate'


def test_pdf_invalid_document_is_diagnostic():
    rows, kind = parse_public_document(b'%PDF-invalid','application/pdf',URL,DNI)
    assert rows == []
    assert kind in {'pdf_parse_error','pdf_reader_unavailable'}


def test_real_pdf_text_extraction():
    if not shutil.which('pdftotext'):
        pytest.skip('Poppler is optional outside the Docker runtime')
    content = f'BT /F1 12 Tf 72 720 Td (DNI {DNI}) Tj ET'.encode()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(content)).encode() + b' >>\nstream\n' + content + b'\nendstream']
    pdf = b'%PDF-1.4\n'
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += str(index).encode() + b' 0 obj\n' + obj + b'\nendobj\n'
    xref = len(pdf)
    pdf += b'xref\n0 6\n0000000000 65535 f \n'
    for offset in offsets[1:]:
        pdf += f'{offset:010d} 00000 n \n'.encode()
    pdf += f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    rows, kind = parse_public_document(pdf, 'application/pdf', 'https://example.test/document.pdf', DNI)
    assert kind == 'pdf'
    assert rows[0]['dni'] == DNI
    assert not rows[0].get('full_name')

@pytest.mark.asyncio
async def test_redirect_to_private_lookup_is_not_observed():
    with respx.mock(assert_all_called=False) as router:
        router.get(URL).respond(302, headers={'location':'https://dniruc.apisperu.com/api/dni/00123456'})
        blocked = router.get('https://dniruc.apisperu.com/api/dni/00123456').respond(200, text=CSV, headers={'content-type':'text/csv'})
        context = TargetContext(dni=DNI, extra={'dni_source_urls':[URL]})
        assert await DniLookupTool().execute(context) == []
        assert context.extra['dni_public_results'][DNI+'|'+URL]['status'] == 'request_error'
        assert not blocked.called

@pytest.mark.asyncio
@respx.mock
async def test_actual_stream_size_limit_without_length_header():
    respx.get(URL).respond(200, content=b'x' * 2000001, headers={'content-type':'text/plain'})
    context=TargetContext(dni=DNI, extra={'dni_source_urls':[URL]})
    assert await DniLookupTool().execute(context) == []
    assert context.extra['dni_public_results'][DNI+'|'+URL]['status'] == 'too_large'


@pytest.mark.asyncio
@respx.mock
async def test_rules_follow_public_source_then_search_candidate_name(monkeypatch):
    from app.models.target import Target
    from app.tools.registry import tool_registry
    monkeypatch.setattr(tool_registry, '_tools', {'dni_lookup':DniLookupTool(), 'search_dorker':SearchDorkerTool()})
    monkeypatch.setattr(settings, 'tavily_api_key', 'fixture-key')
    monkeypatch.setattr(settings, 'tavily_max_queries', 5)
    respx.post('https://html.duckduckgo.com/html/').respond(500)
    respx.post('https://api.tavily.com/search').respond(200,json={'results':[{'url':URL,'title':'ANA PRUEBA SINTETICA','content':f'DNI {DNI}', 'score':0.8}]})
    respx.get(URL).respond(200,text=CSV,headers={'content-type':'text/csv'})
    result = await RuleEngine().collect_findings('dni-fixture', Target(dni=DNI, extra_data={}))
    assert result.context.full_name is None
    assert result.context.discovered_names == ['ANA PRUEBA SINTETICA']
    assert any(f.entity_type == 'document' and f.metadata_info.get('source_url') == URL for f in result.findings)
    assert any('ANA PRUEBA SINTETICA' in query[0] for query in result.context.extra['search_queries_executed'])
    assert len(result.context.extra['search_queries_executed']) == 5
    assert result.rounds >= 3
