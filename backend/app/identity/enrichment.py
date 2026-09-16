"""Enriquecimiento de evidencia que no decide pertenencia de identidad."""

from typing import Any, Dict, List

from sqlalchemy.ext.asyncio import AsyncSession

from app.identity.avatar_hasher import avatar_hasher
from app.identity.avatar_harvest import harvest_avatar_urls
from app.models.entity import Entity
from app.models.relationship import Relationship

AVATAR_MAX_DISTANCE = 4


async def enrich_correlations(entities: List[Entity], db: AsyncSession) -> Dict[str, Any]:
    """Añade relaciones visuales observables sin puntuar ni atribuir entidades."""
    summary: Dict[str, Any] = {"avatars_harvested": 0, "avatar_relationships": 0}
    if not entities:
        return summary

    summary["avatars_harvested"] = await harvest_avatar_urls(entities)
    try:
        correlations = await avatar_hasher.correlate_entity_avatars(entities)
    except Exception:
        return summary

    for correlation in correlations:
        distance = int(correlation.get("hamming_distance", 65))
        if distance > AVATAR_MAX_DISTANCE:
            continue
        source_id = correlation.get("entity_a_id")
        target_id = correlation.get("entity_b_id")
        if not source_id or not target_id or source_id == target_id:
            continue
        db.add(
            Relationship(
                investigation_id=entities[0].investigation_id,
                source_entity_id=source_id,
                target_entity_id=target_id,
                relation_type="similar_avatar",
                supports_group=False,
                evidence={"hamming_distance": distance, "method": "dhash"},
            )
        )
        summary["avatar_relationships"] += 1

    await db.flush()
    return summary
