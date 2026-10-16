from typing import Dict
import json
from uuid import UUID
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.identity.evidence import STRONG_EMAIL_ROLES, STRONG_PHONE_ROLES
from app.models.investigation import Investigation
from app.schemas.graph import GraphEdge, GraphNode, GraphNodeData, GraphNodePosition, GraphResponse

router = APIRouter()

EDGE_STYLES = {
    "target_email_match": {"stroke": "#38bdf8", "strokeWidth": 2},
    "target_phone_match": {"stroke": "#f59e0b", "strokeWidth": 2},
    "target_identifier_match": {"stroke": "#a855f7", "strokeWidth": 2},
    "target_context_match": {"stroke": "#64748b", "strokeDasharray": "3,5", "strokeWidth": 1},
    "registration_query": {"stroke": "#64748b", "strokeDasharray": "3,5", "strokeWidth": 1},
    "shares_email_and_username": {"stroke": "#38bdf8", "strokeWidth": 2.5},
    "email_lookup_association": {"stroke": "#38bdf8", "strokeDasharray": "3,5", "strokeWidth": 2},
    "shares_declared_phone": {"stroke": "#f59e0b", "strokeWidth": 2},
    "shared_orcid": {"stroke": "#a855f7", "strokeWidth": 2},
    "shared_gaia_id": {"stroke": "#a855f7", "strokeWidth": 2},
    "authored_work": {"stroke": "#a855f7", "strokeWidth": 1.5},
    "name_and_affiliation": {"stroke": "#64748b", "strokeDasharray": "3,5", "strokeWidth": 1},
    "discovered_from": {"stroke": "#38bdf8", "strokeDasharray": "2,7", "strokeWidth": 1},
    "publishes_phone": {"stroke": "#f59e0b", "strokeWidth": 2},
    "mentions_phone": {"stroke": "#f59e0b", "strokeDasharray": "3,5", "strokeWidth": 1.5},
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

    return await build_evidence_graph(investigation)


async def build_evidence_graph(investigation):
    from app.identity.projection import project_evidence
    relations, groups, affinities = await project_evidence(investigation.id, investigation.entities,
        investigation.target, investigation.relationships)
    target = investigation.target
    root_id = f"target-{target.id}"
    root_label = target.full_name or target.username or target.email or target.phone or target.dni or "Identidad Objetivo"
    membership = {str(entity_id): str(group.id) for group in groups for entity_id in group.entity_ids}
    nodes = [
        GraphNode(
            id=root_id,
            type="personRoot",
            position=GraphNodePosition(x=0, y=0),
            data=GraphNodeData(
                label=root_label,
                entity_type="target",
                value=root_label,
                display_name=root_label,
                is_root=True,
                metadata_info={
                    "full_name": target.full_name,
                    "email": target.email,
                    "username": target.username,
                    "phone": target.phone,
                    "university": target.university,
                    "dni": target.dni,
                    "description": target.description,
                    "declared_seeds": (target.footprint_input or {}).get("declared_seeds", []),
                    "correlation_policy_version": 2,
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
                    source_tool=entity.source_tool,
                    discovered_at=entity.discovered_at.isoformat() if entity.discovered_at else None,
                    group_id=membership.get(str(entity.id)),
                    correlation=affinities[str(entity.id)],
                ),
            )
        )
        affinity = affinities[str(entity.id)]
        strong_email = any(signal['kind'] == 'email' and signal['role'] in STRONG_EMAIL_ROLES
            for signal in affinity['signals'])
        strong_phone = any(signal['kind'] == 'phone' and signal['role'] in STRONG_PHONE_ROLES
            for signal in affinity['signals'])
        rel_type, rel_label = 'discovered_from', 'hallazgo derivado'
        if affinity['level'] == 'strong':
            if strong_email:
                rel_type, rel_label = 'target_email_match', 'correo coincidente observado'
            elif strong_phone:
                rel_type, rel_label = 'target_phone_match', 'teléfono coincidente observado'
            else:
                rel_type, rel_label = 'target_identifier_match', 'identificador coincidente observado'
        elif affinity['level'] == 'registration':
            rel_type, rel_label = 'registration_query', 'señal de registro del correo'
        elif affinity['weight'] > 0:
            rel_type, rel_label = 'target_context_match', 'coincidencia contextual'

        edges.append(
            GraphEdge(
                id=f"source-{entity.id}",
                source=root_id,
                target=entity_id,
                relation_type=rel_type,
                label=rel_label,
                style=EDGE_STYLES.get(rel_type, EDGE_STYLES["discovered_from"]),
                evidence={"source_tool": entity.source_tool, "signals": affinity['signals'],
                    "visual_weight": affinity['weight'], "semantics": affinity['semantics'],
                    "ownership_status": "unverified"},
            )
        )

    for relationship in relations:
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

    return GraphResponse(investigation_id=str(investigation.id), nodes=nodes, edges=edges)


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
        '  <key id="correlation" for="node" attr.name="correlation" attr.type="string"/>',
        '  <key id="evidence" for="edge" attr.name="evidence" attr.type="string"/>',
        '  <graph id="G" edgedefault="undirected">',
    ]
    for node in graph.nodes:
        lines.extend(
            [
                f'    <node id="{escape(node.id)}">',
                f'      <data key="label">{escape(node.data.label)}</data>',
                f'      <data key="type">{escape(node.data.entity_type)}</data>',
                f'      <data key="correlation">{escape(json.dumps(node.data.correlation, ensure_ascii=False))}</data>',
                "    </node>",
            ]
        )
    for edge in graph.edges:
        lines.extend(
            [
                f'    <edge source="{escape(edge.source)}" target="{escape(edge.target)}">',
                f'      <data key="relation">{escape(edge.relation_type)}</data>',
                f'      <data key="evidence">{escape(json.dumps(edge.evidence, ensure_ascii=False))}</data>',
                "    </edge>",
            ]
        )
    lines.extend(["  </graph>", "</graphml>"])
    return Response(
        content="\n".join(lines),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="person_map_{id}.graphml"'},
    )
