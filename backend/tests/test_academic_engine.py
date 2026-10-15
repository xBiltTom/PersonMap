"""Academic provider isolation, strict authorship, DOI provenance and bounded pivots."""
import asyncio
import json

import httpx
import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.core.runtime import durable_runtime
from app.engine.persistence import finding_dedupe_key
from app.engine.pivot_rules import extract_and_apply_pivots
from app.tools import http_client
from app.tools.academic_finder import AcademicFinderTool, execution_summary
from app.tools.academic_metadata import doi_url, orcid_url
from app.tools.base import TargetContext, ToolFinding

DOI = 'https://doi.org/10.5555/test.123'
ORCID = 'https://orcid.org/0000-0002-1825-0097'
OTHER_ORCID = 'https://orcid.org/0000-0001-5109-3700'


def crossref_work(**changes):
    return {'DOI': '10.5555/TEST.123', 'title': ['Observed paper'],
        'author': [{'given': 'Ana', 'family': 'Pérez', 'ORCID': ORCID,
                    'affiliation': [{'name': 'Observed University'}]}],
        'published': {'date-parts': [[2024, 2, 1]]}, 'is-referenced-by-count': 8,
        'type': 'journal-article', **changes}


def openalex_work(**changes):
    return {'id': 'https://openalex.org/W1', 'doi': 'http://dx.doi.org/10.5555/test.123',
        'title': 'Observed paper', 'authorships': [{'author': {'id': 'https://openalex.org/A1', 'display_name': 'Ana Pérez', 'orcid': ORCID},
            'institutions': [{'display_name': 'Observed University'}]}],
        'publication_year': 2024, 'cited_by_count': 12, **changes}


def cr_response(items, single=False):
    return httpx.Response(200, json={'status': 'ok', 'message': items[0] if single else {'items': items}})


@pytest.fixture(autouse=True)
def config(monkeypatch):
    for key,value in [('crossref_enabled',True),('crossref_mailto',None),('openalex_api_key',None),
        ('academic_max_requests',24),('academic_batch_timeout',60)]:
        monkeypatch.setattr(settings,key,value)


def bridge(monkeypatch, responder):
    monkeypatch.setattr(http_client, 'build_client', lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(responder)))


def respond_names(request):
    if request.url.host == 'api.crossref.org':
        return cr_response([crossref_work()])
    if request.url.path == '/authors':
        return httpx.Response(200, json={'results': [{'id': 'https://openalex.org/A1', 'display_name': 'Ana Pérez', 'orcid': ORCID}]})
    return httpx.Response(200, json={'results': [openalex_work()]})


@pytest.mark.parametrize('value', [DOI, 'doi:10.5555/TEST.123', 'http://dx.doi.org/10.5555/test.123', DOI+'?utm_source=fixture'])
def test_doi_forms_share_one_persistent_key(value):
    finding = ToolFinding(entity_type='academic', value=value, platform='research_paper')
    canonical = ToolFinding(entity_type='academic', value=DOI, platform='research_paper')
    assert finding_dedupe_key(finding) == finding_dedupe_key(canonical)
    assert doi_url(value) == DOI


@pytest.mark.parametrize('value', ['https://doi.org.evil.test/10.5555/test', 'https://doi.org@evil.test/10.5555/test',
    'https://example.test/10.5555/test', '10.5555/no space', '10.5555/bad\x00value', '10.123/nope', {}, None])
def test_invalid_dois_never_become_api_inputs(value):
    assert doi_url(value) is None


@pytest.mark.parametrize('value', ['https://orcid.org.evil.test/0000-0002-1825-0097',
    '0000-0002-1825-0098', ORCID+'/works', ORCID+'?view=works'])
def test_orcid_requires_exact_profile_host_and_checksum(value):
    assert orcid_url(value) is None


@pytest.mark.asyncio
async def test_both_providers_merge_same_doi_without_summing_citations_or_identity(monkeypatch):
    bridge(monkeypatch, respond_names)
    context = TargetContext(full_name='Ana Perez', university='Observed University')
    findings = await AcademicFinderTool().execute(context)
    papers = [f for f in findings if f.platform == 'research_paper']
    assert len(papers) == 1
    paper = papers[0]
    assert paper.value == DOI and paper.metadata_info['doi'] == DOI
    assert set(paper.metadata_info['academic_sources']) == {'crossref', 'openalex'}
    assert paper.metadata_info['citation_counts'] == {'crossref': 8, 'openalex': 12}
    assert {r['provider'] for r in paper.metadata_info['academic_records']} == {'crossref', 'openalex'}
    assert paper.metadata_info['independent_identity_confirmations'] == 0
    assert paper.metadata_info['ownership_status'] == 'unverified'
    assert paper.metadata_info['affiliation_match'] is True
    assert not AcademicFinderTool().can_run(context)
    assert await AcademicFinderTool().execute(context) == []


@pytest.mark.asyncio
@pytest.mark.parametrize('failed', ['openalex', 'crossref'])
async def test_one_blocked_provider_keeps_other_provider_findings(monkeypatch, failed):
    def respond(request):
        return httpx.Response(429) if request.url.host == 'api.'+failed+'.org' else respond_names(request)
    bridge(monkeypatch, respond)
    context = TargetContext(full_name='Ana Perez', discovered_names=['Juan Lopez'])
    findings = await AcademicFinderTool().execute(context)
    assert any(f.platform == 'research_paper' and f.value == DOI for f in findings)
    assert context.extra['academic_disabled_providers'] == [failed]
    assert sum(r['provider'] == failed for r in context.extra['academic_diagnostics']) == 1
    assert any(r['status'] == 'rate_limited' for r in context.extra['academic_diagnostics'])


@pytest.mark.asyncio
async def test_crossref_fuzzy_hits_and_coauthor_affiliations_do_not_prove_match(monkeypatch):
    work = crossref_work(author=[
        {'given': 'Ana', 'family': 'Perez', 'affiliation': [{'name': 'Different University'}]},
        {'given': 'Other', 'family': 'Person', 'ORCID': ORCID, 'affiliation': [{'name': 'Queried University'}]}])
    wrong = crossref_work(DOI='10.5555/wrong', author=[{'given': 'Ana Maria', 'family': 'Perez'}])
    bridge(monkeypatch, lambda r: cr_response([work,wrong]) if r.url.host == 'api.crossref.org' else httpx.Response(200,json={'results':[]}))
    context = TargetContext(full_name='Ana Perez', university='Queried University')
    findings = await AcademicFinderTool().execute(context)
    assert len(findings) == 1 and findings[0].value == DOI
    m = findings[0].metadata_info
    assert m['affiliation_match'] is False and m['institutions'] == ['Different University']
    assert not m.get('linked_profiles')
    extract_and_apply_pivots(findings, context)
    assert not context.extra.get('maigret_identifiers')
    assert context.discovered_names == [] and context.all_usernames() == []


@pytest.mark.asyncio
async def test_orcid_search_checks_returned_author_field_not_query_or_coauthor(monkeypatch):
    def respond(request):
        if request.url.host == 'api.crossref.org':
            assert request.url.params['filter'] == 'orcid:0000-0002-1825-0097'
            return cr_response([crossref_work(),crossref_work(DOI='10.5555/wrong',author=[{'given':'Ana','family':'Perez','ORCID':OTHER_ORCID}])])
        if request.url.path == '/authors':
            assert request.url.params['filter'] == 'orcid:'+ORCID
            return httpx.Response(200,json={'results':[
                {'id':'https://openalex.org/A1','display_name':'Ana Perez','orcid':ORCID},
                {'id':'https://openalex.org/A2','display_name':'Wrong Person','orcid':OTHER_ORCID}]})
        return httpx.Response(200,json={'results':[openalex_work()]})
    bridge(monkeypatch,respond)
    context = TargetContext(extra={'maigret_identifiers':[{'id_type':'orcid','value':ORCID.rsplit('/',1)[-1]}]})
    tool = AcademicFinderTool()
    assert tool.can_run(context)
    findings = await tool.execute(context)
    assert {f.value for f in findings} == {DOI,'https://openalex.org/A1'}
    assert all(f.metadata_info.get('ownership_status') == 'unverified' for f in findings)


@pytest.mark.asyncio
async def test_direct_doi_without_name_never_promotes_all_authors_to_target(monkeypatch):
    def respond(request):
        if request.url.host == 'api.crossref.org':
            return cr_response([crossref_work()],single=True)
        return httpx.Response(200,json={'results':[openalex_work(),openalex_work(id='https://openalex.org/W2',doi='10.5555/wrong')]})
    bridge(monkeypatch,respond)
    context = TargetContext(extra={'candidate_urls':[DOI]})
    findings = await AcademicFinderTool().execute(context)
    assert len(findings) == 1 and findings[0].value == DOI
    assert findings[0].metadata_info['target_association_status'] == 'not_asserted'
    assert not findings[0].metadata_info.get('linked_profiles')
    extract_and_apply_pivots(findings,context)
    assert not context.extra.get('maigret_identifiers') and not context.discovered_names


@pytest.mark.asyncio
async def test_affiliation_query_can_fall_back_when_editorial_metadata_is_missing(monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        if request.url.host == 'api.crossref.org':
            return cr_response([] if 'query.affiliation' in request.url.params else [crossref_work(author=[{'given':'Ana','family':'Perez'}])])
        return httpx.Response(200,json={'results':[]})
    bridge(monkeypatch,respond)
    findings = await AcademicFinderTool().execute(TargetContext(full_name='Ana Perez',university='Requested University'))
    assert len(findings) == 1 and findings[0].metadata_info.get('affiliation_match') is None
    assert len([r for r in calls if r.url.host == 'api.crossref.org']) == 2


@pytest.mark.asyncio
async def test_total_request_budget_survives_reload_and_pivots(monkeypatch):
    monkeypatch.setattr(settings,'academic_max_requests',2)
    calls = []
    def respond(request):
        calls.append(request)
        return respond_names(request)
    bridge(monkeypatch,respond)
    context = TargetContext(full_name='Ana Perez')
    findings = await AcademicFinderTool().execute(context)
    assert findings and len(calls) == 2
    restored = TargetContext(full_name='Ana Perez',discovered_names=['New Person'],extra=durable_runtime(context.extra))
    assert not AcademicFinderTool().can_run(restored)
    assert await AcademicFinderTool().execute(restored) == []
    assert len(calls) == 2 and execution_summary(restored)['requests'] == 2


@pytest.mark.asyncio
async def test_timeout_preserves_completed_provider_findings(monkeypatch):
    monkeypatch.setattr(settings,'academic_batch_timeout',1)
    async def respond(request):
        if request.url.host == 'api.crossref.org':
            return cr_response([crossref_work()])
        await asyncio.sleep(2)
        return httpx.Response(200,json={'results':[]})
    bridge(monkeypatch,respond)
    context = TargetContext(full_name='Ana Perez')
    findings = await AcademicFinderTool().execute(context)
    assert len(findings) == 1 and findings[0].value == DOI
    assert execution_summary(context)['counts']['budget_exhausted'] == 1


@pytest.mark.asyncio
async def test_provider_credentials_and_operator_contact_do_not_leak_or_use_target_email(monkeypatch):
    monkeypatch.setattr(settings,'openalex_api_key',SecretStr('fixture-secret-key'))
    monkeypatch.setattr(settings,'crossref_mailto','operator@example.org')
    seen = []
    def respond(request):
        seen.append(request)
        if request.url.host == 'api.crossref.org':
            assert request.url.params['mailto'] == 'operator@example.org'
            assert 'api_key' not in request.url.params
        else:
            assert request.url.params['api_key'] == 'fixture-secret-key'
        return respond_names(request)
    bridge(monkeypatch,respond)
    context = TargetContext(full_name='Ana Perez',email='target@example.org')
    findings = await AcademicFinderTool().execute(context)
    report = json.dumps([f.model_dump() for f in findings])+json.dumps(durable_runtime(context.extra))
    assert 'fixture-secret-key' not in report and 'operator@example.org' not in report
    assert all('target@example.org' not in str(r.url) for r in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize('payload',[[],{}, {'status':'ok','message':[]}, {'status':'ok','message':{'items':[None,True,{}]}}])
async def test_malformed_crossref_does_not_break_other_provider(monkeypatch,payload):
    bridge(monkeypatch,lambda r: httpx.Response(200,json=payload) if r.url.host == 'api.crossref.org' else respond_names(r))
    findings = await AcademicFinderTool().execute(TargetContext(full_name='Ana Perez'))
    assert any(f.value == DOI for f in findings)


@pytest.mark.asyncio
async def test_explicit_orcid_subsearch_does_not_query_inherited_name_or_doi(monkeypatch):
    from app.tools.academic_finder import select_call_inputs
    from app.services.workspace import call_fingerprint
    bridge(monkeypatch, respond_names)
    context = TargetContext(full_name='Inherited Person',extra={'candidate_urls':[DOI]})
    select_call_inputs(context,{'identifiers':[{'id_type':'orcid','value':ORCID.rsplit('/',1)[-1]}]})
    before = call_fingerprint('academic_finder',context)
    await AcademicFinderTool().execute(context)
    context.extra['candidate_urls'].append('https://doi.org/10.5555/new')
    assert call_fingerprint('academic_finder',context) == before
    assert {item['kind'] for item in context.extra['academic_queries'].values()} == {'orcid'}


def test_later_doi_only_observation_keeps_prior_author_evidence():
    from app.engine.persistence import dedupe_findings
    record = {'provider':'crossref','match_basis':'orcid','matched_authors':[{'name':'Ana Perez'}],'affiliation_match':True}
    prior = ToolFinding(entity_type='academic',platform='research_paper',value=DOI,confidence=0,
        metadata_info={'academic_records':[record],'ownership_status':'unverified'})
    later = ToolFinding(entity_type='academic',platform='research_paper',value=DOI,
        metadata_info={'academic_records':[{'provider':'openalex','match_basis':'explicit_doi','matched_authors':[]}],
            'target_association_status':'not_asserted','authorship_evidence':'explicit_doi'})
    merged = dedupe_findings([prior,later])[0].metadata_info
    assert merged['target_association_status'] == 'unverified' and merged['authorship_evidence'] == 'orcid'
    assert merged['ownership_status'] == 'unverified' and merged['affiliation_match'] is True


def test_affiliation_matching_never_uses_partial_words():
    from app.tools.academic_metadata import affiliation_match
    assert affiliation_match(['Unobserved University'],'Observed University') is False
    assert affiliation_match(['Department, Observed University, Peru'],'Observed University') is True


@pytest.mark.asyncio
async def test_crossref_serializes_concurrent_investigations(monkeypatch):
    active = peak = 0
    async def respond(request):
        nonlocal active,peak
        if request.url.host != 'api.crossref.org':
            return httpx.Response(200,json={'results':[]})
        active += 1
        peak = max(peak,active)
        await asyncio.sleep(0.02)
        active -= 1
        return cr_response([crossref_work()])
    bridge(monkeypatch,respond)
    results = await asyncio.gather(*(AcademicFinderTool().execute(TargetContext(full_name='Ana Perez')) for _ in range(2)))
    assert peak == 1 and all(result for result in results)


@pytest.mark.asyncio
async def test_traditional_engine_follows_bounded_academic_pivots(monkeypatch):
    from app.engine.rule_engine import RuleEngine
    from app.engine.persistence import dedupe_findings
    from app.models.target import Target
    from app.tools.registry import tool_registry
    bridge(monkeypatch,respond_names)
    monkeypatch.setattr(tool_registry,'get_all',lambda:[AcademicFinderTool()])
    result = await RuleEngine().collect_findings('academic-fixture',Target(full_name='Ana Perez'))
    papers = [f for f in dedupe_findings(result.findings) if f.platform == 'research_paper']
    assert len(papers) == 1 and papers[0].value == DOI
    assert result.context.extra['academic_requests'] <= settings.academic_max_requests
    assert not result.context.all_usernames() and not result.context.discovered_names
    assert all(f.metadata_info['ownership_status'] == 'unverified' for f in result.findings)


def test_academic_schema_supports_doi_and_orcid_without_requiring_name():
    from app.agent.tool_dispatch import build_tool_schemas
    schema = next(s['function']['parameters'] for s in build_tool_schemas() if s['function']['name'] == 'academic_finder')
    assert schema['required'] == []
    assert {rule['required'][0] for rule in schema['anyOf']} == {'full_name','identifiers','candidate_urls'}
    assert 'university' in schema['properties']
