import asyncio
from datetime import datetime, timezone
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.events import event_bus
from app.engine.orchestrator import orchestrator
from app.engine.pivot_frontier import PivotFrontierResponse
from app.models.entity import Entity
from app.models.investigation import Investigation
from app.models.target import Target
from app.models.tool_execution import ToolExecution
from app.models.entity_observation import EntityObservation
from app.models.investigation_trace_event import InvestigationTraceEvent
from app.models.review_decision import ReviewDecision
from app.schemas.investigation import (
    InvestigationCreate,
    InvestigationDetail,
    InvestigationRead,
)
from app.schemas.footprint import DataProvenance
from app.schemas.review import (
    InvestigationReviewResponse,
    ReviewDecisionPatch,
    ReviewFinalizeResponse,
    ReviewedFootprintDataset,
)
from app.schemas.trace import InvestigationTraceResponse
from app.services.workspace import workspace
from app.services import verification_gate

router = APIRouter()


async def _review_investigation(id: UUID, db: AsyncSession, *, lock: bool = False):
    stmt = select(Investigation).where(Investigation.id == id).options(selectinload(Investigation.target))
    if lock:
        stmt = stmt.with_for_update()
    investigation = (await db.execute(stmt)).scalar_one_or_none()
    if investigation is None:
        raise HTTPException(404, "Investigación no encontrada")
    if (investigation.metrics or {}).get("acquisition_mode") != "fair":
        raise HTTPException(404, "La Verification Gate solo está disponible para investigaciones Fair")
    return investigation


def _require_fair_finished(investigation: Investigation):
    metrics = investigation.metrics or {}
    if (investigation.status != "completed" or investigation.completed_at is None
            or not isinstance(metrics.get("fair_snapshot"), dict)):
        raise HTTPException(409, "La adquisición Fair aún no terminó; puedes revisar resultados, pero todavía no finalizar la revisión")


def _decision_provenance(entity: Entity, decision: str) -> dict:
    metadata = dict(entity.metadata_info or {})
    raw = metadata.get("provenance") or {
        "origin": "automatic", "status": "discovered", "subject_asserted": False,
        "evidence_urls": metadata.get("evidence_urls", []), "matches_declared_identifier": False,
    }
    provenance = DataProvenance.model_validate(raw)
    # Reviewable findings are automatic observations. Keep that historical origin.
    return provenance.model_copy(update={"origin": "automatic", "status": decision,
        "subject_asserted": decision == "confirmed"}).model_dump(mode="json")


def _apply_human_decision(entity: Entity, decision: str, decided_at):
    metadata = dict(entity.metadata_info or {})
    metadata["provenance"] = _decision_provenance(entity, decision)
    if entity.entity_type == "social_account":
        ownership_status = {"confirmed": "subject_confirmed", "rejected": "subject_rejected",
                            "uncertain": "uncertain"}[decision]
        old = metadata.get("ownership") if isinstance(metadata.get("ownership"), dict) else {}
        metadata["ownership"] = {**old, "status": ownership_status, "needs_review": False,
                                 "decision_source": "verification_gate", "decided_at": decided_at.isoformat()}
        metadata["ownership_status"] = ownership_status
        metadata["ownership_review_required"] = False
    entity.metadata_info = metadata


@router.get("/investigations/{id}/review", response_model=InvestigationReviewResponse)
async def get_investigation_review(id: UUID, db: AsyncSession = Depends(get_db)):
    investigation = await _review_investigation(id, db)
    return await verification_gate.get_review_response(db, investigation, investigation.target)


@router.patch("/investigations/{id}/review/{candidate_id}", response_model=InvestigationReviewResponse)
async def decide_investigation_candidate(
    id: UUID,
    candidate_id: UUID,
    payload: ReviewDecisionPatch,
    db: AsyncSession = Depends(get_db),
):
    """Persist the subject's explicit decision for an existing server-side candidate."""
    investigation = await _review_investigation(id, db, lock=True)
    current_view = await verification_gate.get_review_response(db, investigation, investigation.target)
    if not any(candidate.id == candidate_id for candidate in current_view.candidates):
        raise HTTPException(404, "Candidato revisable no encontrado")

    entity = (await db.execute(select(Entity).where(Entity.id == candidate_id,
        Entity.investigation_id == id).with_for_update())).scalar_one_or_none()
    if entity is None:
        raise HTTPException(404, "Candidato revisable no encontrado")
    row = (await db.execute(select(ReviewDecision).where(ReviewDecision.investigation_id == id,
        ReviewDecision.entity_id == candidate_id).with_for_update())).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    changed = row is None or row.decision != payload.decision
    if row is None:
        row = ReviewDecision(investigation_id=id, entity_id=candidate_id, decision=payload.decision,
            decided_at=now, history=[{"decision": payload.decision, "decided_at": now.isoformat(),
                                      "source": "verification_gate"}])
        db.add(row)
    elif changed:
        history = list(row.history or [])
        history.append({"decision": payload.decision, "decided_at": now.isoformat(),
                        "source": "verification_gate"})
        row.decision = payload.decision
        row.decided_at = now
        row.history = history
    if changed:
        _apply_human_decision(entity, payload.decision, now)
        metrics = dict(investigation.metrics or {})
        gate = dict(metrics.get("verification_gate") or {})
        gate.update(version=1, status="in_progress", started_at=gate.get("started_at") or now.isoformat(),
                    finalized_at=None, reviewed_candidate_ids=[])
        metrics["verification_gate"] = gate
        metrics.pop("reviewed_footprint_dataset", None)
        investigation.metrics = metrics
        await db.commit()
    else:
        return current_view

    response = await verification_gate.get_review_response(db, investigation, investigation.target)
    await event_bus.publish(str(id), {"type": "verification_review_updated", "review_status": response.review_status,
        "counts": response.counts.model_dump(mode="json"), "candidate_id": str(candidate_id),
        "decision": payload.decision})
    return response


@router.post("/investigations/{id}/review/finalize", response_model=ReviewFinalizeResponse)
async def finalize_investigation_review(id: UUID, db: AsyncSession = Depends(get_db)):
    investigation = await _review_investigation(id, db, lock=True)
    _require_fair_finished(investigation)
    response = await verification_gate.get_review_response(db, investigation, investigation.target)
    now = datetime.now(timezone.utc)
    dataset = await verification_gate.build_dataset(db, investigation, investigation.target, response.candidates)
    dataset_json = dataset.model_dump(mode="json")
    metrics = dict(investigation.metrics or {})
    gate = dict(metrics.get("verification_gate") or {})
    gate.update(version=1, status="complete", started_at=gate.get("started_at") or now.isoformat(),
        finalized_at=now.isoformat(), reviewed_candidate_ids=[str(item.id) for item in response.candidates])
    metrics["verification_gate"] = gate
    metrics["reviewed_footprint_dataset"] = dataset_json
    investigation.metrics = metrics
    await db.commit()
    await event_bus.publish(str(id), {"type": "verification_review_finalized", "review_status": "complete",
        "counts": response.counts.model_dump(mode="json"), "reviewed_at": now.isoformat(),
        "dataset_version": 1})
    return ReviewFinalizeResponse(investigation_id=id, finalized_at=now, counts=response.counts)


@router.get("/investigations/{id}/reviewed-footprint", response_model=ReviewedFootprintDataset)
async def get_reviewed_footprint(id: UUID, db: AsyncSession = Depends(get_db)):
    investigation = await _review_investigation(id, db)
    metrics = investigation.metrics or {}
    gate = metrics.get("verification_gate") or {}
    raw_dataset = metrics.get("reviewed_footprint_dataset")
    if gate.get("status") != "complete" or not isinstance(raw_dataset, dict):
        raise HTTPException(409, detail={"code": "review_not_finalized", "message": "Finaliza la revisión para consultar la huella atribuida."})
    current = await verification_gate.get_review_response(db, investigation, investigation.target)
    reviewed_ids = {str(item) for item in gate.get("reviewed_candidate_ids", [])}
    if any(str(candidate.id) not in reviewed_ids for candidate in current.candidates):
        raise HTTPException(409, detail={"code": "review_not_finalized", "message": "Hay nuevos descubrimientos pendientes; finaliza de nuevo la revisión."})
    return ReviewedFootprintDataset.model_validate(raw_dataset)


@router.post("/investigations", response_model=InvestigationRead, status_code=201)
async def create_investigation(
    payload: InvestigationCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Creates and launches a new OSINT investigation for a person.
    At least ONE identifier is required in target (name, email, username, phone, or dni).
    """
    investigation = await workspace.create(payload, db)
    if payload.execution_mode == "internal":
        asyncio.create_task(orchestrator.run_investigation(investigation.id))
    return investigation


@router.get("/investigations", response_model=List[InvestigationRead])
async def list_investigations(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    """Returns the history of investigations ordered by newest first."""
    stmt = (
        select(Investigation)
        .options(selectinload(Investigation.target))
        .order_by(desc(Investigation.created_at))
        .limit(limit)
        .offset(offset)
    )
    result = await db.execute(stmt)
    return result.scalars().all()


@router.get("/investigations/{id}", response_model=InvestigationDetail)
async def get_investigation(
    id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Returns full investigation details including target, discovered entities, and identity clusters."""
    stmt = (
        select(Investigation)
        .where(Investigation.id == id)
        .options(
            selectinload(Investigation.target),
            selectinload(Investigation.entities),
            selectinload(Investigation.correlation_groups),
            selectinload(Investigation.analysis_notes),
            selectinload(Investigation.sessions),
        )
    )
    result = await db.execute(stmt)
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigación no encontrada")
    return inv


@router.get("/investigations/{id}/frontier", response_model=PivotFrontierResponse)
async def get_investigation_frontier(id: UUID, db: AsyncSession = Depends(get_db)):
    """Persisted investigation priorities and provenance, without identity claims."""
    inv = await db.get(Investigation, id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigación no encontrada")
    from app.engine.pivot_frontier import frontier_from_metrics
    return {"pivot_frontier": frontier_from_metrics(inv.metrics or {})}


@router.get("/investigations/{id}/trace", response_model=InvestigationTraceResponse)
async def get_investigation_trace(
    id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Trazabilidad persistida de ejecución; nunca se reconstruye desde relaciones del grafo."""
    investigation = await db.get(Investigation, id)
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigación no encontrada")

    executions = list(
        (await db.execute(
            select(ToolExecution)
            .where(ToolExecution.investigation_id == id)
            .order_by(ToolExecution.started_at, ToolExecution.id)
        )).scalars().all()
    )
    observations = list(
        (await db.execute(
            select(EntityObservation)
            .where(EntityObservation.investigation_id == id)
            .options(selectinload(EntityObservation.entity))
            .order_by(EntityObservation.observed_at, EntityObservation.id)
        )).scalars().all()
    )
    events = list(
        (await db.execute(
            select(InvestigationTraceEvent)
            .where(InvestigationTraceEvent.investigation_id == id)
            .order_by(InvestigationTraceEvent.created_at, InvestigationTraceEvent.id)
        )).scalars().all()
    )

    return InvestigationTraceResponse(
        investigation_id=id,
        available=bool(executions or observations or events),
        executions=executions,
        observations=observations,
        events=events,
    )

@router.delete("/investigations/{id}")
async def delete_investigation(
    id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Deletes an investigation and all related records."""
    stmt = select(Investigation).where(Investigation.id == id)
    result = await db.execute(stmt)
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigación no encontrada")

    await db.delete(inv)
    await db.commit()

    # El bus de eventos guarda el historial de logs en memoria; sin esto quedaría
    # retenido para una investigación que ya no existe.
    await event_bus.clear(str(id))
    await event_bus.publish("registry", {"type": "investigation_deleted", "investigation_id": str(id)})

    return {"status": "success", "message": "Investigación eliminada"}


@router.get("/sources/fair", response_model=dict)
async def fair_source_plan():
    """Inspect acquisition policy without starting tools or contacting providers."""
    from app.engine.fair_plan import FairPlan
    from app.tools.registry import tool_registry
    return FairPlan.configured().inspect(tool_registry)


@router.get("/investigations/{id}/fair", response_model=dict)
async def fair_acquisition_state(id: UUID, db: AsyncSession = Depends(get_db)):
    """Progress + discovery references for future review; no ownership decisions."""
    inv = await db.get(Investigation, id)
    if inv is None:
        raise HTTPException(404, "Investigación no encontrada")
    metrics = inv.metrics or {}
    if metrics.get("acquisition_mode") != "fair":
        raise HTTPException(404, "La investigación no usa adquisición Fair")
    history = event_bus.get_history(str(id))
    progress = next((event for event in reversed(history) if event.get("type") == "fair_progress"), None)
    snapshot = next((event["snapshot"] for event in reversed(history) if event.get("type") == "fair_snapshot"), None)
    recovery = next((event["findings"] for event in reversed(history) if event.get("type") == "fair_unpersisted_findings"), [])
    return {"version": 1, "progress": progress or metrics.get("fair_progress"),
            "snapshot": snapshot or metrics.get("fair_snapshot"), "unpersisted_findings": recovery}
