from typing import List
from app.models.entity import Entity
from app.models.identity_cluster import IdentityCluster
from app.models.target import Target


class IdentityResolver:
    """
    Groups discovered entities into cohesive identity clusters, separating
    high-certainty profiles from low-certainty homonyms.
    """

    def resolve_clusters(
        self,
        investigation_id,
        entities: List[Entity],
        target: Target,
    ) -> List[IdentityCluster]:
        if not entities:
            return []

        primary_entities: List[Entity] = []
        secondary_entities: List[Entity] = []
        homonyms: List[Entity] = []

        for e in entities:
            if e.confidence >= 0.70 or e.verified:
                primary_entities.append(e)
            elif e.confidence >= 0.40:
                secondary_entities.append(e)
            else:
                homonyms.append(e)

        clusters: List[IdentityCluster] = []

        # 1. Primary Identity Cluster (High confidence)
        if primary_entities:
            avg_conf = sum(e.confidence for e in primary_entities) / len(primary_entities)
            clusters.append(
                IdentityCluster(
                    investigation_id=investigation_id,
                    label="Identidad Principal (Confirmada / Alta Certeza)",
                    confidence=round(avg_conf, 2),
                    entity_ids=[str(e.id) for e in primary_entities],
                    reasoning=(
                        f"Se correlacionaron {len(primary_entities)} perfiles y servicios "
                        f"con coincidencia verificable en nombre, alias o credenciales institucionales."
                    ),
                    scoring_breakdown={
                        "entities_count": len(primary_entities),
                        "status": "confirmed",
                    },
                )
            )

        # 2. Secondary Cluster (Probable match)
        if secondary_entities:
            avg_conf = sum(e.confidence for e in secondary_entities) / len(secondary_entities)
            clusters.append(
                IdentityCluster(
                    investigation_id=investigation_id,
                    label="Perfiles Probables (Requieren Verificación Manual)",
                    confidence=round(avg_conf, 2),
                    entity_ids=[str(e.id) for e in secondary_entities],
                    reasoning=(
                        f"Se encontraron {len(secondary_entities)} perfiles con alias idéntico "
                        f"pero sin biografía o enlaces cruzados confirmados."
                    ),
                    scoring_breakdown={
                        "entities_count": len(secondary_entities),
                        "status": "probable",
                    },
                )
            )

        # 3. Homonyms Cluster (Low match)
        if homonyms:
            clusters.append(
                IdentityCluster(
                    investigation_id=investigation_id,
                    label="Posibles Homónimos Descartados",
                    confidence=0.20,
                    entity_ids=[str(e.id) for e in homonyms],
                    reasoning=(
                        f"{len(homonyms)} perfiles detectados con discrepancias significativas "
                        f"en nombre, ubicación geográfica o actividad."
                    ),
                    scoring_breakdown={
                        "entities_count": len(homonyms),
                        "status": "homonym_discarded",
                    },
                )
            )

        return clusters


identity_resolver = IdentityResolver()
