"""External reconstruction preserves the registry and validates all authored evidence."""
from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from test_reconstruction_analysis import build
from reconstruction_fixture import fixture_dataset
from app.schemas.reconstruction_handoff import McpReconstructionResult
from app.services.reconstruction_handoff import assemble_result, require_claim
from app.reconstruction.handoff_prompt import reconstruction_command, reconstruction_prompt


def fixture():
    base = build(fixture_dataset())
    ids = [item.fact_id for item in base.post_assessments]
    row = SimpleNamespace(id=uuid4(), base_snapshot=base.model_dump(mode='json'), model='fixture/vision')
    inventory = {'posts': [{'post_id': key, 'analysis_text': 'Comunidad de la Universidad Fixture.',
        'account_entity_id': str(uuid4()), 'platform': 'instagram', 'url': f'https://example.org/post/{index}',
        'published_at': '2026-10-01', 'media': []} for index, key in enumerate(ids)]}
    evidence = [dict(id=f'e{index}', fact_id=key, excerpt='Universidad Fixture') for index, key in enumerate(ids)]
    posts = [dict(fact_id=key, title='Contexto académico público', context='El anuncio presenta una comunidad académica.',
        status='signals_detected', severity='low', explanation='El vínculo público permite relacionar el perfil con una comunidad académica.',
        signals=[dict(category='education_work_context', severity='low', observation='El texto menciona la Universidad Fixture.',
            why_it_matters='Permite conectar este anuncio con otros contextos públicos.',
            recommendations=['Revisa si quieres conservar esta colaboración pública.'], evidence_refs=[f'e{index}'])],
        recommendations=['Revisa el alcance público de esta colaboración.'], limitations=['No demuestra matrícula ni asistencia.'])
        for index, key in enumerate(ids)]
    claim = dict(text='Dos publicaciones comparten un contexto académico explícito.', fact_ids=ids,
        basis='CORRELATED', caveat='La colaboración no demuestra matrícula actual.', evidence_refs=['e0', 'e1'])
    payload = McpReconstructionResult(summary=[claim], identity_portrait=[claim], post_analyses=posts, evidence=evidence)
    return row, inventory, payload


def test_valid_submission_preserves_facts_graph_and_provenance():
    row, inventory, payload = fixture()
    before = deepcopy(row.base_snapshot)
    result = assemble_result(row, payload, inventory)
    assert result.analysis_provider == 'mcp'
    assert result.model_dump(mode='json')['facts'] == before['facts']
    assert result.model_dump(mode='json')['graph'] == before['graph']
    assert all(post.analysis_method == 'mcp' for post in result.post_assessments)
    assert all(ref in result.evidence for post in result.post_assessments for signal in post.signals for ref in signal.evidence_refs)
    assert result.narrative_model == 'fixture/vision'


@pytest.mark.parametrize('change', ['omit_post', 'duplicate_post', 'unknown_fact', 'invented_quote', 'foreign_evidence'])
def test_unsupported_submissions_are_rejected(change):
    row, inventory, payload = fixture()
    if change == 'omit_post': payload.post_analyses.pop()
    if change == 'duplicate_post': payload.post_analyses.append(payload.post_analyses[0])
    if change == 'unknown_fact': payload.identity_portrait[0].fact_ids = ['unknown']
    if change == 'invented_quote': payload.evidence[0].excerpt = 'This quote was invented'
    if change == 'foreign_evidence': payload.post_analyses[0].signals[0].evidence_refs = ['e1']
    with pytest.raises(HTTPException) as error:
        assemble_result(row, payload, inventory)
    assert error.value.status_code == 422


def test_visual_evidence_requires_inspected_asset_and_region():
    row, inventory, payload = fixture()
    media_id = 'a' * 64
    inventory['posts'][0]['media'] = [{'id': media_id}]
    payload.evidence[0].media_id = media_id
    payload.evidence[0].region = 'Franja superior'
    with pytest.raises(HTTPException):
        assemble_result(row, payload, inventory)
    payload.inspected_media_ids = [media_id]
    result = assemble_result(row, payload, inventory)
    assert any(e.source_type == 'mcp_visual_observation' for e in result.evidence.values())
    payload.evidence[0].region = None
    with pytest.raises(HTTPException):
        assemble_result(row, payload, inventory)


def test_uninspected_images_are_partial_coverage():
    row, inventory, payload = fixture()
    inventory['posts'][0]['media'] = [{'id': 'a' * 64}]
    result = assemble_result(row, payload, inventory)
    assert result.coverage == 'partial'
    assert 'visual_media_not_inspected' in result.coverage_reasons


def test_claim_token_and_cancelled_state_prevent_publication():
    token = uuid4()
    row = SimpleNamespace(status='running', claim_token=token)
    require_claim(row, token)
    with pytest.raises(HTTPException): require_claim(row, uuid4())
    row.status = 'cancelled'
    with pytest.raises(HTTPException): require_claim(row, token)


def test_command_only_contains_a_validated_request_id():
    request_id = uuid4()
    assert str(request_id) in reconstruction_command(request_id)
    assert '--reconstruction-request' in reconstruction_command(request_id)
    assert 'submit_reconstruction_result' in reconstruction_prompt(request_id)
    with pytest.raises(ValueError): reconstruction_command('invalid; shell-command')


def test_external_result_cannot_replace_registry_or_graph():
    _, _, payload = fixture()
    with pytest.raises(ValidationError):
        McpReconstructionResult.model_validate({**payload.model_dump(), 'graph': {'nodes': []}})


def test_codex_launcher_passes_the_request_prompt_and_keeps_credentials_out_of_args(monkeypatch):
    import os
    import runpy
    import shutil
    import sys
    from pathlib import Path
    request_id = uuid4()
    script = Path(__file__).resolve().parents[1] / 'scripts/personmap_mcp.py'
    monkeypatch.setenv('PERSONMAP_MCP_TOKEN', 'fixture-private-token')
    monkeypatch.setattr(sys, 'argv', [str(script), 'codex', '--reconstruction-request', str(request_id)])
    monkeypatch.syspath_prepend(str(script.parents[1]))
    monkeypatch.setattr(shutil, 'which', lambda name: '/fixture/codex')
    calls = []
    monkeypatch.setattr(os, 'execvpe', lambda executable, args, env: calls.append((executable, args, env)))
    runpy.run_path(str(script), run_name='__main__')
    executable, args, env = calls[0]
    assert executable == 'codex'
    assert str(request_id) in args[-1] and 'submit_reconstruction_result' in args[-1]
    assert '--reconstruction-request' not in args
    assert 'fixture-private-token' not in str(args)
    assert env['PERSONMAP_MCP_TOKEN'] == 'fixture-private-token'
