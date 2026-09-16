from typing import Dict
from uuid import UUID
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models.investigation import Investigation
from app.schemas.graph import GraphEdge, GraphNode, GraphNodeData, GraphNodePosition, GraphResponse

router = APIRouter()

EDGE_STYLES = {
    "discovered_from": {"stroke": "#3b82f6", "strokeDasharray": "2,7", "strokeWidth": 1},
    "shares_declared_email": {"stroke": "#34d399", "strokeWidth": 2.5},
    "explicit_profile_link": {"stroke": "#a855f7", "strokeWidth": 2.5},
    "same_username": {"stroke": "#f59e0b", "strokeDasharray": "5,5", "strokeWidth": 1.5},
    "similar_avatar": {"stroke": "#f97316", "strokeDasharray": "3,3", "strokeWidth": 1.5},
}


def _group_membership(investigation: Investigation) -> Dict[str, str]:
    return {
        entity_id: str(group.id)
        for group in investigation.correlation_groups
        for entity_id in group.entity_ids
    }


@router.get("/investigations/{id}/graph", response_model=GraphResponse)
async def get_investigation_graph(id: UUID, db: AsyncSession = Depends(get_db)):
    """Devuelve observaciones y evidencia, no atribuciones de identidad."""
    stmt = (
        select(Investigation)
        .where(Investigation.id == id)
        .options(
            selectinload(Investigation.target),
            selectinload(Investigation.entities),
            selectinload(Investigation.relationships),
            selectinload(Investigation.correlation_groups),
        )
    )
    investigation = (await db.execute(stmt)).scalar_one_or_none()
    if not investigation:
        raise HTTPException(status_code=404, detail="Investigación no encontrada")

    target = investigation.target
    root_id = f"target-{target.id}"
    root_label = target.full_name or target.username or target.email or "Identidad Objetivo"
    membership = _group_membership(investigation)
    nodes = [
        GraphNode(
            id=root_id,
            type="personRoot",
            position=GraphNodePosition(x=0, y=0),
            data=GraphNodeData(
                label=root_label,
                entity_type="target",
                value=root_label,
                display_name=target.full_name or target.username or "Identidad Objetivo",
                is_root=True,
                metadata_info={
                    "full_name": target.full_name,
                    "email": target.email,
                    "username": target.username,
                    "university": target.university,
                    "dni": target.dni,
                },
            ),
        )
    ]
    edges = []
    for index, entity in enumerate(investigation.entities):
        entity_id = f"ent-{entity.id}"
        nodes.append(
            GraphNode(
                id=entity_id,
                type="customEntity",
                position=GraphNodePosition(x=float(250 + index * 20), y=0),
                data=GraphNodeData(
                    label=entity.display_name or entity.value,
                    entity_type=entity.entity_type,
                    platform=entity.platform,
                    value=entity.value,
                    display_name=entity.display_name,
                    metadata_info=entity.metadata_info or {},
                    group_id=membership.get(str(entity.id)),
                ),
            )
        )
        edges.append(
            GraphEdge(
                id=f"source-{entity.id}",
                source=root_id,
                target=entity_id,
                relation_type="discovered_from",
                label=None,
                style=EDGE_STYLES["discovered_from"],
                evidence={"source_tool": entity.source_tool},
            )
        )

    for relationship in investigation.relationships:
        relation_type = relationship.relation_type
        edges.append(
            GraphEdge(
                id=f"rel-{relationship.id}",
                source=f"ent-{relationship.source_entity_id}",
                target=f"ent-{relationship.target_entity_id}",
                relation_type=relation_type,
                label=relation_type.replace("_", " "),
                style=EDGE_STYLES.get(relation_type, {"stroke": "#64748b", "strokeWidth": 1.5}),
                evidence=relationship.evidence or {},
                supports_group=relationship.supports_group,
            )
        )

    return GraphResponse(investigation_id=str(id), nodes=nodes, edges=edges)


@router.get("/investigations/{id}/graphml")
async def export_graphml(id: UUID, db: AsyncSession = Depends(get_db)):
    """Exporta el mismo grafo factual para Gephi, Cytoscape o NetworkX."""
    graph = await get_investigation_graph(id, db)
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
        '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
        '  <key id="type" for="node" attr.name="type" attr.type="string"/>',
        '  <key id="relation" for="edge" attr.name="relation" attr.type="string"/>',
        '  <graph id="G" edgedefault="undirected">',
    ]
    for node in graph.nodes:
        lines.extend(
            [
                f'    <node id="{escape(node.id)}">',
                f'      <data key="label">{escape(node.data.label)}</data>',
                f'      <data key="type">{escape(node.data.entity_type)}</data>',
                "    </node>",
            ]
        )
    for edge in graph.edges:
        lines.extend(
            [
                f'    <edge source="{escape(edge.source)}" target="{escape(edge.target)}">',
                f'      <data key="relation">{escape(edge.relation_type)}</data>',
                "    </edge>",
            ]
        )
    lines.extend(["  </graph>", "</graphml>"])
    return Response(
        content="\n".join(lines),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="person_map_{id}.graphml"'},
    )
