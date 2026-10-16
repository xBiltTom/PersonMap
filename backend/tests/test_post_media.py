"""Public media parsing, native MCP image blocks and source provenance."""
import base64
import io
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from PIL import Image

from app.core.config import settings
from app.models.entity import Entity
from app.services import post_media
from app.services.verification_gate import _safe_content
from app.social.apify_adapter import _content
from app.social.media import actor_media, media_reference, public_media_url
from app.tools import http_client
from test_mcp import mcp_app, rpc

URL = 'https://scontent.example.cdninstagram.com/photo.jpg?oh=public-signature&oe=6789'
POST_URL = 'https://www.instagram.com/p/Fixture123/'


def png():
    out = io.BytesIO()
    Image.new('RGB', (400, 200), 'white').save(out, format='PNG')
    return out.getvalue()


def packet():
    media = {**media_reference(URL, 'instagram'), 'position': 1}
    return {'investigation_id': str(uuid4()), 'dataset_hash': 'a' * 64,
        'authorization': {'subject_consent': True}, 'coverage': 'reviewed_accounts',
        'posts': [{'post_id': 'content:fixture', 'url': POST_URL, 'platform': 'instagram',
            'account_entity_id': str(uuid4()), 'media': [media], 'media_count': 1, 'analysis_text': '',
            'visual_status': 'not_inspected'}]}


def test_signed_media_survive_adapter_and_review():
    row = {'id': '1', 'url': POST_URL, 'ownerUsername': 'fixture', 'displayUrl': URL,
        'images': [URL, 'https://scontent.example.cdninstagram.com/slide2.jpg?oh=second'],
        'childPosts': [{'displayUrl': URL}], 'caption': ''}
    content = _content('instagram', row, 'fixture')
    assert len(content['media']) == 2 and content['media'][0]['url'] == URL
    entity = Entity(id=uuid4(), entity_type='social_account', platform='instagram', value='https://instagram.com/fixture', metadata_info={})
    assert _safe_content([content], entity)[0]['media'] == content['media']
    assert media_reference(URL.replace('public-signature', 'renewed'), 'instagram')['id'] == content['media'][0]['id']


@pytest.mark.parametrize('url', ['http://scontent.example.cdninstagram.com/a.jpg',
    'https://cdninstagram.com.evil.test/a.jpg', 'https://127.0.0.1/a.jpg',
    'https://scontent.example.cdninstagram.com:8443/a.jpg',
    'https://user:pass@scontent.example.cdninstagram.com/a.jpg',
    'https://scontent.example.cdninstagram.com/a.jpg?access_token=secret'])
def test_unsafe_media_urls_rejected(url):
    assert public_media_url(url, 'instagram') is None


def test_video_cover_remains_a_thumbnail():
    assert actor_media('instagram', {'type': 'Video', 'displayUrl': URL})[0]['role'] == 'video_thumbnail'
    assert actor_media('youtube', {'thumbnailUrl': 'https://i.ytimg.com/vi/abcdefghijk/maxresdefault.jpg'})[0]['role'] == 'video_thumbnail'


def test_crop_and_pixel_limits(monkeypatch):
    encoded, meta = post_media.display_image(png(), [.5, 0, 1, 1])
    assert meta['delivered_dimensions'] == [200, 200] and meta['original_dimensions'] == [400, 200]
    assert Image.open(io.BytesIO(encoded)).format == 'JPEG'
    monkeypatch.setattr(settings, 'mcp_media_max_pixels', 100)
    with pytest.raises(post_media.MediaReadError, match='image_pixel_limit'):
        post_media.display_image(png())


@pytest.mark.asyncio
async def test_unsafe_redirect_never_fetched(monkeypatch):
    calls = []
    def respond(request):
        calls.append(request)
        assert 'authorization' not in request.headers
        return httpx.Response(302, headers={'location': 'http://127.0.0.1/private'})
    def client(**options):
        assert options['public_only'] and not options['follow_redirects']
        return httpx.AsyncClient(transport=httpx.MockTransport(respond))
    monkeypatch.setattr(http_client, 'build_client', client)
    with pytest.raises(post_media.MediaReadError, match='unsafe_redirect'):
        await post_media.download_image(URL, 'instagram')
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('status,mime,code', [(403, 'text/html', 'media_expired_or_unavailable'),
    (429, 'text/html', 'media_rate_limited'), (200, 'text/html', 'unsupported_image_type')])
async def test_download_gaps_are_explicit(monkeypatch, status, mime, code):
    monkeypatch.setattr(http_client, 'build_client', lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(status, content=b'not image', headers={'content-type': mime}))))
    with pytest.raises(post_media.MediaReadError, match=code) as error:
        await post_media.download_image(URL, 'instagram')
    assert 'public-signature' not in str(error.value)


@pytest.mark.asyncio
async def test_image_only_inventory_is_paginated_without_cdn_queries(monkeypatch):
    data = packet()
    data['posts'] *= 3
    monkeypatch.setattr(post_media, 'inventory', AsyncMock(return_value=data))
    result = await post_media.list_posts(None, uuid4(), limit=2)
    assert result['next_offset'] == 2 and len(result['posts']) == 2
    assert result['posts'][0]['analysis_text'] == '' and 'url' not in result['posts'][0]['media'][0]
    assert result['server_llm_called'] is False


@pytest.mark.asyncio
async def test_source_and_revision_checked_before_image_delivery(monkeypatch):
    data = packet()
    monkeypatch.setattr(post_media, 'inventory', AsyncMock(return_value=data))
    downloader = AsyncMock(return_value=png())
    monkeypatch.setattr(post_media, 'download_image', downloader)
    db = SimpleNamespace(rollback=AsyncMock())
    with pytest.raises(HTTPException) as stale:
        await post_media.read_images(db, uuid4(), 'content:fixture', expected_dataset_hash='b' * 64)
    assert stale.value.status_code == 409 and downloader.await_count == 0
    with pytest.raises(HTTPException):
        await post_media.read_images(db, uuid4(), 'content:fixture', media_ids=['wrong-post'])
    meta, images = await post_media.read_images(db, uuid4(), 'content:fixture', expected_dataset_hash='a' * 64)
    assert meta['media'][0]['status'] == 'ready' and len(meta['media'][0]['source_sha256']) == 64
    assert images[0][1] and 'public-signature' not in str(meta)


@pytest.mark.asyncio
async def test_mcp_delivers_actual_image_blocks(mcp_app, monkeypatch):
    from app.mcp.server import workspace
    data = packet()
    post = data['posts'][0]
    meta = {**data, 'post': post_media.public_post(post)}
    item = {'media_id': post['media'][0]['id'], 'position': 1, 'role': 'image'}
    @asynccontextmanager
    async def factory():
        yield object()
    monkeypatch.setattr(workspace, 'session_factory', factory)
    monkeypatch.setattr(post_media, 'read_images', AsyncMock(return_value=(meta, [(item, png())])))
    app, mcp = mcp_app
    async with mcp.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://127.0.0.1:8000') as client:
            await rpc(client, 'initialize', {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'vision-test', 'version': '1'}})
            result = (await rpc(client, 'tools/call', {'name': 'read_post_images', 'arguments': {
                'investigation_id': str(uuid4()), 'post_id': 'content:fixture'}})).json()['result']
            assert not result.get('isError')
            images = [item for item in result['content'] if item['type'] == 'image']
            assert len(images) == 1 and base64.b64decode(images[0]['data']) == png()
            assert result['structuredContent']['authorization']['subject_consent'] is True


@pytest.mark.asyncio
async def test_missing_consent_blocks_inventory(monkeypatch):
    from app.services.workspace import workspace
    inv = SimpleNamespace(target=SimpleNamespace(extra_data={'subject_consent': False}))
    monkeypatch.setattr(workspace, '_investigation', AsyncMock(return_value=inv))
    db = SimpleNamespace(scalars=AsyncMock())
    with pytest.raises(HTTPException) as error:
        await post_media.inventory(db, uuid4())
    assert error.value.status_code == 403 and db.scalars.await_count == 0


@pytest.mark.asyncio
async def test_recovery_only_reads_original_dataset_and_preserves_post_fields(monkeypatch):
    from copy import deepcopy
    from pydantic import SecretStr
    from app.services.workspace import workspace
    from app.social.apify_client import ApifyClient
    account_id, investigation_id = uuid4(), uuid4()
    source = {'provider': 'apify', 'actor': 'apify/instagram-scraper', 'dataset_id': 'dataset123'}
    stored = {'id': '1', 'url': POST_URL, 'text': 'Original reviewed caption', 'collection_source': source}
    entity = SimpleNamespace(id=account_id, platform='instagram', value='https://instagram.com/fixture',
        metadata_info={'username': 'fixture', 'public_content': [deepcopy(stored)]})
    inv = SimpleNamespace(id=investigation_id, execution_mode='internal', revision=0,
        target=SimpleNamespace(extra_data={'subject_consent': True}),
        metrics={'reviewed_footprint_dataset': {'social_content': [{**deepcopy(stored), 'account_entity_id': str(account_id)}]}})
    db = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(one_or_none=lambda: entity)),
        rollback=AsyncMock(), commit=AsyncMock())
    monkeypatch.setattr(workspace, '_investigation', AsyncMock(return_value=inv))
    monkeypatch.setattr(workspace, '_record_change', AsyncMock())
    monkeypatch.setattr(settings, 'apify_token', SecretStr('fixture-token'))
    requests = []
    async def dataset(api, client, method, path, **kwargs):
        requests.append((method, path))
        return [{'id': '1', 'url': POST_URL, 'ownerUsername': 'fixture', 'displayUrl': URL}]
    monkeypatch.setattr(ApifyClient, '_json', dataset)
    result = await post_media.refresh_references(db, investigation_id, account_id)
    assert requests == [('GET', '/datasets/dataset123/items')]
    assert result['paid_actor_runs'] == 0 and result['updated_posts'] == 1
    assert entity.metadata_info['public_content'][0]['text'] == 'Original reviewed caption'
    assert inv.metrics['reviewed_footprint_dataset']['social_content'][0]['media'][0]['url'] == URL
    assert inv.revision == 1 and db.commit.await_count == 1


@pytest.mark.asyncio
async def test_visual_note_validates_media_and_saves_interpretation(monkeypatch):
    from app.mcp.server import save_post_visual_analysis, workspace
    from app.schemas.visual_analysis import PostVisualAnalysis
    data = packet()
    media_id = data['posts'][0]['media'][0]['id']
    @asynccontextmanager
    async def factory():
        yield object()
    monkeypatch.setattr(workspace, 'session_factory', factory)
    monkeypatch.setattr(workspace, '_investigation', AsyncMock(return_value=SimpleNamespace(execution_mode='internal')))
    monkeypatch.setattr(post_media, 'inventory', AsyncMock(return_value=data))
    writer = AsyncMock(return_value={'id': str(uuid4())})
    monkeypatch.setattr(workspace, 'add_note', writer)
    analysis = PostVisualAnalysis(post_id='content:fixture', dataset_hash='a' * 64,
        summary='El afiche contiene un contexto académico legible que complementa su descripción.', severity='low',
        observations=[dict(media_id=media_id, kind='visible_text', region='Franja superior',
            observation='El afiche contiene el nombre visible de una universidad.', visible_text='Universidad Fixture',
            why_it_matters='Permite asociar el anuncio con un contexto institucional.',
            recommendation='Revisa si quieres mantener esta colaboración en tu perfil personal.')],
        inferences=['Podría existir un vínculo con esa comunidad.'], limitations=['El logo no demuestra matrícula ni asistencia.'])
    await save_post_visual_analysis(uuid4(), analysis)
    note = writer.call_args.args[1]
    assert note.evidence_urls == [POST_URL]
    assert note.details['authorship'] == 'client_reported_visual_interpretation'
    assert 'Inferencias condicionales' in note.content
    assert 'public-signature' not in str(note.model_dump())
    analysis.observations[0].media_id = 'b' * 64
    from mcp.server.fastmcp.exceptions import ToolError
    with pytest.raises(ToolError):
        await save_post_visual_analysis(uuid4(), analysis)
    assert writer.await_count == 1


@pytest.mark.asyncio
async def test_external_image_only_posts_keep_unverified_attribution(monkeypatch):
    from app.services.workspace import workspace
    account_id = uuid4()
    entity = Entity(id=account_id, entity_type='social_account', platform='instagram', value='https://instagram.com/fixture',
        metadata_info={'username': 'fixture', 'ownership': {'status': 'unverified'},
            'public_content': [{'id': '1', 'url': POST_URL, 'text': '', 'media': actor_media('instagram', {'displayUrl': URL})}]})
    inv = SimpleNamespace(target=SimpleNamespace(extra_data={'subject_consent': True}), metrics={})
    monkeypatch.setattr(workspace, '_investigation', AsyncMock(return_value=inv))
    db = SimpleNamespace(scalars=AsyncMock(return_value=SimpleNamespace(all=lambda: [entity])))
    result = await post_media.inventory(db, uuid4())
    assert len(result['posts']) == 1
    assert result['posts'][0]['media_count'] == 1 and result['posts'][0]['analysis_text'] == ''
    assert result['posts'][0]['attribution_status'] == 'unverified'
    assert result['authorization']['subject_consent'] is True
