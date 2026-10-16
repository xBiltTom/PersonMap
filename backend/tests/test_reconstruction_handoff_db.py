"""Web → MCP → web handoff in a disposable schema, without backend LLM calls."""
import asyncio
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import SecretStr
from sqlalchemy import select

from test_exposure_lens import exposure_workspace, _finalize
from app.core.config import settings
from app.models.reconstruction_run import ReconstructionRequest
from app.schemas.reconstruction_handoff import McpReconstructionResult, McpReconstructionProgress
from app.services import reconstruction_handoff as handoff
from app.mcp import server
from test_mcp import mcp_app

pytestmark = pytest.mark.db


def payload(packet):
    posts = [dict(fact_id=post['post_id'], title='Publicación revisada', context='El texto contiene contexto público observado.',
        severity=None, status='not_analyzed', explanation='La fuente se registró, pero no fue posible completar la lectura en esta prueba.',
        limitations=['Cobertura parcial explícita.']) for post in packet['posts']]
    return McpReconstructionResult(summary=[dict(text='Reconstrucción parcial de las fuentes revisadas.', fact_ids=[posts[0]['fact_id']])],
        identity_portrait=[dict(text='Las cuentas fueron atribuidas durante la revisión del sujeto.',
            fact_ids=[posts[0]['fact_id']], caveat='No se infieren atributos personales.')], post_analyses=posts)


@pytest.mark.asyncio
async def test_web_request_mcp_claim_submit_and_poll_without_studio(exposure_workspace, monkeypatch):
    ws = exposure_workspace
    monkeypatch.setattr(settings, 'mcp_enabled', True)
    monkeypatch.setattr(settings, 'mcp_api_key', SecretStr('fixture-token'))
    monkeypatch.setattr(settings, 'reconstruction_ai_enabled', False)
    monkeypatch.setattr(settings, 'llm_api_key', None)
    async def forbidden(**kwargs):
        raise AssertionError('MCP must not invoke a backend LLM')
    import litellm
    monkeypatch.setattr(litellm, 'acompletion', forbidden)
    await _finalize(ws)
    route = f"/api/v1/investigations/{ws['investigation_id']}/reconstruction/mcp"
    first = await ws['client'].post(route)
    assert first.status_code == 200, first.text
    body = first.json()
    assert body['status'] == 'pending' and body['result'] is None
    assert body['id'] in body['command']
    assert (await ws['client'].post(route)).json()['id'] == body['id']
    request_id = __import__('uuid').UUID(body['id'])
    monkeypatch.setattr(server.workspace, 'session_factory', ws['factory'])
    packet = await server.get_reconstruction_request(request_id)
    assert packet['server_llm_called'] is False
    claim = await server.claim_reconstruction_request(request_id, 'Codex test', 'fixture/model')
    token = __import__('uuid').UUID(claim['claim_token'])
    await server.update_reconstruction_progress(request_id, token, McpReconstructionProgress(message='Leyendo fuentes.'))
    assert (await ws['client'].get(route)).json()['status'] == 'running'
    async with ws['factory']() as db:
        inventory = await handoff.post_media.inventory(db, ws['investigation_id'])
    published = await server.submit_reconstruction_result(request_id, token, payload(inventory))
    assert published['published_to_web'] is True
    final = (await ws['client'].get(route)).json()
    assert final['status'] == 'completed' and final['result']['snapshot']['analysis_provider'] == 'mcp'
    assert final['result']['snapshot']['content_analysis_status'] == 'partial'
    assert final['result']['snapshot']['narrative_model'] == 'fixture/model'
    assert 'claim_token' not in final
    # A transport retry is idempotent.
    assert (await server.submit_reconstruction_result(request_id, token, payload(inventory)))['published_to_web'] is True


@pytest.mark.asyncio
async def test_cancel_stale_and_duplicate_claims(exposure_workspace, monkeypatch):
    ws = exposure_workspace
    monkeypatch.setattr(settings, 'mcp_enabled', True)
    monkeypatch.setattr(settings, 'mcp_api_key', SecretStr('fixture-token'))
    await _finalize(ws)
    route = f"/api/v1/investigations/{ws['investigation_id']}/reconstruction/mcp"
    request = (await ws['client'].post(route)).json()
    request_id = __import__('uuid').UUID(request['id'])
    async with ws['factory']() as db:
        await handoff.claim_request(db, request_id, 'first')
    async with ws['factory']() as db:
        with pytest.raises(HTTPException):
            await handoff.claim_request(db, request_id, 'second')
    cancelled = await ws['client'].post(route + '/' + request['id'] + '/cancel')
    assert cancelled.json()['status'] == 'cancelled'
    fresh = (await ws['client'].post(route)).json()
    assert fresh['id'] != request['id']
    monkeypatch.setattr(settings, 'graph_max_post_nodes', 1)
    assert (await ws['client'].get(route)).json()['stale'] is True
    newest = (await ws['client'].post(route)).json()
    assert newest['id'] != fresh['id']
    async with ws['factory']() as db:
        old = (await db.scalars(select(ReconstructionRequest).where(ReconstructionRequest.id == __import__('uuid').UUID(fresh['id'])))).one()
        assert old.status == 'cancelled'


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_pending_handoff(exposure_workspace, monkeypatch):
    ws = exposure_workspace
    monkeypatch.setattr(settings, 'mcp_enabled', True)
    monkeypatch.setattr(settings, 'mcp_api_key', SecretStr('fixture-token'))
    await _finalize(ws)
    route = f"/api/v1/investigations/{ws['investigation_id']}/reconstruction/mcp"
    responses = await asyncio.gather(ws['client'].post(route), ws['client'].post(route))
    assert all(response.status_code == 200 for response in responses)
    assert responses[0].json()['id'] == responses[1].json()['id']


@pytest.mark.asyncio
async def test_native_mcp_protocol_publishes_to_the_web(exposure_workspace, mcp_app, monkeypatch):
    import httpx
    import json
    from uuid import UUID
    from test_mcp import rpc
    ws = exposure_workspace
    await _finalize(ws)
    monkeypatch.setattr(server.workspace, 'session_factory', ws['factory'])
    route = f"/api/v1/investigations/{ws['investigation_id']}/reconstruction/mcp"
    created = (await ws['client'].post(route)).json()
    async with ws['factory']() as db:
        inventory = await handoff.post_media.inventory(db, ws['investigation_id'])
    app, mcp = mcp_app
    async with mcp.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            await rpc(client, 'initialize', {'protocolVersion': '2025-11-25', 'capabilities': {},
                'clientInfo': {'name': 'handoff-test', 'version': '1'}})
            async def call(name, arguments):
                response = await rpc(client, 'tools/call', {'name': name, 'arguments': arguments})
                result = response.json()['result']
                assert not result.get('isError'), result
                return result.get('structuredContent') or json.loads(result['content'][0]['text'])
            request = await call('get_reconstruction_request', {'request_id': created['id']})
            assert request['server_llm_called'] is False
            claim = await call('claim_reconstruction_request', {'request_id': created['id'], 'client': 'Codex protocol'})
            result = await call('submit_reconstruction_result', {'request_id': created['id'],
                'claim_token': claim['claim_token'], 'result': payload(inventory).model_dump(mode='json')})
            assert result['published_to_web'] is True
    observed = (await ws['client'].get(route)).json()
    assert observed['status'] == 'completed' and observed['client'] == 'Codex protocol'
    assert observed['result']['snapshot']['analysis_provider'] == 'mcp'
