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
from app.models.identity_cluster import IdentityCluster
from app.models.investigation import Investigation
from app.models.target import Target
from app.schemas.entity import EntityVerifyRequest
from app.schemas.investigation import (
    InvestigationCreate,
    InvestigationDetail,
    InvestigationRead,
)

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
            selectinload(Investigation.identity_clusters),
        )
    )
    result = await db.execute(stmt)
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigación no encontrada")
    return inv


@router.post("/investigations/{id}/verify-entity/{entity_id}")
async def verify_entity(
    id: UUID,
    entity_id: UUID,
    payload: EntityVerifyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Allows manual confirmation or rejection of a discovered entity."""
    stmt = select(Entity).where(Entity.id == entity_id, Entity.investigation_id == id)
    result = await db.execute(stmt)
    entity = result.scalar_one_or_none()
    if not entity:
        raise HTTPException(status_code=404, detail="Entidad no encontrada")

    entity.verified = payload.verified
    if payload.verification_notes:
        entity.verification_notes = payload.verification_notes
    if payload.verified:
        entity.confidence = 1.0

    await db.commit()
    return {"status": "success", "entity_id": str(entity_id), "verified": entity.verified}


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
