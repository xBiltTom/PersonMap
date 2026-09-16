"""Proyección de observaciones en grupos conectados por evidencia explícita."""

from typing import Any, Dict, Iterable, List

from app.models.correlation_group import CorrelationGroup
from app.models.entity import Entity
from app.models.relationship import Relationship

# Brechas e infostealers son registros ligados al identificador consultado. No
# representan cuentas ni se mezclan con los grupos de observaciones.
IDENTIFIER_BOUND_TYPES = {"breach", "infostealer"}


class UnionFind:
    def __init__(self, items: Iterable[str]) -> None:
        self._parent: Dict[str, str] = {item: item for item in items}

    def find(self, item: str) -> str:
        root = item
        while self._parent[root] != root:
            root = self._parent[root]
        while self._parent[item] != root:
            self._parent[item], item = root, self._parent[item]
        return root

    def union(self, left: str, right: str) -> None:
        if left in self._parent and right in self._parent:
            root_left, root_right = self.find(left), self.find(right)
            if root_left != root_right:
                self._parent[root_right] = root_left

    def groups(self) -> Dict[str, List[str]]:
        groups: Dict[str, List[str]] = {}
        for item in self._parent:
            groups.setdefault(self.find(item), []).append(item)
        return groups


class CorrelationResolver:
    """Materializa grupos visuales, sin determinar de quién son los datos."""

    async def resolve_groups(
        self,
        investigation_id: Any,
        entities: List[Entity],
        relationships: List[Relationship],
    ) -> List[CorrelationGroup]:
        correlatable = [entity for entity in entities if entity.entity_type not in IDENTIFIER_BOUND_TYPES]
        if not correlatable:
            return self._identifier_bound_group(investigation_id, entities)

        by_id = {str(entity.id): entity for entity in correlatable}
        union_find = UnionFind(by_id)
        evidence_by_component: Dict[str, List[dict]] = {}

        for relationship in relationships:
            if not relationship.supports_group:
                continue
            source = str(relationship.source_entity_id)
            target = str(relationship.target_entity_id)
            if source in by_id and target in by_id:
                union_find.union(source, target)

        groups = union_find.groups()
        materialized: List[CorrelationGroup] = []
        for number, (_, member_ids) in enumerate(
            sorted(groups.items(), key=lambda item: min(item[1])), start=1
        ):
            member_set = set(member_ids)
            group_edges = [
                {
                    "source_entity_id": str(relationship.source_entity_id),
                    "target_entity_id": str(relationship.target_entity_id),
                    "relation_type": relationship.relation_type,
                    "evidence": relationship.evidence or {},
                }
                for relationship in relationships
                if str(relationship.source_entity_id) in member_set
                and str(relationship.target_entity_id) in member_set
                and relationship.supports_group
            ]
            count = len(member_ids)
            summary = (
                "Observación aislada: no se detectó un vínculo explícito con otra observación."
                if count == 1
                else f"{count} observaciones conectadas por {len(group_edges)} evidencia(s) explícita(s)."
            )
            materialized.append(
                CorrelationGroup(
                    investigation_id=investigation_id,
                    label=f"Grupo {number:02d}",
                    entity_ids=sorted(member_ids),
                    summary=summary,
                    evidence={"edges": group_edges},
                )
            )

        materialized.extend(self._identifier_bound_group(investigation_id, entities))
        return materialized

    def _identifier_bound_group(
        self, investigation_id: Any, entities: List[Entity]
    ) -> List[CorrelationGroup]:
        bound = [entity for entity in entities if entity.entity_type in IDENTIFIER_BOUND_TYPES]
        if not bound:
            return []
        return [
            CorrelationGroup(
                investigation_id=investigation_id,
                label="Registros del identificador consultado",
                entity_ids=[str(entity.id) for entity in bound],
                summary="Registros obtenidos al consultar un identificador proporcionado; no forman una agrupación de cuentas.",
                evidence={"kind": "identifier_bound"},
            )
        ]


correlation_resolver = CorrelationResolver()
