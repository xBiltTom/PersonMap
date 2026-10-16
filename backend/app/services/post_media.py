"""Public post inventory and bounded image delivery for the connected MCP agent."""
import asyncio
import hashlib
import io
import warnings
from datetime import datetime, timezone
from urllib.parse import urljoin

import httpx
from fastapi import HTTPException
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select

from app.core.config import settings
from app.models.entity import Entity
from app.reconstruction.registry import canonical, fingerprint
from app.reconstruction.semantic import clean_source
from app.services import exposure_lens, verification_gate
from app.social.media import sanitize_media, public_media_url
from app.tools import http_client


def consent_context(investigation):
    extra = investigation.target.extra_data or {}
    return {'subject_consent': extra.get('subject_consent') is True,
        'self_consent': extra.get('self_consent') is True,
        'source': 'investigation.target.extra_data',
        'scope': 'Audit the consenting subject’s public digital footprint for privacy awareness. '
                 'Account attribution and third-party identities remain separate evidence questions.'}


async def inventory(db, investigation_id):
    from app.services.workspace import workspace
    inv = await workspace._investigation(db, investigation_id)
    authorization = consent_context(inv)
    if not authorization['subject_consent']:
        raise HTTPException(403, detail={'code': 'subject_consent_required',
            'message': 'El expediente debe registrar el consentimiento explícito del sujeto.'})
    account_status = {}
    if (inv.metrics or {}).get('acquisition_mode') == 'fair':
        _, dataset, digest = await exposure_lens._current_dataset(db, investigation_id)
        posts = dataset.social_content
        account_status = {str(account.entity_id): account.ownership.get('status', 'unverified')
            for account in dataset.accounts if exposure_lens._is_attributed(account)}
        coverage = 'reviewed_accounts'
    else:
        entities = (await db.scalars(select(Entity).where(Entity.investigation_id == investigation_id,
            Entity.entity_type == 'social_account').order_by(Entity.id))).all()
        posts = []
        for entity in entities:
            meta = entity.metadata_info or {}
            owner = meta.get('ownership') if isinstance(meta.get('ownership'), dict) else {}
            provenance = meta.get('provenance') if isinstance(meta.get('provenance'), dict) else {}
            status = owner.get('status', 'unverified')
            if status in {'rejected', 'uncertain'} or provenance.get('status') in {'rejected', 'uncertain'}:
                continue
            account_status[str(entity.id)] = status
            posts.extend(verification_gate._safe_content(meta.get('public_content'), entity))
        digest = hashlib.sha256(canonical(posts).encode()).hexdigest()
        coverage = 'observed_accounts_attribution_explicit'
    result = {}
    for post in posts:
        if not isinstance(post, dict) or str(post.get('account_entity_id')) not in account_status:
            continue
        external = post.get('id') or post.get('url')
        if not external:
            continue
        parent = str(post['account_entity_id'])
        post_id = fingerprint('content', canonical(['entity:' + parent, str(external)]))
        media = sanitize_media(post.get('media'), post.get('account_platform'))
        body = ' '.join(post[key] for key in ('text', 'caption', 'title', 'description') if isinstance(post.get(key), str))
        result[post_id] = {'post_id': post_id, 'source_id': exposure_lens._stable_content_id(post),
            'account_entity_id': parent, 'platform': post.get('account_platform'), 'account': post.get('account_username'),
            'attribution_status': account_status[parent], 'url': post.get('url'),
            'published_at': exposure_lens._date_only(post.get('posted_at') or post.get('published_at') or post.get('timestamp')),
            'authorship_role': post.get('authorship_role') or 'publisher',
            'analysis_text': clean_source(body, 6000), 'text_truncated': len(body) > 6000,
            'media': media, 'media_count': len(media), 'visual_status': 'not_inspected' if media else 'no_media_reference',
            'video_status': 'thumbnail_only' if any(item['role'] == 'video_thumbnail' for item in media) else 'not_applicable'}
    return {'investigation_id': str(investigation_id), 'dataset_hash': digest, 'authorization': authorization,
            'coverage': coverage, 'posts': [result[key] for key in sorted(result)]}


def public_post(post):
    return {**post, 'media': [{key: value for key, value in item.items() if key != 'url'} for item in post['media']]}


async def list_posts(db, investigation_id, *, limit=20, offset=0):
    packet = await inventory(db, investigation_id)
    posts = packet.pop('posts')
    return {**packet, 'total_posts': len(posts), 'posts': [public_post(post) for post in posts[offset:offset + limit]],
        'next_offset': offset + limit if offset + limit < len(posts) else None,
        'server_llm_called': False, 'media_fetches': 0,
        'visual_analysis_workflow': 'Use read_post_images with post_id, selected media IDs and dataset_hash. '
            'Inspect returned images with your own vision model. Cite the canonical post URL and media ID. '
            'Save visual observations separately from inferences with save_post_visual_analysis.'}


class MediaReadError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


async def download_image(url, platform):
    current = public_media_url(url, platform)
    if not current:
        raise MediaReadError('unsupported_media_host')
    try:
        async with asyncio.timeout(25):
            async with http_client.build_client(timeout=12, follow_redirects=False, public_only=True,
                    max_retries=0, rotate_ua=False, trust_env=False) as client:
                for _ in range(4):
                    async with client.stream('GET', current, headers={'Accept': 'image/jpeg,image/png,image/webp'}) as response:
                        if response.status_code in {301, 302, 303, 307, 308}:
                            current = public_media_url(urljoin(current, response.headers.get('location', '')), platform)
                            if not current:
                                raise MediaReadError('unsafe_redirect')
                            continue
                        if response.status_code in {401, 403, 404, 410}:
                            raise MediaReadError('media_expired_or_unavailable')
                        if response.status_code == 429:
                            raise MediaReadError('media_rate_limited')
                        if response.status_code != 200:
                            raise MediaReadError('media_http_error')
                        mime = response.headers.get('content-type', '').split(';')[0].lower()
                        if mime not in {'image/jpeg', 'image/png', 'image/webp'}:
                            raise MediaReadError('unsupported_image_type')
                        size = response.headers.get('content-length')
                        if size and size.isdigit() and int(size) > settings.mcp_media_max_download_bytes:
                            raise MediaReadError('image_too_large')
                        body = bytearray()
                        async for chunk in response.aiter_bytes():
                            body.extend(chunk)
                            if len(body) > settings.mcp_media_max_download_bytes:
                                raise MediaReadError('image_too_large')
                        return bytes(body)
                raise MediaReadError('too_many_redirects')
    except (httpx.HTTPError, TimeoutError):
        raise MediaReadError('media_network_error') from None


def display_image(body, crop=None):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(body)) as original:
                if original.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise MediaReadError('unsupported_image_type')
                if original.width * original.height > settings.mcp_media_max_pixels:
                    raise MediaReadError('image_pixel_limit')
                source_size = [original.width, original.height]
                image = ImageOps.exif_transpose(original)
                if crop:
                    left, top, right, bottom = crop
                    if not 0 <= left < right <= 1 or not 0 <= top < bottom <= 1:
                        raise MediaReadError('invalid_crop')
                    image = image.crop((int(left * image.width), int(top * image.height),
                                        int(right * image.width), int(bottom * image.height)))
                    if image.width < 1 or image.height < 1:
                        raise MediaReadError('invalid_crop')
                image.thumbnail((settings.mcp_media_max_dimension, settings.mcp_media_max_dimension), Image.Resampling.LANCZOS)
                if image.mode in {'RGBA', 'LA'} or image.mode == 'P' and 'transparency' in image.info:
                    rgba = image.convert('RGBA')
                    background = Image.new('RGBA', rgba.size, 'white')
                    image = Image.alpha_composite(background, rgba).convert('RGB')
                else:
                    image = image.convert('RGB')
                for quality in (90, 80, 65):
                    output = io.BytesIO()
                    image.save(output, format='JPEG', quality=quality)
                    if output.tell() <= settings.mcp_media_max_output_bytes:
                        return output.getvalue(), {'original_dimensions': source_size, 'delivered_dimensions': list(image.size),
                            'crop': crop, 'metadata_stripped': True, 'image_transform': 'exif_oriented_resized_jpeg'}
                raise MediaReadError('image_output_limit')
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise MediaReadError('invalid_image') from None


async def read_images(db, investigation_id, post_id, *, media_ids=None, expected_dataset_hash=None, crop=None):
    packet = await inventory(db, investigation_id)
    if expected_dataset_hash and expected_dataset_hash != packet['dataset_hash']:
        raise HTTPException(409, detail={'code': 'post_dataset_changed', 'message': 'El contenido cambió; vuelve a listar los posts.'})
    post = next((post for post in packet['posts'] if post['post_id'] == post_id), None)
    if post is None:
        raise HTTPException(404, 'Publicación fuera del conjunto observado o revisado de este expediente.')
    available = {item['id']: item for item in post['media']}
    selected = list(dict.fromkeys(media_ids)) if media_ids else list(available)[:settings.mcp_media_max_images]
    if not 1 <= len(selected) <= settings.mcp_media_max_images or any(key not in available for key in selected):
        raise HTTPException(422, 'Selecciona IDs de medios disponibles dentro del límite por llamada.')
    # Release the read transaction before waiting for CDN requests.
    await db.rollback()
    semaphore = asyncio.Semaphore(2)

    async def read_one(key):
        media = available[key]
        try:
            async with semaphore:
                body = await download_image(media['url'], post['platform'])
                encoded, transform = await asyncio.to_thread(display_image, body, crop)
            return {'media_id': key, 'position': media['position'], 'role': media['role'], 'status': 'ready',
                'source_sha256': hashlib.sha256(body).hexdigest(), 'delivered_sha256': hashlib.sha256(encoded).hexdigest(),
                'retrieved_at': datetime.now(timezone.utc).isoformat(), **transform}, encoded
        except MediaReadError as error:
            return {'media_id': key, 'position': media['position'], 'role': media['role'], 'status': error.code}, None
    images = await asyncio.gather(*(read_one(key) for key in selected))
    return {'investigation_id': str(investigation_id), 'dataset_hash': packet['dataset_hash'],
        'authorization': packet['authorization'], 'post': public_post(post),
        'server_llm_called': False, 'media': [metadata for metadata, _ in images],
        'coverage': 'delivered_images_only', 'unrequested_media_count': len(available) - len(selected),
        'limitations': ['A video thumbnail is not an analysis of the full video or its audio.',
            'A collaborative post does not identify every person depicted or named.',
            'Images are resized; use a normalized crop for text that is too small.']}, images


async def refresh_references(db, investigation_id, account_entity_id, *, session_id=None, max_rows=100):
    """Recover public media URLs from recorded Apify datasets; never start an Actor."""
    from copy import deepcopy
    from app.services.workspace import workspace
    from app.social.apify_client import ApifyClient, ApifyError, identifier
    from app.social.apify_adapter import _content
    from app.social.capabilities import ACTORS, INSTAGRAM_POSTS
    from app.social.safety import public_url
    from app.tools.social_profiles import parse_social_profile
    inv = await workspace._investigation(db, investigation_id)
    if not consent_context(inv)['subject_consent']:
        raise HTTPException(403, detail={'code': 'subject_consent_required'})
    if inv.execution_mode == 'external':
        await workspace._active_session(db, inv, session_id)
    entity = (await db.scalars(select(Entity).where(Entity.id == account_entity_id,
        Entity.investigation_id == investigation_id, Entity.entity_type == 'social_account'))).one_or_none()
    if entity is None:
        raise HTTPException(404, 'Cuenta no encontrada en este expediente.')
    meta = deepcopy(entity.metadata_info or {})
    posts = meta.get('public_content', [])
    profile = parse_social_profile(entity.value)
    handle = meta.get('username') or (profile.username if profile else None)
    platform = entity.platform
    if platform not in ACTORS:
        raise HTTPException(422, 'Esta plataforma no tiene un contrato de recuperación de medios.')
    known_urls = {post.get('url') for post in posts if isinstance(post, dict) and post.get('url')}
    actors = {spec.actor for spec in ACTORS.values()} | {INSTAGRAM_POSTS.actor}
    sources = [post.get('collection_source') for post in posts if isinstance(post, dict)]
    sources.extend(meta.get('collection_sources', []))
    datasets = list(dict.fromkeys(source['dataset_id'] for source in sources if isinstance(source, dict)
        and source.get('provider') == 'apify' and source.get('actor') in actors and identifier(source.get('dataset_id'))))[:3]
    if not handle or not known_urls or not datasets:
        return {'updated_posts': 0, 'status': 'original_dataset_reference_missing', 'paid_actor_runs': 0}
    if not settings.apify_token:
        raise HTTPException(409, detail={'code': 'apify_not_configured'})
    await db.rollback()
    recovered, errors, rows_read, datasets_read = {}, [], 0, set()
    async with http_client.build_client(timeout=15, follow_redirects=False, public_only=True, max_retries=0,
        rotate_ua=False, headers={'Authorization': 'Bearer ' + settings.apify_token.get_secret_value()}) as client:
        api = ApifyClient()
        for dataset_id in datasets:
            offset = 0
            try:
                while rows_read < max_rows:
                    page_size = min(25, max_rows - rows_read)
                    rows = await api._json(client, 'GET', f'/datasets/{dataset_id}/items',
                        params={'clean': 'true', 'format': 'json', 'offset': offset, 'limit': page_size})
                    if not isinstance(rows, list):
                        raise ApifyError('dataset_schema_changed')
                    datasets_read.add(dataset_id)
                    rows_read += len(rows)
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        nested = row.get('latestPosts')
                        for candidate in nested[:100] if isinstance(nested, list) else [row]:
                            if not isinstance(candidate, dict) or public_url(candidate.get('url') or candidate.get('webVideoUrl')) not in known_urls:
                                continue
                            content = _content(platform, candidate, handle)
                            if content and content.get('media'):
                                recovered[content['url']] = content['media']
                    offset += len(rows)
                    if len(rows) < page_size:
                        break
            except ApifyError as error:
                errors.append(error.code)
    inv = await workspace._investigation(db, investigation_id, lock=True)
    if not consent_context(inv)['subject_consent']:
        raise HTTPException(403, detail={'code': 'subject_consent_required'})
    if inv.execution_mode == 'external':
        await workspace._active_session(db, inv, session_id)
    entity = (await db.scalars(select(Entity).where(Entity.id == account_entity_id,
        Entity.investigation_id == investigation_id))).one_or_none()
    if entity is None:
        raise HTTPException(404, 'La cuenta ya no existe en el expediente.')
    latest = deepcopy(entity.metadata_info or {})
    updated = 0
    for post in latest.get('public_content', []):
        if isinstance(post, dict) and post.get('url') in recovered:
            refs = recovered[post['url']]
            if post.get('media') != refs:
                post['media'] = refs
                updated += 1
    if updated:
        entity.metadata_info = latest
        # Enrich only already-reviewed posts, without adding posts or altering
        # attribution decisions. The dataset hash invalidates dependent reports.
        metrics = deepcopy(inv.metrics or {})
        reviewed = metrics.get('reviewed_footprint_dataset')
        if isinstance(reviewed, dict):
            for post in reviewed.get('social_content', []):
                if str(post.get('account_entity_id')) == str(account_entity_id) and post.get('url') in recovered:
                    post['media'] = recovered[post['url']]
            inv.metrics = metrics
        inv.revision += 1
        await workspace._record_change(db, inv, entities=[entity.id])
        await db.commit()
    return {'investigation_id': str(investigation_id), 'account_entity_id': str(account_entity_id),
        'updated_posts': updated, 'dataset_rows_read': rows_read, 'datasets_read': len(datasets_read),
        'errors': errors, 'status': 'updated' if updated else 'no_new_media_references',
        'paid_actor_runs': 0, 'dependent_reports_may_need_refresh': bool(updated)}
