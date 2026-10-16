"""Real REST creation, no real OSINT. Fixture rejects non-personmap_lite DBs."""
import asyncio
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from test_exposure_lens import exposure_workspace  # noqa: F401
from app.core.config import settings
from app.models.target import Target

pytestmark = pytest.mark.db


@pytest.mark.asyncio
@pytest.mark.parametrize('scan_mode', ['fast', 'deep', 'all'])
async def test_old_form_requests_are_persisted_as_fair_in_lite(exposure_workspace, monkeypatch, scan_mode):
    from app.api.v1.investigations import orchestrator
    monkeypatch.setattr(settings, 'personmap_env', 'lite')
    run = AsyncMock()
    monkeypatch.setattr(orchestrator, 'run_investigation', run)
    ws = exposure_workspace
    response = await ws['client'].post('/api/v1/investigations', json={
        'target': {'input_version': 2, 'given_names': 'Fixture', 'family_names': 'Lite',
                   'usernames': [{'username': 'lite_fixture'}]},
        'strategy': 'agentic', 'acquisition_mode': 'normal', 'subject_consent': True,
        'maigret_plan': {'scan_mode': scan_mode, 'options': {'enrich': True, 'parse': True}},
    })
    assert response.status_code == 201, response.text
    result = response.json()
    assert result['acquisition_mode'] == 'fair'
    assert result['strategy'] == 'rule_based'
    assert result['metrics']['engine_used'] == 'fair'
    async with ws['factory']() as db:
        target = await db.get(Target, UUID(result['target_id']))
        assert 'maigret_plan' not in target.extra_data
        assert target.extra_data['pivot_frontier_mode'] == 'standard'
    await asyncio.sleep(0)
    run.assert_awaited_once()


@pytest.mark.asyncio
async def test_infostealer_survives_review_exposure_and_graph_without_machine_data(exposure_workspace):
    import json
    from app.models.entity import Entity
    from test_exposure_lens import _finalize
    ws = exposure_workspace
    ids = []
    async with ws['factory']() as db:
        for kind, value in [('email', 'lite@example.org'), ('username', 'lens_shared'),
                            ('email', 'not-attributed@example.net'), ('username', 'not_attributed')]:
            row = Entity(investigation_id=ws['investigation_id'], entity_type='infostealer',
                         value='fixture:' + value, platform='hudson_rock', source_tool='infostealer_checker',
                         metadata_info={'queried_by': kind, kind: value,
                           'computer_name': 'PRIVATE_MACHINE', 'ip': '192.0.2.15', 'malware_path': 'PRIVATE_PATH',
                           'provenance': {'origin': 'automatic', 'status': 'discovered'}})
            db.add(row)
            await db.flush()
            ids.append(str(row.id))
        await db.commit()
    await _finalize(ws)
    prefix = f"/api/v1/investigations/{ws['investigation_id']}"
    dataset = (await ws['client'].get(prefix + '/reviewed-footprint')).json()
    assert {item['entity_id'] for item in dataset['infostealers']} == set(ids[:2])
    exposure = await ws['client'].post(prefix + '/exposure/analyze')
    assert exposure.status_code == 200, exposure.text
    findings = [f for f in exposure.json()['findings'] if f['category'] == 'infostealer_exposure']
    assert len(findings) == 2
    result = await ws['client'].post(prefix + '/reconstruction/build')
    assert result.status_code == 200, result.text
    graph = result.json()['snapshot']['graph']
    nodes = {n['id']: n for n in graph['nodes']}
    edges = [e for e in graph['edges'] if e['type'] == 'EXPOSED_IN_INFOSTEALER']
    assert len(edges) == 2
    assert {nodes[e['source']]['kind'] for e in edges} == {'email', 'alias'}
    assert all(nodes[e['target']]['kind'] == 'infostealer' and e['evidence_refs'] for e in edges)
    serialized = json.dumps([dataset, exposure.json(), result.json()])
    for forbidden in ['PRIVATE_MACHINE', 'PRIVATE_PATH', '192.0.2.15', *ids[2:]]:
        assert forbidden not in serialized
