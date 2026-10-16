"""Automatic Lite policy and concurrent multi-source coverage; no live providers."""
import asyncio
from dataclasses import replace
from uuid import uuid4

import pytest

from app.core.config import settings
from app.engine.lite_policy import creation_policy, COMMON_PLATFORMS
from app.engine.fair_plan import FairPlan
from app.schemas.investigation import InvestigationCreate
from app.schemas.target import TargetCreate
from app.schemas.workspace import MaigretPlan
from app.tools.maigret_catalog import build_scan_catalog
from test_fair_orchestrator import Stub, target, engine


@pytest.mark.parametrize('scan_mode', ['fast', 'deep', 'all'])
def test_lite_ignores_normal_modes_and_manual_maigret_plans(monkeypatch, scan_mode):
    monkeypatch.setattr(settings, 'personmap_env', 'lite')
    payload = InvestigationCreate(target=TargetCreate(username='fixture'), strategy='agentic', pivot_mode='deep',
                                  maigret_plan=MaigretPlan(scan_mode=scan_mode))
    normalized = creation_policy(payload)
    assert normalized.acquisition_mode == 'fair'
    assert normalized.strategy == 'rule_based' and normalized.pivot_mode == 'standard'
    assert normalized.maigret_plan is None
    assert payload.maigret_plan.scan_mode == scan_mode


def test_normal_and_external_workspaces_keep_their_explicit_configuration(monkeypatch):
    payload = InvestigationCreate(target=TargetCreate(username='fixture'), maigret_plan=MaigretPlan(scan_mode='all'))
    monkeypatch.setattr(settings, 'personmap_env', 'normal')
    assert creation_policy(payload) is payload
    monkeypatch.setattr(settings, 'personmap_env', 'lite')
    external = payload.model_copy(update={'execution_mode': 'external'})
    assert creation_policy(external) is external


def test_lite_plan_limits_platforms_without_disabling_search_social_or_academic(monkeypatch):
    monkeypatch.setattr(settings, 'personmap_env', 'lite')
    monkeypatch.setattr(settings, 'fair_disabled_sources', [])
    monkeypatch.setattr(settings, 'fair_total_deadline_seconds', 600)
    plan = FairPlan.configured()
    assert plan.deadline_seconds == 225 and plan.max_waves == 3 and plan.username_sites <= 100
    assert plan.maigret_options['names'] == list(COMMON_PLATFORMS)
    assert not plan.maigret_options['parse'] and not plan.maigret_options['enrich']
    assert not plan.maigret_options['permutation_parts']
    assert {'search_dorker', 'academic_finder', 'apify_social', 'username_finder', 'ghunt', 'breach_checker', 'email_enumerator', 'infostealer_checker'} <= {s.tool for s in plan.sources if s.enabled and s.first_wave == 1}
    recipes = build_scan_catalog(include_variants=True, names=list(COMMON_PLATFORMS), tags=[], excluded=[])
    assert {r.name.casefold() for r in recipes} == {n.casefold() for n in COMMON_PLATFORMS}
    assert len(recipes) <= plan.username_sites


@pytest.mark.asyncio
async def test_search_apify_and_academia_run_without_waiting_for_slow_username_finder(monkeypatch):
    monkeypatch.setattr(settings, 'personmap_env', 'lite')
    entered = set()
    all_started = asyncio.Event()
    def response(name):
        async def run(context):
            entered.add(name)
            if len(entered) == 4:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), 2)
            if name == 'username_finder':
                await asyncio.sleep(20)
            return []
        return run
    names = ['username_finder', 'search_dorker', 'apify_social', 'academic_finder']
    tools = [Stub(name, response(name)) for name in names]
    runner = engine(monkeypatch, tools, deadline_seconds=.2)
    run = await runner.collect_findings(str(uuid4()), target(given_names='Fixture', family_names='Person'))
    assert entered == set(names)
    assert all(run.sources[n]['status'] == 'completed' for n in names if n != 'username_finder')
    assert run.sources['username_finder']['status'] == 'timeout'


@pytest.mark.asyncio
async def test_configured_context_overrides_stale_deep_options(monkeypatch):
    monkeypatch.setattr(settings, 'personmap_env', 'lite')
    seen = []
    async def collect(context):
        seen.append(context.extra['maigret_options'])
        return []
    runner = engine(monkeypatch, [Stub('username_finder', collect)])
    configured = FairPlan.configured()
    runner.plan = replace(runner.plan, maigret_options=configured.maigret_options, username_sites=configured.username_sites)
    await runner.collect_findings(str(uuid4()), target())
    assert seen[0]['names'] == list(COMMON_PLATFORMS)
    assert seen[0]['parse'] is False


@pytest.mark.asyncio
async def test_health_exposes_effective_mode_without_credentials(monkeypatch):
    from app.main import health_check
    monkeypatch.setattr(settings, 'personmap_env', 'lite')
    health = await health_check()
    assert health['default_acquisition_mode'] == 'fair'
    assert health['lite_plan']['deadline_seconds'] <= 225
    assert health['lite_plan']['platforms'] == list(COMMON_PLATFORMS)


@pytest.mark.asyncio
async def test_infostealer_identifier_tasks_do_not_replay_other_identifiers(monkeypatch):
    from app.engine.fair_plan import SourcePlan
    seen = []
    async def query(context):
        emails, aliases = context.all_emails(), context.all_usernames()
        assert len(emails) + len(aliases) == 1
        seen.extend(('email', value) for value in emails)
        seen.extend(('username', value) for value in aliases)
        return []
    runner = engine(monkeypatch, [Stub('infostealer_checker', query, required=('email', 'username'))],
                    sources=[SourcePlan('infostealer_checker', 0, 1, scope='identifier', max_invocations=6)])
    await runner.collect_findings(str(uuid4()), target(emails=['one@example.org', 'two@example.org']))
    assert sorted(seen) == [('email', 'one@example.org'), ('email', 'two@example.org'), ('username', 'seed_alias')]


def test_lite_retains_operator_disabled_sources(monkeypatch):
    monkeypatch.setattr(settings, 'personmap_env', 'lite')
    monkeypatch.setattr(settings, 'fair_disabled_sources', ['infostealer_checker', 'apify_social'])
    plan = FairPlan.configured()
    assert not any(s.enabled for s in plan.sources if s.tool in {'infostealer_checker', 'apify_social'})
    assert len(COMMON_PLATFORMS) >= 35


@pytest.mark.parametrize('name,diagnostic', [('academic_finder', 'academic_diagnostics'),
                                           ('email_enumerator', 'email_enum_diagnostics')])
@pytest.mark.asyncio
async def test_provider_errors_are_not_reported_as_empty_success(monkeypatch, name, diagnostic):
    async def unavailable(context):
        context.extra[diagnostic] = [{'status': 'blocked', 'http_status': 403}]
        return []
    run = await engine(monkeypatch, [Stub(name, unavailable)]).collect_findings(str(uuid4()), target())
    assert run.sources[name]['status'] == 'provider_unavailable'
    assert run.snapshot()['execution']['partial'] is True


@pytest.mark.asyncio
async def test_search_continues_batches_without_new_identifiers(monkeypatch):
    from app.engine.fair_plan import SourcePlan
    calls = []
    async def batch(context):
        used = context.extra.get('search_queries_used', 0)
        calls.append(used)
        context.extra['search_queries_used'] = used + 2
        return []
    source = Stub('search_dorker', batch, ready=lambda c: c.extra.get('search_queries_used', 0) < 8)
    runner = engine(monkeypatch, [source], sources=[SourcePlan('search_dorker', 0, 1, max_invocations=8)])
    run = await runner.collect_findings(str(uuid4()), target())
    assert calls == [0, 2, 4, 6]
    assert run.context.extra['search_queries_used'] == 8


def test_web_uses_native_operator_budget_and_scribd_studocu_have_own_queries(monkeypatch):
    from app.tools.search_dorker import SearchDorkerTool
    from app.tools.base import TargetContext
    monkeypatch.setattr(settings, 'personmap_env', 'lite')
    monkeypatch.setattr(settings, 'search_max_queries', 60)
    monkeypatch.setattr(settings, 'fair_search_queries', 8)
    monkeypatch.setattr(settings, 'search_timeout_seconds', 120)
    plan = FairPlan.configured()
    assert plan.search_queries == 60
    assert next(s for s in plan.sources if s.tool == 'search_dorker').timeout_seconds == 120
    queries = SearchDorkerTool()._generate_dorks(TargetContext(full_name='Fixture Persona'))
    assert any(q.include_domains == ['scribd.com'] for q in queries)
    assert any(q.include_domains == ['studocu.com'] for q in queries)
