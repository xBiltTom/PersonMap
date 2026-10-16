"""Durable web ↔ MCP handoff. This path never calls a backend language model."""
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select

from app.core.config import settings
from app.models.reconstruction_run import ReconstructionRequest
from app.models.investigation import Investigation
from app.reconstruction.builder import build_snapshot, RECONSTRUCTION_VERSION, GRAPH_VERSION
from app.reconstruction.handoff_prompt import reconstruction_command, reconstruction_prompt
from app.reconstruction.registry import canonical, fingerprint
from app.reconstruction.semantic import grounded, safe_prose
from app.schemas.reconstruction import (DigitalFootprintReconstruction, EvidenceRef, NarrativeClaim,
    PostAssessment, PostRiskSignal, ReconstructionReport)
from app.schemas.reconstruction_handoff import ReconstructionRequestRead
from app.services import exposure_lens, post_media


def options():
    integrated = settings.reconstruction_ai_enabled and settings.ai_enabled
    mcp_enabled = bool(settings.mcp_enabled and settings.mcp_api_key and settings.mcp_api_key.get_secret_value().strip())
    return {'integrated': {'enabled': bool(integrated), 'model': settings.llm_model if integrated else None,
                'label': 'Google AI Studio' if (settings.llm_model or '').startswith('gemini/') else 'IA integrada',
                'reason': None if integrated else 'Configura RECONSTRUCTION_AI_ENABLED, LLM_MODEL y LLM_API_KEY en el backend.'},
            'mcp': {'enabled': mcp_enabled,
                'label': 'Codex por MCP', 'reason': None if mcp_enabled else
                'Configura el MCP del backend con personmap_mcp.py setup.'}}


async def _inputs(db, investigation_id, *, lock=False):
    inv, dataset, digest = await exposure_lens._current_dataset(db, investigation_id, lock=lock)
    if not post_media.consent_context(inv)['subject_consent']:
        raise HTTPException(403, detail={'code': 'subject_consent_required', 'message': 'Falta el consentimiento registrado del sujeto.'})
    from app.services.digital_reconstruction import reconstruction_config
    config = reconstruction_config() | {'provider': 'mcp', 'ai_presentation': False, 'presentation_model': None,
                                        'presentation_policy': 'mcp-authored-evidence-v1'}
    local_config, _, local_config_hash = exposure_lens._analysis_config(ai_enabled=False)
    config['local_exposure_config_hash'] = local_config_hash
    input_hash = hashlib.sha256(canonical({'dataset_hash': digest, 'config': config,
        'reconstruction_version': RECONSTRUCTION_VERSION, 'graph_version': GRAPH_VERSION}).encode()).hexdigest()
    return dataset, digest, input_hash, config, local_config


def _read(row, current_hash):
    stale = row.input_hash != current_hash
    result = None
    if row.status == 'completed' and row.result_snapshot and not stale:
        snapshot = DigitalFootprintReconstruction.model_validate(row.result_snapshot)
        result = ReconstructionReport(investigation_id=str(row.investigation_id),
            status='partial' if snapshot.coverage == 'partial' else 'completed', input_hash=row.input_hash,
            current_input_hash=current_hash, snapshot=snapshot)
    return ReconstructionRequestRead(id=row.id, investigation_id=row.investigation_id,
        status=row.status, stale=stale, input_hash=row.input_hash, dataset_hash=row.dataset_hash,
        client=row.client, model=row.model, progress=row.progress or {}, created_at=row.created_at,
        updated_at=row.updated_at, completed_at=row.completed_at,
        command=reconstruction_command(row.id), prompt=reconstruction_prompt(row.id), result=result)


async def latest_request(db, investigation_id):
    _, _, current_hash, _, _ = await _inputs(db, investigation_id)
    row = (await db.scalars(select(ReconstructionRequest).where(ReconstructionRequest.investigation_id == investigation_id)
        .order_by(ReconstructionRequest.created_at.desc(), ReconstructionRequest.id.desc()).limit(1))).first()
    return _read(row, current_hash) if row else None


async def request_reconstruction(db, investigation_id):
    if not options()['mcp']['enabled']:
        raise HTTPException(503, detail={'code': 'mcp_not_configured', 'message': 'El MCP no está configurado en el backend.'})
    dataset, digest, current_hash, config, local_config = await _inputs(db, investigation_id, lock=True)
    active = (await db.scalars(select(ReconstructionRequest).where(
        ReconstructionRequest.investigation_id == investigation_id,
        ReconstructionRequest.status.in_(['pending', 'running'])).with_for_update())).first()
    if active and active.input_hash == current_hash:
        await db.commit()
        return _read(active, current_hash)
    if active:
        active.status = 'cancelled'
        active.progress = {'message': 'La evidencia cambió; reemplazada por una solicitud actual.'}
        active.updated_at = datetime.now(timezone.utc)
        await db.flush()
    exposure = await exposure_lens._build_analysis(db, investigation_id, dataset, digest, local_config, None)
    exposure_hash = hashlib.sha256(canonical(exposure.model_dump(mode='json', exclude={
        'cache_hit', 'stale', 'current_dataset_hash', 'generated_at'})).encode()).hexdigest()
    snapshot = build_snapshot(dataset, exposure, investigation_id=str(investigation_id), data_hash=digest,
        exposure_hash=exposure_hash, input_hash=current_hash, config=config)
    snapshot.analysis_provider = 'mcp'
    now = datetime.now(timezone.utc)
    row = ReconstructionRequest(id=uuid4(), investigation_id=investigation_id, input_hash=current_hash,
        dataset_hash=digest, status='pending', base_snapshot=snapshot.model_dump(mode='json'),
        progress={'message': 'Esperando a que Codex tome la solicitud.', 'analyzed_posts': 0,
                  'total_posts': len(snapshot.post_assessments)}, created_at=now, updated_at=now)
    db.add(row)
    await db.commit()
    return _read(row, current_hash)


async def _request(db, request_id, *, lock=False):
    statement = select(ReconstructionRequest).where(ReconstructionRequest.id == request_id)
    if lock:
        # All mutations lock the dossier before its request, as creation/review
        # do. This prevents publication racing a review change or cancellation.
        parent_id = (await db.scalars(select(ReconstructionRequest.investigation_id).where(
            ReconstructionRequest.id == request_id))).first()
        if parent_id is None:
            raise HTTPException(404, 'Solicitud de reconstrucción no encontrada.')
        await db.execute(select(Investigation.id).where(Investigation.id == parent_id).with_for_update())
        statement = statement.with_for_update()
    row = (await db.scalars(statement)).first()
    if row is None:
        raise HTTPException(404, 'Solicitud de reconstrucción no encontrada.')
    return row


async def _current(db, row):
    _, _, current_hash, _, _ = await _inputs(db, row.investigation_id)
    if current_hash != row.input_hash:
        raise HTTPException(409, detail={'code': 'reconstruction_request_stale',
            'message': 'El contenido o la configuración cambió. Crea otra solicitud desde la web.'})
    return current_hash


async def cancel_request(db, investigation_id, request_id):
    row = await _request(db, request_id, lock=True)
    if row.investigation_id != investigation_id:
        raise HTTPException(404, 'Solicitud fuera de este expediente.')
    if row.status in {'pending', 'running'}:
        row.status = 'cancelled'
        row.updated_at = datetime.now(timezone.utc)
        row.progress = {**(row.progress or {}), 'message': 'Solicitud cancelada desde la web.'}
        await db.commit()
    _, _, current_hash, _, _ = await _inputs(db, investigation_id)
    return _read(row, current_hash)


async def request_packet(db, request_id):
    row = await _request(db, request_id)
    current_hash = await _current(db, row)
    base = DigitalFootprintReconstruction.model_validate(row.base_snapshot)
    identity = [fact.model_dump(mode='json') for fact in base.facts if fact.kind not in {'post', 'repository'}]
    return {'request': _read(row, current_hash).model_dump(mode='json'),
        'authorization': (await post_media.inventory(db, row.investigation_id))['authorization'],
        'identity_facts': identity, 'post_count': len(base.post_assessments),
        'evidence': {key: value.model_dump(mode='json') for key, value in base.evidence.items()
                     if any(key in fact['evidence_refs'] for fact in identity)},
        'workflow': {'list_posts': 'list_public_posts', 'read_images': 'read_post_images',
                     'claim': 'claim_reconstruction_request', 'progress': 'update_reconstruction_progress',
                     'complete': 'submit_reconstruction_result'},
        'result_rules': [
            'Submit exactly one post_analyses item for every post_id returned by list_public_posts; paginate all posts.',
            'Only existing fact IDs may be used. Text evidence excerpts must be exact quotations of analysis_text.',
            'Image evidence requires an available media_id, region, and inclusion in inspected_media_ids; it is client-reported interpretation.',
            'Use local IDs for new evidence and cite them in signal.evidence_refs. Existing evidence IDs are also allowed.',
            'Claims need fact_ids; CORRELATED requires at least two facts. Do not infer ownership from coauthoring or faces.',
            'Never return claim_token in prose. Failed images and uninspected media must be declared as limitations.',
            'A successful submit atomically publishes the result to the waiting web UI. No backend LLM is called.'],
        'server_llm_called': False}


async def claim_request(db, request_id, client, model=None):
    row = await _request(db, request_id, lock=True)
    await _current(db, row)
    if row.status != 'pending':
        raise HTTPException(409, f'La solicitud está {row.status}; no se puede tomar de nuevo.')
    row.status, row.client, row.model, row.claim_token = 'running', client, model, uuid4()
    row.updated_at = datetime.now(timezone.utc)
    row.progress = {**(row.progress or {}), 'message': f'{client} está analizando la huella.'}
    await db.commit()
    return {'request_id': str(row.id), 'investigation_id': str(row.investigation_id),
            'claim_token': str(row.claim_token), 'dataset_hash': row.dataset_hash, 'status': row.status}


def require_claim(row, claim_token):
    if row.status != 'running' or row.claim_token != claim_token:
        raise HTTPException(409, 'La solicitud no está activa para este claim_token.')


async def update_progress(db, request_id, claim_token, progress):
    row = await _request(db, request_id, lock=True)
    require_claim(row, claim_token)
    current_hash = await _current(db, row)
    base = DigitalFootprintReconstruction.model_validate(row.base_snapshot)
    supplied = set(progress.analyzed_post_ids)
    if not supplied <= {item.fact_id for item in base.post_assessments}:
        raise HTTPException(422, 'El progreso contiene publicaciones ajenas a la solicitud.')
    row.progress = {'message': progress.message, 'analyzed_posts': len(supplied),
        'total_posts': len(base.post_assessments)}
    row.updated_at = datetime.now(timezone.utc)
    if progress.failed:
        row.status = 'failed'
    await db.commit()
    return _read(row, current_hash)


def assemble_result(row, payload, inventory):
    """Validate references/coverage and overlay authored analysis onto immutable facts."""
    snapshot = DigitalFootprintReconstruction.model_validate(row.base_snapshot)
    facts = {fact.id: fact for fact in snapshot.facts}
    posts = {post['post_id']: post for post in inventory['posts']}
    required = {item.fact_id for item in snapshot.post_assessments}
    provided = [post.fact_id for post in payload.post_analyses]
    if len(provided) != len(set(provided)) or set(provided) != required:
        raise HTTPException(422, 'Entrega un análisis por cada publicación de la solicitud, sin duplicados ni omisiones.')
    available_media = {media['id'] for post in posts.values() for media in post['media']}
    inspected = set(payload.inspected_media_ids)
    if not inspected <= available_media:
        raise HTTPException(422, 'Hay medios inspeccionados ajenos al conjunto actual.')
    refs = {key: key for key in snapshot.evidence}
    new_ids = set()
    for item in payload.evidence:
        if item.id in refs or item.id in new_ids or item.fact_id not in posts:
            raise HTTPException(422, 'ID de evidencia duplicado o publicación desconocida.')
        new_ids.add(item.id)
        post = posts[item.fact_id]
        if item.media_id:
            if item.media_id not in {media['id'] for media in post['media']} or item.media_id not in inspected or not item.region:
                raise HTTPException(422, 'La evidencia visual necesita un medio inspeccionado de ese post y su región.')
            source_type = 'mcp_visual_observation'
            excerpt = f'[{item.media_id[:12]} · {item.region}] {item.excerpt}'[:280]
        else:
            if not grounded(item.excerpt, post['analysis_text']):
                raise HTTPException(422, 'Una cita de texto no existe en la publicación suministrada.')
            source_type, excerpt = 'mcp_text_evidence', item.excerpt
        key = fingerprint('evidence', canonical([str(row.id), item.model_dump(mode='json')]))
        refs[item.id] = key
        snapshot.evidence[key] = EvidenceRef(id=key, source_type=source_type, excerpt=excerpt,
            source_entity_ids=[post['account_entity_id']], source_content_ids=[item.fact_id],
            url=post['url'], platform=post['platform'])

    def resolve(keys, fact_ids):
        if any(key not in refs for key in keys):
            raise HTTPException(422, 'Se cita evidencia inexistente.')
        resolved = sorted({refs[key] for key in keys})
        allowed = {ref for fact_id in fact_ids for ref in facts[fact_id].evidence_refs}
        for key in resolved:
            if key not in allowed and not set(snapshot.evidence[key].source_content_ids).intersection(fact_ids):
                raise HTTPException(422, 'La evidencia citada no corresponde a esos hechos.')
        return resolved

    def claims(items):
        result = []
        for claim in items:
            if not set(claim.fact_ids) <= set(facts) or claim.basis == 'CORRELATED' and len(set(claim.fact_ids)) < 2:
                raise HTTPException(422, 'Una afirmación cita hechos inexistentes o una correlación sin dos fuentes.')
            result.append(NarrativeClaim(text=claim.text, fact_ids=list(dict.fromkeys(claim.fact_ids)),
                basis=claim.basis, caveat=claim.caveat, evidence_refs=resolve(claim.evidence_refs, claim.fact_ids)))
        return result

    assessments = []
    for post in payload.post_analyses:
        if (post.status == 'signals_detected') != bool(post.signals):
            raise HTTPException(422, 'El estado de la publicación debe coincidir con sus señales.')
        if post.status in {'not_analyzed', 'no_text'} and post.severity is not None:
            raise HTTPException(422, 'No asignes severidad a contenido no analizado o sin texto evaluable.')
        signals = [PostRiskSignal(category=signal.category, label=exposure_lens.CATEGORY_LABELS[signal.category],
            severity=signal.severity, observation=signal.observation, why_it_matters=signal.why_it_matters,
            recommendations=signal.recommendations, evidence_refs=resolve(signal.evidence_refs, [post.fact_id]),
            analysis_method='ai') for signal in post.signals]
        order = {'high': 3, 'medium': 2, 'low': 1, 'informational': 0}
        severity = max((signal.severity for signal in signals), key=order.get) if signals else post.severity
        assessments.append(PostAssessment(**post.model_dump(exclude={'signals', 'severity'}),
            severity=severity, signals=signals, analysis_method='mcp'))
    prose = ' '.join([claim.text + ' ' + (claim.caveat or '') for claim in [*payload.summary, *payload.identity_portrait]] +
        [post.title + ' ' + post.context + ' ' + post.explanation + ' ' + ' '.join([*post.recommendations, *post.limitations])
         + ' ' + ' '.join(signal.observation + ' ' + signal.why_it_matters + ' ' + ' '.join(signal.recommendations) for signal in post.signals)
         for post in payload.post_analyses])
    if not safe_prose(prose, {post['published_at'] for post in posts.values()}):
        raise HTTPException(422, 'El análisis debe omitir contactos completos, direcciones precisas, horarios y atributos sensibles.')
    order = {'high': 3, 'medium': 2, 'low': 1, 'informational': 0}
    snapshot.post_assessments = sorted(assessments, key=lambda item: (-order.get(item.severity, -1), -len(item.signals), item.fact_id))
    snapshot.summary, snapshot.identity_portrait = claims(payload.summary), claims(payload.identity_portrait)
    snapshot.narrative_highlights = []
    snapshot.analysis_provider = 'mcp'
    snapshot.narrative_method, snapshot.narrative_status, snapshot.narrative_model = 'ai_assisted', 'completed', row.model
    incomplete = any(post.status == 'not_analyzed' for post in assessments)
    snapshot.content_analysis_status = 'partial' if incomplete else 'completed'
    if available_media - inspected:
        snapshot.coverage_reasons.append('visual_media_not_inspected')
    if incomplete:
        snapshot.coverage_reasons.append('posts_not_analyzed')
    if snapshot.coverage_reasons:
        snapshot.coverage = 'partial'
    snapshot.generated_at = datetime.now(timezone.utc)
    return snapshot


async def submit_result(db, request_id, claim_token, payload):
    row = await _request(db, request_id, lock=True)
    # Idempotent retries cannot replace the published snapshot.
    if row.status == 'completed' and row.claim_token == claim_token:
        current_hash = await _current(db, row)
        return _read(row, current_hash)
    require_claim(row, claim_token)
    current_hash = await _current(db, row)
    inventory = await post_media.inventory(db, row.investigation_id)
    if inventory['dataset_hash'] != row.dataset_hash:
        raise HTTPException(409, 'El conjunto de publicaciones cambió durante la solicitud.')
    snapshot = assemble_result(row, payload, inventory)
    row.status, row.result_snapshot = 'completed', snapshot.model_dump(mode='json')
    row.updated_at = row.completed_at = snapshot.generated_at
    row.progress = {'message': 'Análisis de Codex recibido y publicado.',
        'analyzed_posts': sum(post.status != 'not_analyzed' for post in snapshot.post_assessments),
        'total_posts': len(snapshot.post_assessments)}
    await db.commit()
    return _read(row, current_hash)
