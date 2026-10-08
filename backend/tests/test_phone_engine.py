import httpx
import pytest

from app.core.config import settings
from app.tools.base import BaseTool, TargetContext, ToolCategory, ToolFinding
from app.tools.phone_lookup import PhoneLookupTool
from app.tools.phone_numbers import analyze_phone, phone_identity, extract_phone_observations, matches_phone_text
from app.tools.search_dorker import SearchDorkerTool, Dork, SearchBackend, _matches_literally
from app.engine.pivot_rules import extract_and_apply_pivots


@pytest.mark.parametrize('raw', ['987654321', '987 654 321', '+51 987 654 321', '51987654321', 'tel:+51987654321'])
def test_normalizes_equivalent_numbers(raw):
    assert phone_identity(raw) == '+51987654321'


@pytest.mark.parametrize('raw', ['abc', '+51999', '123', '+999987654321', '987654321oops'])
@pytest.mark.asyncio
async def test_invalid_inputs_have_reasons_and_do_not_create_phone_entities(raw):
    context = TargetContext(phone=raw)
    assert await PhoneLookupTool().execute(context) == []
    assert next(iter(context.extra['phone_lookup_results'].values()))['valid'] is False
    assert next(iter(context.extra['phone_lookup_results'].values()))['validation_reason']


@pytest.mark.asyncio
async def test_local_facts_are_not_carrier_activity_or_messaging_evidence():
    context = TargetContext(phone='987 654 321')
    tool = PhoneLookupTool()
    result = (await tool.execute(context))[0]
    data = result.metadata_info
    assert data['raw_input'] == '987 654 321'
    assert data['country_iso'] == 'PE' and data['line_type'] == 'mobile'
    assert data['original_carrier']
    assert data['current_carrier'] is None and data['active_status'] == 'unknown'
    assert data['contact_links_origin'] == 'derived'
    assert data['messaging_registration_status'] == 'unknown'
    assert result.evidence_urls == []
    assert await tool.execute(context) == []


@pytest.mark.parametrize('raw,kind,country', [('+5111234567', 'fixed_line', 'PE'), ('+12015550123', 'fixed_or_mobile', 'US'), ('+80012345678', 'toll_free', '001')])
def test_line_types_and_non_geographic_numbers(raw, kind, country):
    facts = analyze_phone(raw)
    assert facts['line_type'] == kind and facts['country_iso'] == country
    if country == '001':
        assert facts['numbering_region'] is None and facts['timezones'] == []
    if kind != 'mobile':
        assert facts['original_carrier'] is None


def test_extensions_are_distinct_and_preserved():
    assert phone_identity('+5111234567 ext 123') == '+5111234567;ext=123'
    assert phone_identity('+5111234567 ext 456') != phone_identity('+5111234567 ext 123')
    assert analyze_phone('+5111234567;ext=123')['extension'] == '123'


@pytest.mark.parametrize('text', ['WhatsApp: 987 654 321', 'Teléfono: 987654321', 'Contacto: +51 987 654 321', 'Número +51987654321'])
def test_full_phone_mentions_match_formats(text):
    assert matches_phone_text('+51987654321', text)


@pytest.mark.parametrize('text', ['DNI: 987654321', 'Código ABC987654321', 'RUC 19876543210', 'WhatsApp: 987654320', 'Contacto: +52 987654321', 'Teléfono: 19876543210', '+519876543210', 'Teléfono: 654321'])
def test_partial_dni_other_country_and_longer_numbers_do_not_match(text):
    assert not matches_phone_text('+51987654321', text)


def test_phone_query_uses_or_formats_and_does_not_require_every_variant():
    tool = SearchDorkerTool()
    context = TargetContext(phone='987654321')
    assert tool.can_run(context)
    dork = tool._generate_dorks(context)[0]
    assert dork.phone == '+51987654321' and ' OR ' in dork.query
    assert _matches_literally(dork, 'Contacto', 'WhatsApp: 987 654 321', 'https://example.com')
    assert not _matches_literally(dork, 'Documentos', 'DNI: 987654321', 'https://example.com')


def test_observed_phones_enable_bounded_pivots_with_source_provenance(monkeypatch):
    monkeypatch.setattr(settings, 'phone_max_numbers', 2)
    context = TargetContext(phone='987654321')
    finding = ToolFinding(entity_type='social_account', value='https://github.com/audituser', metadata_info={'source_tool': 'social_verifier', 'extracted_phones': ['+51912345678', '912 345 678', '+12015550123', 'not a phone']})
    assert extract_and_apply_pivots([finding], context)
    assert context.all_phones() == ['+51987654321', '+51912345678']
    assert context.extra['phone_observations']['+51912345678'][0]['source_url'] == finding.value
    assert len(context.extra['phone_observations']['+51912345678']) == 2
    assert not extract_and_apply_pivots([finding], context)


@pytest.mark.asyncio
async def test_discovered_phone_runs_without_seed_and_retains_evidence():
    context = TargetContext()
    finding = ToolFinding(entity_type='social_account', value='https://example.com/profile', metadata_info={'phones': ['987 654 321']})
    extract_and_apply_pivots([finding], context)
    tool = PhoneLookupTool()
    assert tool.can_run(context)
    results = await tool.execute(context)
    assert results[0].value == '+51987654321' and results[0].evidence_urls == [finding.value]


def test_phone_execution_keys_change_and_agent_preserves_discovered_phones():
    from app.engine.rule_engine import RuleEngine
    from app.agent.tool_dispatch import build_call_context
    from app.models.target import Target
    context = TargetContext(phone='987654321')
    engine = RuleEngine()
    before = engine._get_tool_run_key(PhoneLookupTool(), context)
    context.discovered_phones.append('+51912345678')
    assert engine._get_tool_run_key(PhoneLookupTool(), context) != before
    assert build_call_context({}, Target(), context).all_phones() == context.all_phones()


@pytest.mark.asyncio
async def test_search_budget_is_shared_across_rounds_and_does_not_repeat_queries(monkeypatch):
    monkeypatch.setattr(settings, 'tavily_max_queries', 2)
    calls = []
    tool = SearchDorkerTool()
    async def search(client, dork, seen):
        calls.append(dork.query)
        return []
    monkeypatch.setattr(tool, '_backends', lambda: [SearchBackend('fake', lambda: True, lambda: httpx.AsyncClient(), search)])
    context = TargetContext(phone='987654321')
    await tool.execute(context)
    assert await tool.execute(context) == []
    context.discovered_phones.append('+51912345678')
    await tool.execute(context)
    context.discovered_phones.append('+12015550123')
    await tool.execute(context)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_phone_search_rejects_mismatch_even_when_literal_filter_disabled(monkeypatch):
    monkeypatch.setattr(settings, 'tavily_require_literal_match', False)
    dork = Dork('"+51987654321"', 'phone', phone='+51987654321')
    response = {'results': [{'url': 'https://example.com/contact', 'title': 'Contact', 'content': 'Phone: +51912345678'}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))) as client:
        assert await SearchDorkerTool()._search_tavily(client, dork, set()) == []


def test_phone_relationship_does_not_group_identities():
    from app.models.entity import Entity
    from app.engine.persistence import detect_relationships
    phone = Entity(entity_type='phone', value='+51987654321', metadata_info={})
    profile = Entity(entity_type='social_account', value='https://example.com/profile', metadata_info={'phones': ['987 654 321']})
    assert detect_relationships(phone, profile) == [('publishes_phone', False, {'phone': '+51987654321', 'source_url': profile.value})]
    profile.entity_type = 'search_mention'
    assert detect_relationships(profile, phone)[0][0:2] == ('mentions_phone', False)


@pytest.mark.asyncio
async def test_phone_discovered_in_profile_is_analyzed_in_next_round(monkeypatch):
    from app.engine.rule_engine import RuleEngine
    from app.models.target import Target
    from app.tools.registry import tool_registry
    class Source(BaseTool):
        name, description, category, required_inputs = 'phone_source', 'fixture', ToolCategory.SOCIAL, ['full_name']
        async def execute(self, context):
            return [ToolFinding(entity_type='social_account', value='https://example.com/profile', metadata_info={'phones': ['987654321']})]
    monkeypatch.setattr(tool_registry, 'get_all', lambda: [Source(), PhoneLookupTool()])
    result = await RuleEngine().collect_findings('phone-round', Target(full_name='Audit User'))
    assert any(f.entity_type == 'phone' and f.value == '+51987654321' for f in result.findings)

@pytest.mark.asyncio
async def test_optional_network_is_disabled_without_selected_packages(monkeypatch):
    from app.tools.phone_network import lookup_phone_network
    monkeypatch.setattr(settings, 'phone_twilio_fields', [])
    assert await lookup_phone_network('+51987654321') == {'status': 'disabled'}


@pytest.mark.asyncio
@pytest.mark.parametrize('payload,state', [
    ({'phone_number': '+51987654321', 'line_type_intelligence': {'error_code': None, 'carrier_name': 'ProviderCarrier', 'type': 'mobile'}}, 'reported'),
    ({'phone_number': '+51987654321', 'line_type_intelligence': None}, 'unknown'),
    ({'phone_number': '+51987654321', 'line_type_intelligence': {'error_code': 60601}}, 'unsupported'),
])
async def test_network_packages_are_bound_and_separate_from_original_carrier(monkeypatch, payload, state):
    from pydantic import SecretStr
    from app.tools import http_client
    monkeypatch.setattr(settings, 'phone_twilio_fields', ['line_type_intelligence'])
    monkeypatch.setattr(settings, 'phone_twilio_api_key', 'test-key')
    monkeypatch.setattr(settings, 'phone_twilio_api_secret', SecretStr('test-secret'))
    def build_client(**kwargs):
        assert kwargs['max_retries'] == 0 and kwargs['follow_redirects'] is False and kwargs['public_only'] is True
        return httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)))
    monkeypatch.setattr(http_client, 'build_client', build_client)
    result = (await PhoneLookupTool().execute(TargetContext(phone='987654321')))[0]
    assert result.metadata_info['original_carrier'] == 'Claro'
    assert result.metadata_info['network_lookup']['packages']['line_type_intelligence']['status'] == state
    assert result.metadata_info['current_carrier'] is None
    assert 'test-secret' not in result.model_dump_json()


@pytest.mark.asyncio
async def test_network_mismatched_number_is_rejected(monkeypatch):
    from pydantic import SecretStr
    from app.tools import http_client
    from app.tools.phone_network import lookup_phone_network
    monkeypatch.setattr(settings, 'phone_twilio_fields', ['line_status'])
    monkeypatch.setattr(settings, 'phone_twilio_api_key', 'test-key')
    monkeypatch.setattr(settings, 'phone_twilio_api_secret', SecretStr('test-secret'))
    monkeypatch.setattr(http_client, 'build_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={'phone_number': '+51912345678', 'line_status': {'status': 'Active'}}))))
    assert (await lookup_phone_network('+51987654321'))['status'] == 'error'

@pytest.mark.asyncio
async def test_agent_dispatch_keeps_lookup_cache_and_global_phone_budget(monkeypatch):
    from app.agent.tool_dispatch import dispatch_tool_call
    from app.models.target import Target
    monkeypatch.setattr(settings, 'phone_max_numbers', 1)
    context = TargetContext()
    target = Target()
    assert len(await dispatch_tool_call('phone_lookup', {'phone': '987654321'}, target, base_context=context)) == 1
    assert await dispatch_tool_call('phone_lookup', {'phone': '+51987654321'}, target, base_context=context) == []
    assert await dispatch_tool_call('phone_lookup', {'phone': '+51912345678'}, target, base_context=context) == []
    assert len(context.extra['phone_lookup_results']) == 1


def test_phone_only_agent_search_schema_does_not_require_a_name():
    from app.agent.tool_dispatch import build_tool_schemas
    params = next(s['function']['parameters'] for s in build_tool_schemas() if s['function']['name'] == 'search_dorker')
    assert params['required'] == [] and {'required': ['phone']} in params['anyOf']


@pytest.mark.asyncio
async def test_network_line_status_and_failures(monkeypatch):
    from pydantic import SecretStr
    from app.tools import http_client
    from app.tools.phone_network import lookup_phone_network
    monkeypatch.setattr(settings, 'phone_twilio_fields', ['line_status'])
    monkeypatch.setattr(settings, 'phone_twilio_api_key', 'test-key')
    monkeypatch.setattr(settings, 'phone_twilio_api_secret', SecretStr('test-secret'))
    for response, expected in [(httpx.Response(200, json={'phone_number': '+51987654321', 'line_status': {'status': 'Active', 'error_code': None}}), 'completed'), (httpx.Response(429), 'error'), (httpx.Response(200, text='not-json'), 'error')]:
        monkeypatch.setattr(http_client, 'build_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)))
        data = await lookup_phone_network('+51987654321')
        assert data['status'] == expected
        if expected == 'completed':
            assert data['packages']['line_status']['line_status'] == 'Active'
