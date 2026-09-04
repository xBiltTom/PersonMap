"""
Agrupación de hallazgos en clusters de identidad.

La versión anterior no agrupaba: partía las entidades en tres cajas fijas según
su confianza (>=0.70, >=0.40, resto) e ignoraba por completo tanto las aristas
de `Relationship` como los pares correlacionados por avatar. Dos perfiles unidos
por evidencia directa podían acabar en cajas distintas si sus puntuaciones caían
a distinto lado del umbral.

Aquí se hace agrupación real con **union-find** sobre las aristas de evidencia:
si A está unido a B y B a C, los tres forman una identidad, aunque A y C no
compartan ninguna señal entre sí. Es el enfoque de `clawithme`, señalado en el
análisis del estado del arte como el más cercano a la visión del proyecto.
"""

from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.identity.avatar_hasher import avatar_hasher
from app.models.entity import Entity
from app.models.identity_cluster import IdentityCluster
from app.models.relationship import Relationship
from app.models.target import Target

# Tipos de relación que constituyen evidencia de "misma persona" y por tanto
# unen componentes. `same_username` NO está: dos cuentas con el mismo alias
# pueden ser homónimos, que es justamente el caso que el sistema debe separar.
IDENTITY_EDGES = {"uses_email", "linked_to", "same_avatar"}


class UnionFind:
    """Estructura de conjuntos disjuntos con compresión de caminos."""

    def __init__(self, items: Iterable[str]) -> None:
        self._parent: Dict[str, str] = {i: i for i in items}

    def find(self, item: str) -> str:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        # Compresión: acorta el camino para las consultas siguientes.
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, a: str, b: str) -> None:
        if a in self._parent and b in self._parent:
            root_a, root_b = self.find(a), self.find(b)
            if root_a != root_b:
                self._parent[root_b] = root_a

    def groups(self) -> Dict[str, List[str]]:
        out: Dict[str, List[str]] = {}
        for item in self._parent:
            out.setdefault(self.find(item), []).append(item)
        return out


def _plural(count: int, singular: str, plural: str) -> str:
    """
    Concuerda el sustantivo con la cifra.

    Estos textos se muestran en la pantalla de reconstrucción de identidad, que
    es una de las que se recorren en la sustentación. Un "1 hallazgos" delata
    descuido justo donde el sistema está afirmando algo sobre una persona.
    """
    return f"{count} {singular if count == 1 else plural}"


class IdentityResolver:
    """Resuelve qué hallazgos pertenecen a la misma identidad."""

    CONFIRMED_THRESHOLD = 0.70
    PROBABLE_THRESHOLD = 0.40

    async def resolve_clusters(
        self,
        investigation_id: Any,
        entities: List[Entity],
        target: Target,
        relationships: Optional[List[Relationship]] = None,
    ) -> List[IdentityCluster]:
        if not entities:
            return []

        avatar_correlations = await self._correlate_avatars(entities)

        # 1. Union-find sobre la evidencia de identidad disponible.
        by_id = {str(e.id): e for e in entities}
        uf = UnionFind(by_id.keys())
        edges: List[Tuple[str, str, str]] = []

        for rel in relationships or []:
            if rel.relation_type in IDENTITY_EDGES:
                a, b = str(rel.source_entity_id), str(rel.target_entity_id)
                uf.union(a, b)
                edges.append((a, b, rel.relation_type))

        for corr in avatar_correlations:
            a, b = corr["entity_a_id"], corr["entity_b_id"]
            uf.union(a, b)
            edges.append((a, b, "same_avatar"))

        # 2. Cada componente hereda la mejor evidencia de sus miembros: si una
        #    sola cuenta del grupo está probada, arrastra a las que están unidas
        #    a ella por evidencia directa. Eso es lo que aporta el clustering
        #    frente a clasificar cada entidad por separado.
        components = uf.groups()
        component_score: Dict[str, float] = {}
        for root, members in components.items():
            component_score[root] = max(self._attribution(by_id[m]) for m in members)

        confirmed: List[Entity] = []
        probable: List[Entity] = []
        discarded: List[Entity] = []

        for root, members in components.items():
            score = component_score[root]
            for member_id in members:
                entity = by_id[member_id]
                # La verificación manual del analista manda sobre el modelo.
                if entity.verified or score >= self.CONFIRMED_THRESHOLD:
                    confirmed.append(entity)
                elif score >= self.PROBABLE_THRESHOLD:
                    probable.append(entity)
                else:
                    discarded.append(entity)

        clusters: List[IdentityCluster] = []
        linked_components = {r: m for r, m in components.items() if len(m) > 1}

        if confirmed:
            clusters.append(
                self._build_cluster(
                    investigation_id,
                    label="Identidad Principal (Confirmada / Alta Certeza)",
                    entities=confirmed,
                    status="confirmed",
                    reasoning=self._confirmed_reasoning(
                        confirmed, linked_components, avatar_correlations
                    ),
                    extra={
                        "avatar_correlations": avatar_correlations,
                        "linked_components": len(linked_components),
                        "evidence_edges": [
                            {"source": a, "target": b, "relation": r} for a, b, r in edges
                        ],
                    },
                )
            )

        if probable:
            clusters.append(
                self._build_cluster(
                    investigation_id,
                    label="Perfiles Probables (Requieren Verificación Manual)",
                    entities=probable,
                    status="probable",
                    reasoning=(
                        f"{_plural(len(probable), 'perfil', 'perfiles')} con evidencia parcial: "
                        f"la probabilidad de "
                        f"atribución queda entre {self.PROBABLE_THRESHOLD:.0%} y "
                        f"{self.CONFIRMED_THRESHOLD:.0%}. Conviene confirmarlos o descartarlos a mano."
                    ),
                )
            )

        if discarded:
            clusters.append(
                self._build_cluster(
                    investigation_id,
                    label="Posibles Homónimos Descartados",
                    entities=discarded,
                    status="homonym_discarded",
                    reasoning=(
                        f"{_plural(len(discarded), 'hallazgo', 'hallazgos')} sin evidencia "
                        f"suficiente de pertenecer al "
                        f"objetivo. Coincidir en un alias no basta: puede tratarse de otra "
                        f"persona que registró el mismo nombre de usuario."
                    ),
                )
            )

        return clusters

    # -- Interno -----------------------------------------------------------

    async def _correlate_avatars(self, entities: List[Entity]) -> List[Dict[str, Any]]:
        try:
            correlations = await avatar_hasher.correlate_entity_avatars(entities)
        except Exception:
            return []

        # Se marca la entidad, pero SIN el antiguo `confidence = max(conf, 0.99)`.
        # Aquel atajo saltaba por encima del modelo probabilístico: dos avatares
        # por defecto idénticos (la silueta genérica de Gravatar, por ejemplo)
        # bastaban para declarar "identidad confirmada" a dos personas distintas.
        # Ahora la correlación entra como una señal más del Fellegi-Sunter y como
        # arista que une componentes.
        matched = {c["entity_a_id"] for c in correlations} | {
            c["entity_b_id"] for c in correlations
        }
        for entity in entities:
            if str(entity.id) in matched:
                entity.metadata_info = {**(entity.metadata_info or {}), "avatar_correlated": True}

        return correlations

    def _attribution(self, entity: Entity) -> float:
        """
        Probabilidad de que el hallazgo sea del objetivo.

        Usa `identity_score` (el modelo) y no `confidence` (que es el máximo con
        la certeza de detección de la herramienta). Agrupar por `confidence`
        hacía que la constante escrita a mano en cada tool decidiera los
        clusters, dejando al modelo probabilístico sin efecto real.
        """
        # Arbitraje por LLM (opcional y apagado por defecto): si un hallazgo de la
        # franja ambigua recibió veredicto, esa es la puntuación EFECTIVA para
        # agrupar. Se lee de los metadatos y no del propio `identity_score`
        # justamente para no contaminarlo: el score persistido sigue siendo la
        # salida pura del scorer, que es lo que miden el histograma y la curva de
        # calibración del artículo.
        arbitration = (entity.metadata_info or {}).get("llm_arbitration")
        if isinstance(arbitration, dict):
            applied = arbitration.get("applied_score")
            if isinstance(applied, (int, float)):
                return float(applied)

        if entity.identity_score is not None:
            return float(entity.identity_score)
        # Entidades anteriores a la separación de métricas.
        return float(entity.confidence or 0.0)

    def _confirmed_reasoning(
        self,
        confirmed: List[Entity],
        linked_components: Dict[str, List[str]],
        avatar_correlations: List[Dict[str, Any]],
    ) -> str:
        parts = [
            f"{_plural(len(confirmed), 'hallazgo atribuido', 'hallazgos atribuidos')} "
            f"al objetivo por el modelo "
            f"Fellegi-Sunter (probabilidad de atribución ≥ {self.CONFIRMED_THRESHOLD:.0%})."
        ]
        if linked_components:
            parts.append(
                f"{_plural(len(linked_components), 'grupo quedó unido', 'grupos quedaron unidos')} "
                f"por evidencia directa "
                f"(correo compartido, enlace explícito o avatar idéntico), de modo que la "
                f"certeza de un perfil se propaga a los que están conectados a él."
            )
        if avatar_correlations:
            parts.append(
                f"Se detectaron {_plural(len(avatar_correlations), 'coincidencia visual', 'coincidencias visuales')} de avatar "
                f"mediante hashing perceptual (dHash)."
            )
        return " ".join(parts)

    def _build_cluster(
        self,
        investigation_id: Any,
        *,
        label: str,
        entities: List[Entity],
        status: str,
        reasoning: str,
        extra: Optional[Dict[str, Any]] = None,
    ) -> IdentityCluster:
        scores = [self._attribution(e) for e in entities]
        breakdown: Dict[str, Any] = {
            "entities_count": len(entities),
            "status": status,
            # Estadísticos del cluster, útiles para el análisis agregado del
            # artículo y para dibujar la distribución en la interfaz.
            "attribution_min": round(min(scores), 3),
            "attribution_max": round(max(scores), 3),
            "attribution_mean": round(sum(scores) / len(scores), 3),
        }
        if extra:
            breakdown.update(extra)

        return IdentityCluster(
            investigation_id=investigation_id,
            label=label,
            confidence=round(sum(scores) / len(scores), 3),
            entity_ids=[str(e.id) for e in entities],
            reasoning=reasoning,
            scoring_breakdown=breakdown,
        )


identity_resolver = IdentityResolver()
