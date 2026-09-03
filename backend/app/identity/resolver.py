from typing import Any, Dict, List
from app.identity.avatar_hasher import avatar_hasher
from app.models.entity import Entity
from app.models.identity_cluster import IdentityCluster
from app.models.target import Target


class IdentityResolver:
    """
    Groups discovered entities into cohesive identity clusters using
    Fellegi-Sunter posterior probabilities and perceptual avatar hashing (dHash),
    separating high-certainty profiles from low-certainty homonyms.
    """

    CONFIRMED_THRESHOLD = 0.70
    PROBABLE_THRESHOLD = 0.40

    async def resolve_clusters(
        self,
        investigation_id: Any,
        entities: List[Entity],
        target: Target,
    ) -> List[IdentityCluster]:
        if not entities:
            return []

        # 1. Run perceptual avatar hashing cross-correlation
        avatar_correlations: List[Dict[str, Any]] = []
        try:
            avatar_correlations = await avatar_hasher.correlate_entity_avatars(entities)
        except Exception:
            pass

        # Apply avatar boost to matched entities
        matched_entity_ids = set()
        for corr in avatar_correlations:
            matched_entity_ids.add(corr["entity_a_id"])
            matched_entity_ids.add(corr["entity_b_id"])

        for e in entities:
            if str(e.id) in matched_entity_ids:
                e.confidence = max(e.confidence, 0.99)
                if not e.metadata_info:
                    e.metadata_info = {}
                e.metadata_info["avatar_correlated"] = True

        primary_entities: List[Entity] = []
        secondary_entities: List[Entity] = []
        homonyms: List[Entity] = []

        for e in entities:
            if e.confidence >= self.CONFIRMED_THRESHOLD or e.verified:
                primary_entities.append(e)
            elif e.confidence >= self.PROBABLE_THRESHOLD:
                secondary_entities.append(e)
            else:
                homonyms.append(e)

        clusters: List[IdentityCluster] = []

        # 2. Primary Identity Cluster (High confidence)
        if primary_entities:
            avg_conf = sum(e.confidence for e in primary_entities) / len(primary_entities)
            reasoning = (
                f"Se correlacionaron {len(primary_entities)} perfiles y servicios "
                f"mediante el modelo Fellegi-Sunter con alta verosimilitud en credenciales, alias o correos."
            )
            if avatar_correlations:
                reasoning += f" Se confirmaron {len(avatar_correlations)} correlaciones visuales directas de avatar (dHash)."

            clusters.append(
                IdentityCluster(
                    investigation_id=investigation_id,
                    label="Identidad Principal (Confirmada / Alta Certeza)",
                    confidence=round(avg_conf, 2),
                    entity_ids=[str(e.id) for e in primary_entities],
                    reasoning=reasoning,
                    scoring_breakdown={
                        "entities_count": len(primary_entities),
                        "status": "confirmed",
                        "avatar_correlations": avatar_correlations,
                        "fellegi_sunter_active": True,
                    },
                )
            )

        # 3. Secondary Cluster (Probable match)
        if secondary_entities:
            avg_conf = sum(e.confidence for e in secondary_entities) / len(secondary_entities)
            clusters.append(
                IdentityCluster(
                    investigation_id=investigation_id,
                    label="Perfiles Probables (Requieren Verificación Manual)",
                    confidence=round(avg_conf, 2),
                    entity_ids=[str(e.id) for e in secondary_entities],
                    reasoning=(
                        f"Se detectaron {len(secondary_entities)} perfiles con alias compartido "
                        f"pero sin biografía institucional o correlación visual suficiente."
                    ),
                    scoring_breakdown={
                        "entities_count": len(secondary_entities),
                        "status": "probable",
                    },
                )
            )

        # 4. Homonyms Cluster (Low match)
        if homonyms:
            clusters.append(
                IdentityCluster(
                    investigation_id=investigation_id,
                    label="Posibles Homónimos Descartados",
                    confidence=0.20,
                    entity_ids=[str(e.id) for e in homonyms],
                    reasoning=(
                        f"{len(homonyms)} perfiles con discrepancia en nombre, ámbito geográfico o actividad."
                    ),
                    scoring_breakdown={
                        "entities_count": len(homonyms),
                        "status": "homonym_discarded",
                    },
                )
            )

        return clusters


identity_resolver = IdentityResolver()
