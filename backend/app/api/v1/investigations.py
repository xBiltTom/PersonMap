import asyncio
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.core.events import event_bus
from app.engine.orchestrator import orchestrator
from app.models.entity import Entity
from app.models.investigation import Investigation
from app.models.target import Target
from app.models.tool_execution import ToolExecution
from app.models.entity_observation import EntityObservation
from app.models.investigation_trace_event import InvestigationTraceEvent
from app.schemas.investigation import (
    InvestigationCreate,
    InvestigationDetail,
    InvestigationRead,
)
from app.schemas.trace import InvestigationTraceResponse

router = APIRouter()


@router.post("/investigations", response_model=InvestigationRead, status_code=201)
async def create_investigation(
    payload: InvestigationCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Creates and launches a new OSINT investigation for a person.
    At least ONE identifier is required in target (name, email, username, phone, or dni).
    """
    # 1. Create Target
    target = Target(
        full_name=payload.target.full_name,
        email=payload.target.email,
        username=payload.target.username,
        phone=payload.target.phone,
        dni=payload.target.dni,
        university=payload.target.university,
        description=payload.target.description,
        extra_data={
            **(payload.target.extra_data or {}),
            # Se guarda con el objetivo, no en una columna nueva: `extra_data`
            # es JSONB y ya existe, así que no hace falta migración para una
            # bandera que además pertenece al encargo concreto.
            "self_consent": bool(payload.self_consent),
        },
    )
    db.add(target)
    await db.flush()

    # 2. Create Investigation
    investigation = Investigation(
        target_id=target.id,
        strategy=payload.strategy,
        status="pending",
    )
    db.add(investigation)
    await db.commit()
    await db.refresh(investigation)
    await db.refresh(target)

    # 3. Launch background investigation task asynchronously
    asyncio.create_task(orchestrator.run_investigation(investigation.id))

    investigation.target = target
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
        )
    )
    result = await db.execute(stmt)
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigación no encontrada")
    return inv


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

    return {"status": "success", "message": "Investigación eliminada"}
