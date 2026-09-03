from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models.identity_cluster import IdentityCluster
from app.models.investigation import Investigation
from app.schemas.entity import EntityRead
from app.schemas.identity import IdentityClusterRead

router = APIRouter()


@router.get("/investigations/{id}/identity", response_model=List[IdentityClusterRead])
async def get_investigation_identity_clusters(
    id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Returns resolved identity clusters with reconstructed profiles and confidence percentages.
    """
    stmt = (
        select(Investigation)
        .where(Investigation.id == id)
        .options(
            selectinload(Investigation.identity_clusters),
            selectinload(Investigation.entities),
        )
    )
    result = await db.execute(stmt)
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigación no encontrada")

    entities_by_id = {str(e.id): e for e in inv.entities}
    response_clusters: List[IdentityClusterRead] = []

    for cluster in inv.identity_clusters:
        cluster_entities = [
            EntityRead.model_validate(entities_by_id[eid])
            for eid in cluster.entity_ids
            if eid in entities_by_id
        ]
        cluster_read = IdentityClusterRead(
            id=cluster.id,
            investigation_id=cluster.investigation_id,
            label=cluster.label,
            confidence=cluster.confidence,
            entity_ids=cluster.entity_ids,
            reasoning=cluster.reasoning,
            scoring_breakdown=cluster.scoring_breakdown or {},
            entities=cluster_entities,
        )
        response_clusters.append(cluster_read)

    return response_clusters
