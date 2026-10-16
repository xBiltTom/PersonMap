"""Persistence and preconditions; semantic builders only see reviewed contracts."""
import hashlib
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.exposure_run import ExposureRun
from app.models.reconstruction_run import ReconstructionRun
from app.reconstruction.builder import build_snapshot, RECONSTRUCTION_VERSION, GRAPH_VERSION
from app.reconstruction.registry import canonical
from app.schemas.reconstruction import DigitalFootprintReconstruction, ReconstructionReport
from app.services import exposure_lens


def reconstruction_config():
    return {key: getattr(settings, key) for key in (
        'reconstruction_max_timeline_items', 'graph_max_total_nodes', 'graph_max_post_nodes',
        'graph_max_document_nodes', 'graph_max_exposure_nodes',
    )} | {'evidence_policy': 'reviewed-typed-fields-and-minimized-exposure-v2',
         'ai_presentation': settings.reconstruction_ai_enabled,
         'presentation_model': settings.llm_model if settings.reconstruction_ai_enabled else None,
         'presentation_policy': 'existing-fact-ids-only-v1'}


def exposure_fingerprint(report):
    data = report.model_dump(mode='json', exclude={'cache_hit', 'stale', 'current_dataset_hash'})
    return hashlib.sha256(canonical(data).encode()).hexdigest()


def input_fingerprint(data_hash, exposure_hash, config):
    return hashlib.sha256(canonical(dict(dataset_hash=data_hash, exposure_hash=exposure_hash,
        reconstruction_version=RECONSTRUCTION_VERSION, graph_version=GRAPH_VERSION, config=config)).encode()).hexdigest()


async def _inputs(db, investigation_id, *, lock=False):
    # The shared gate can inspect candidates only to validate finalization; none
    # of its raw objects are passed to reconstruction or used to add facts.
    _, dataset, data_hash = await exposure_lens._current_dataset(db, investigation_id, lock=lock)
    _, _, current_config_hash = exposure_lens._analysis_config()
    matching = select(ExposureRun).where(
        ExposureRun.investigation_id == investigation_id,
        ExposureRun.dataset_hash == data_hash,
        ExposureRun.analysis_version == exposure_lens.ANALYSIS_VERSION,
        ExposureRun.config_hash == current_config_hash,
    )
    latest = (await db.scalars(matching)).first()
    if latest is None:
        any_report = (await db.scalars(select(ExposureRun.id).where(
            ExposureRun.investigation_id == investigation_id).limit(1))).first()
        if any_report is None:
            raise HTTPException(409, detail={'code': 'exposure_analysis_required',
                                           'message': 'Analiza Exposure Lens antes de reconstruir la huella.'})
        raise HTTPException(409, detail={'code': 'exposure_report_stale',
                                       'message': 'La huella o la configuración cambió. Reanaliza Exposure Lens.'})
    if latest.status not in {'completed', 'partial'}:
        raise HTTPException(409, detail={'code': 'exposure_analysis_required',
                                       'message': 'Completa o reintenta Exposure Lens antes de reconstruir.'})
    exposure = exposure_lens._report_from_run(latest)
    config = reconstruction_config()
    exposure_hash = exposure_fingerprint(exposure)
    input_hash = input_fingerprint(data_hash, exposure_hash, config)
    return dataset, exposure, data_hash, exposure_hash, input_hash, config


def _response(run, current_hash, *, cache_hit=False):
    stale = run.input_hash != current_hash
    return ReconstructionReport(
        investigation_id=str(run.investigation_id), status=run.status, stale=stale,
        input_hash=run.input_hash, current_input_hash=current_hash, cache_hit=cache_hit,
        # Historic snapshots must never be presented as current after a review,
        # exposure, version or limit change.
        snapshot=None if stale else DigitalFootprintReconstruction.model_validate(run.snapshot),
    )


async def get_reconstruction(db: AsyncSession, investigation_id: UUID):
    _, _, _, _, current_hash, _ = await _inputs(db, investigation_id)
    current = (await db.scalars(select(ReconstructionRun).where(
        ReconstructionRun.investigation_id == investigation_id, ReconstructionRun.input_hash == current_hash))).first()
    if current:
        return _response(current, current_hash)
    run = (await db.scalars(select(ReconstructionRun).where(ReconstructionRun.investigation_id == investigation_id)
        .order_by(ReconstructionRun.completed_at.desc(), ReconstructionRun.id.desc()).limit(1))).first()
    if run is None:
        return ReconstructionReport(investigation_id=str(investigation_id), current_input_hash=current_hash)
    return _response(run, current_hash)


async def build_reconstruction(db: AsyncSession, investigation_id: UUID):
    try:
        dataset, exposure, data_hash, exposure_hash, input_hash, config = await _inputs(db, investigation_id, lock=True)
        existing = (await db.scalars(select(ReconstructionRun).where(
            ReconstructionRun.investigation_id == investigation_id, ReconstructionRun.input_hash == input_hash))).first()
        retry_presentation = existing and settings.reconstruction_ai_enabled and (existing.snapshot or {}).get("narrative_status") == "fallback"
        if existing and not retry_presentation:
            response = _response(existing, input_hash, cache_hit=True)
            await db.commit()
            return response
        started_at = datetime.now(timezone.utc)
        snapshot = build_snapshot(dataset, exposure, investigation_id=str(investigation_id),
            data_hash=data_hash, exposure_hash=exposure_hash, input_hash=input_hash, config=config)
        from app.reconstruction.presentation import present_snapshot
        snapshot = await present_snapshot(snapshot)
        snapshot.generated_at = datetime.now(timezone.utc)
        if existing:
            existing.snapshot = snapshot.model_dump(mode='json')
            existing.completed_at = snapshot.generated_at
            await db.commit()
            return _response(existing, input_hash)
        # Facts/graph are local; optional presentation finishes before INSERT. The terminal
        # snapshot commits atomically; interruption leaves no persistent run.
        await db.execute(pg_insert(ReconstructionRun).values(
            investigation_id=investigation_id, dataset_hash=data_hash, exposure_hash=exposure_hash,
            input_hash=input_hash, analysis_version=RECONSTRUCTION_VERSION,
            status='partial' if snapshot.coverage == 'partial' else 'completed',
            snapshot=snapshot.model_dump(mode='json'), config=config,
            started_at=started_at, completed_at=snapshot.generated_at,
        ).on_conflict_do_nothing(constraint='uq_reconstruction_input'))
        run = (await db.scalars(select(ReconstructionRun).where(
            ReconstructionRun.investigation_id == investigation_id, ReconstructionRun.input_hash == input_hash))).one()
        response = _response(run, input_hash)
        await db.commit()
        return response
    except BaseException:
        await db.rollback()
        raise
