from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models.investigation import Investigation
from app.schemas.entity import EntityRead
from app.schemas.identity import CorrelationGroupRead

router = APIRouter()


@router.get("/investigations/{id}/correlation-groups", response_model=List[CorrelationGroupRead])
async def get_investigation_correlation_groups(
    id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns groups of observations connected by explicit evidence.
    """
    stmt = (
        select(Investigation)
        .where(Investigation.id == id)
        .options(
            selectinload(Investigation.correlation_groups),
            selectinload(Investigation.entities),
        )
    )
    result = await db.execute(stmt)
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigación no encontrada")

    entities_by_id = {str(e.id): e for e in inv.entities}
    response_groups: List[CorrelationGroupRead] = []

    for group in inv.correlation_groups:
        group_entities = [
            EntityRead.model_validate(entities_by_id[eid])
            for eid in group.entity_ids
            if eid in entities_by_id
        ]
        response_groups.append(
            CorrelationGroupRead(
                id=group.id,
                investigation_id=group.investigation_id,
                label=group.label,
                entity_ids=group.entity_ids,
                summary=group.summary,
                evidence=group.evidence or {},
                entities=group_entities,
            )
        )

    return response_groups
