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
    "discovered_from": {"stroke": "#38bdf8", "strokeDasharray": "2,7", "strokeWidth": 1},
    "observed_email": {"stroke": "#38bdf8", "strokeWidth": 2},
    "shares_declared_email": {"stroke": "#38bdf8", "strokeWidth": 2},
    "explicit_profile_link": {"stroke": "#a855f7", "strokeWidth": 2},
    "same_username": {"stroke": "#38bdf8", "strokeWidth": 2},
    "similar_avatar": {"stroke": "#38bdf8", "strokeWidth": 2},
    "same_name": {"stroke": "#3b82f6", "strokeWidth": 2},
    "mentions": {"stroke": "#06b6d4", "strokeWidth": 2},
    "same_owner": {"stroke": "#10b981", "strokeWidth": 2},
    "affiliation": {"stroke": "#cbd5e1", "strokeWidth": 1.5},
    "possible_location": {"stroke": "#f43f5e", "strokeWidth": 1.5},
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
        rel_type = "discovered_from"
        rel_label = None
        p_lower = (entity.platform or "").lower()
        v_lower = (entity.value or "").lower()
        t_lower = (entity.entity_type or "").lower()

        if t_lower == "email" or (target.email and target.email.lower() in v_lower):
            rel_type = "observed_email"
            rel_label = "correo observado"
        elif "gravatar" in p_lower or "avatar" in t_lower or (entity.metadata_info and entity.metadata_info.get("avatar_url")):
            rel_type = "similar_avatar"
            rel_label = "avatar relacionado"
        elif target.full_name and (target.full_name.lower() in (entity.display_name or "").lower()):
            rel_type = "same_name"
            rel_label = "mismo nombre"
        elif t_lower in ("document", "academic") or "pdf" in v_lower:
            rel_type = "mentions"
            rel_label = "menciona"
        elif t_lower == "domain" or "http" in v_lower:
            rel_type = "mentions"
            rel_label = "menciona"
        elif target.username and (target.username.lower() in v_lower or (entity.metadata_info and target.username.lower() in str(entity.metadata_info.get("username", "")).lower())):
            rel_type = "explicit_profile_link"
            rel_label = "enlaza a"

        edges.append(
            GraphEdge(
                id=f"source-{entity.id}",
                source=root_id,
                target=entity_id,
                relation_type=rel_type,
                label=rel_label,
                style=EDGE_STYLES.get(rel_type, EDGE_STYLES["discovered_from"]),
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
