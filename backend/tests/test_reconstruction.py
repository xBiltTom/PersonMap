"""REST/PostgreSQL coverage in disposable schemas in personmap_lite."""
import asyncio
import json
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from test_exposure_lens import exposure_workspace, _finalize  # noqa: F401
from app.core.config import settings
from app.models.exposure_run import ExposureRun
from app.models.reconstruction_run import ReconstructionRun
from app.services import digital_reconstruction

pytestmark = pytest.mark.db


def path(ws):
    return f"/api/v1/investigations/{ws['investigation_id']}/reconstruction"


async def ready(ws):
    await _finalize(ws)
    response = await ws['client'].post(f"/api/v1/investigations/{ws['investigation_id']}/exposure/analyze")
    assert response.status_code == 200, response.text


@pytest.mark.asyncio
async def test_preconditions_and_pending_no_automatic_exposure(exposure_workspace):
    ws = exposure_workspace
    for method, suffix in (('get', ''), ('post', '/build')):
        response = await getattr(ws['client'], method)(path(ws) + suffix)
        assert response.status_code == 409 and response.json()['detail']['code'] == 'review_not_finalized'
    await _finalize(ws)
    for method, suffix in (('get', ''), ('post', '/build')):
        response = await getattr(ws['client'], method)(path(ws) + suffix)
        assert response.status_code == 409 and response.json()['detail']['code'] == 'exposure_analysis_required'
    async with ws['factory']() as db:
        assert not (await db.scalars(select(ExposureRun))).all()
        assert not (await db.scalars(select(ReconstructionRun))).all()
    await ready(ws)
    response = await ws['client'].get(path(ws))
    assert response.json()['status'] == 'pending' and response.json()['snapshot'] is None


@pytest.mark.asyncio
async def test_full_flow_persistence_explainability_and_cache(exposure_workspace):
    ws = exposure_workspace
    await ready(ws)
    response = await ws['client'].post(path(ws) + '/build')
    assert response.status_code == 200, response.text
    body = response.json()
    snapshot = body['snapshot']
    assert body['status'] == 'completed'
    facts = {f['id']: f for f in snapshot['facts']}
    assert {k: snapshot['counts'][k] for k in ('account', 'alias', 'academic_profile', 'publication', 'post', 'breach')} == {
        'account': 2, 'alias': 1, 'academic_profile': 1, 'publication': 1, 'post': 2, 'breach': 1}
    assert snapshot['graph']['version'] == 'graph-v2'
    types = {edge['type'] for edge in snapshot['graph']['edges']}
    assert {'SAME_ALIAS', 'SAME_EMAIL', 'PUBLISHED', 'AUTHORED', 'EXPOSED_IN_BREACH', 'HAS_EXPOSURE_SIGNAL'} <= types
    for edge in snapshot['correlations']:
        assert edge['evidence_refs']
        if edge['type'] == 'EXPOSED_IN_BREACH':
            assert facts[edge['source']]['kind'] == 'email'
    serialized = json.dumps(snapshot)
    for forbidden in (str(ws['rejected_id']), str(ws['uncertain_id']), 'Los Olivos 123', 'Tuesday at 8', '17:32'):
        assert forbidden not in serialized
    cached = await ws['client'].post(path(ws) + '/build')
    assert cached.json()['cache_hit'] is True and cached.json()['snapshot'] == snapshot
    assert (await ws['client'].get(path(ws))).json()['snapshot'] == snapshot
    async with ws['factory']() as db:
        run = (await db.scalars(select(ReconstructionRun))).one()
        assert run.snapshot == snapshot and run.status == 'completed' and run.completed_at is not None


@pytest.mark.asyncio
async def test_review_change_blocks_old_exposure_and_snapshot(exposure_workspace):
    ws = exposure_workspace
    await ready(ws)
    old = (await ws['client'].post(path(ws) + '/build')).json()
    await ws['client'].patch(f"/api/v1/investigations/{ws['investigation_id']}/review/{ws['confirmed_id']}", json={'decision': 'rejected'})
    response = await ws['client'].get(path(ws))
    assert response.status_code == 409 and response.json()['detail']['code'] == 'review_not_finalized'
    await _finalize(ws)
    for method, suffix in (('get', ''), ('post', '/build')):
        response = await getattr(ws['client'], method)(path(ws) + suffix)
        assert response.status_code == 409 and response.json()['detail']['code'] == 'exposure_report_stale'
        assert 'snapshot' not in response.json()
    await ws['client'].post(f"/api/v1/investigations/{ws['investigation_id']}/exposure/analyze")
    stale = (await ws['client'].get(path(ws))).json()
    assert stale['stale'] is True and stale['snapshot'] is None
    new = (await ws['client'].post(path(ws) + '/build')).json()
    assert new['input_hash'] != old['input_hash']
    assert str(ws['confirmed_id']) not in json.dumps(new['snapshot'])


@pytest.mark.asyncio
async def test_exposure_change_and_config_change_invalidate_reconstruction(exposure_workspace, monkeypatch):
    ws = exposure_workspace
    await ready(ws)
    old = (await ws['client'].post(path(ws) + '/build')).json()
    async with ws['factory']() as db:
        run = (await db.scalars(select(ExposureRun))).one()
        run.completed_at = datetime.now(timezone.utc)
        await db.commit()
    stale = (await ws['client'].get(path(ws))).json()
    assert stale['stale'] and stale['snapshot'] is None
    new = (await ws['client'].post(path(ws) + '/build')).json()
    assert new['input_hash'] != old['input_hash']
    monkeypatch.setattr(settings, 'graph_max_post_nodes', 1)
    assert (await ws['client'].get(path(ws))).json()['stale'] is True
    rebuilt = (await ws['client'].post(path(ws) + '/build')).json()
    assert rebuilt['input_hash'] != new['input_hash']
    assert sum(n['kind'] == 'post' for n in rebuilt['snapshot']['graph']['nodes']) <= 1


@pytest.mark.asyncio
async def test_concurrent_build_and_rollback_leave_only_terminal_runs(exposure_workspace, monkeypatch):
    ws = exposure_workspace
    await ready(ws)
    original = digital_reconstruction.build_snapshot
    def fail(*args, **kwargs):
        raise RuntimeError('fixture interrupted')
    monkeypatch.setattr(digital_reconstruction, 'build_snapshot', fail)
    with pytest.raises(RuntimeError, match='fixture interrupted'):
        await ws['client'].post(path(ws) + '/build')
    async with ws['factory']() as db:
        assert not (await db.scalars(select(ReconstructionRun))).all()
    calls = 0
    def counted(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)
    monkeypatch.setattr(digital_reconstruction, 'build_snapshot', counted)
    responses = await asyncio.gather(*(ws['client'].post(path(ws) + '/build') for _ in range(2)))
    assert all(r.status_code == 200 for r in responses)
    assert calls == 1
    async with ws['factory']() as db:
        assert len((await db.scalars(select(ReconstructionRun))).all()) == 1


@pytest.mark.asyncio
async def test_partial_exposure_keeps_coverage_partial(exposure_workspace, monkeypatch):
    monkeypatch.setattr(settings, 'exposure_max_content_items', 1)
    ws = exposure_workspace
    await ready(ws)
    response = await ws['client'].post(path(ws) + '/build')
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'partial'
    assert response.json()['snapshot']['coverage'] == 'partial'
    assert 'content_limit_reached' in response.json()['snapshot']['coverage_reasons']


@pytest.mark.asyncio
async def test_reverting_configs_reuses_valid_snapshot_without_permanent_staleness(exposure_workspace, monkeypatch):
    ws = exposure_workspace
    await ready(ws)
    original = (await ws['client'].post(path(ws) + '/build')).json()
    graph_limit = settings.graph_max_post_nodes
    monkeypatch.setattr(settings, 'graph_max_post_nodes', 1)
    assert (await ws['client'].post(path(ws) + '/build')).status_code == 200
    monkeypatch.setattr(settings, 'graph_max_post_nodes', graph_limit)
    assert (await ws['client'].get(path(ws))).json()['snapshot'] == original['snapshot']
    max_findings = settings.exposure_max_findings
    monkeypatch.setattr(settings, 'exposure_max_findings', 20)
    await ws['client'].post(f"/api/v1/investigations/{ws['investigation_id']}/exposure/analyze")
    assert (await ws['client'].post(path(ws) + '/build')).status_code == 200
    monkeypatch.setattr(settings, 'exposure_max_findings', max_findings)
    read = await ws['client'].get(path(ws))
    assert read.status_code == 200 and read.json()['stale'] is False
    assert read.json()['snapshot'] == original['snapshot']
    assert (await ws['client'].post(path(ws) + '/build')).json()['cache_hit'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('state', ['running', 'failed'])
async def test_nonterminal_or_failed_exposure_never_triggers_implicit_analysis(exposure_workspace, state):
    ws = exposure_workspace
    await ready(ws)
    async with ws['factory']() as db:
        run = (await db.scalars(select(ExposureRun))).one()
        run.status = state
        await db.commit()
    for method, suffix in (('get', ''), ('post', '/build')):
        response = await getattr(ws['client'], method)(path(ws) + suffix)
        assert response.status_code == 409
        assert response.json()['detail']['code'] == 'exposure_analysis_required'
    async with ws['factory']() as db:
        assert not (await db.scalars(select(ReconstructionRun))).all()
        assert (await db.scalars(select(ExposureRun))).one().status == state
