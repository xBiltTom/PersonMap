import math
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from app.core.database import get_db
from app.models.investigation import Investigation
from app.models.relationship import Relationship
from app.schemas.graph import (
    GraphEdge,
    GraphNode,
    GraphNodeData,
    GraphNodePosition,
    GraphResponse,
)

router = APIRouter()


@router.get("/investigations/{id}/graph", response_model=GraphResponse)
async def get_investigation_graph(
    id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Computes and returns the interactive React Flow graph for an investigation.
    Includes the target root node, discovered entities, and semantic relationships.
    """
    stmt = (
        select(Investigation)
        .where(Investigation.id == id)
        .options(
            selectinload(Investigation.target),
            selectinload(Investigation.entities),
            selectinload(Investigation.relationships),
        )
    )
    result = await db.execute(stmt)
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigación no encontrada")

    target = inv.target
    entities = inv.entities
    relationships = inv.relationships

    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []

    # 1. Root Node (The Target Person)
    root_id = f"target-{target.id}"
    root_label = target.full_name or target.username or target.email or "Objetivo"
    nodes.append(
        GraphNode(
            id=root_id,
            type="personRoot",
            position=GraphNodePosition(x=400.0, y=300.0),
            data=GraphNodeData(
                label=root_label,
                entity_type="person",
                value=root_label,
                display_name=root_label,
                confidence=1.0,
                verified=True,
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
    )

    # 2. Entity Nodes in concentric arrangement
    total_entities = len(entities)
    radius = 280.0 if total_entities < 15 else 360.0

    for i, ent in enumerate(entities):
        angle = (2 * math.pi * i) / max(total_entities, 1)
        x_pos = round(400.0 + radius * math.cos(angle), 1)
        y_pos = round(300.0 + radius * math.sin(angle), 1)

        ent_id = f"ent-{ent.id}"
        nodes.append(
            GraphNode(
                id=ent_id,
                type="customEntity",
                position=GraphNodePosition(x=x_pos, y=y_pos),
                data=GraphNodeData(
                    label=ent.display_name or ent.value,
                    entity_type=ent.entity_type,
                    platform=ent.platform,
                    value=ent.value,
                    display_name=ent.display_name,
                    confidence=ent.confidence,
                    verified=ent.verified,
                    metadata_info=ent.metadata_info or {},
                    is_root=False,
                ),
            )
        )

        # Primary Edge from Root to Entity
        edge_id = f"edge-root-{ent.id}"
        is_high_conf = ent.confidence >= 0.70
        edges.append(
            GraphEdge(
                id=edge_id,
                source=root_id,
                target=ent_id,
                label=f"{int(ent.confidence * 100)}%",
                relation_type="identified_profile",
                strength=ent.confidence,
                animated=is_high_conf,
                style={"stroke": "#22d3ee" if is_high_conf else "#71717a", "strokeWidth": 2 if is_high_conf else 1},
            )
        )

    # 3. Inter-entity Relationship Edges
    for rel in relationships:
        src_id = f"ent-{rel.source_entity_id}"
        tgt_id = f"ent-{rel.target_entity_id}"
        edges.append(
            GraphEdge(
                id=f"rel-{rel.id}",
                source=src_id,
                target=tgt_id,
                label=rel.relation_type.replace("_", " "),
                relation_type=rel.relation_type,
                strength=rel.strength,
                animated=False,
                style={"stroke": "#a855f7", "strokeDasharray": "5,5", "strokeWidth": 1.5},
            )
        )

    return GraphResponse(
        investigation_id=str(id),
        nodes=nodes,
        edges=edges,
    )


@router.get("/investigations/{id}/graphml")
async def export_graphml(
    id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """
    Exports the investigation digital map in GraphML format for direct import
    into Gephi, Cytoscape, or NetworkX for academic publication graphics.
    """
    stmt = (
        select(Investigation)
        .where(Investigation.id == id)
        .options(
            selectinload(Investigation.target),
            selectinload(Investigation.entities),
            selectinload(Investigation.relationships),
        )
    )
    result = await db.execute(stmt)
    inv = result.scalar_one_or_none()
    if not inv:
        raise HTTPException(status_code=404, detail="Investigación no encontrada")

    target = inv.target
    entities = inv.entities
    relationships = inv.relationships

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns"',
        '         xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"',
        '         xsi:schemaLocation="http://graphml.graphdrawing.org/xmlns http://graphml.graphdrawing.org/xmlns/1.0/graphml.xsd">',
        '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
        '  <key id="type" for="node" attr.name="type" attr.type="string"/>',
        '  <key id="platform" for="node" attr.name="platform" attr.type="string"/>',
        '  <key id="confidence" for="node" attr.name="confidence" attr.type="double"/>',
        '  <key id="weight" for="edge" attr.name="weight" attr.type="double"/>',
        '  <key id="relation" for="edge" attr.name="relation" attr.type="string"/>',
        '  <graph id="G" edgedefault="undirected">',
    ]

    # Root Target node
    root_id = f"target_{target.id}"
    root_label = target.full_name or target.username or "Target"
    xml_lines.append(f'    <node id="{root_id}">')
    xml_lines.append(f'      <data key="label">{root_label}</data>')
    xml_lines.append('      <data key="type">target</data>')
    xml_lines.append('      <data key="platform">identity</data>')
    xml_lines.append('      <data key="confidence">1.0</data>')
    xml_lines.append('    </node>')

    # Entity nodes
    for ent in entities:
        ent_id = f"ent_{ent.id}"
        ent_label = (ent.display_name or ent.value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        xml_lines.append(f'    <node id="{ent_id}">')
        xml_lines.append(f'      <data key="label">{ent_label}</data>')
        xml_lines.append(f'      <data key="type">{ent.entity_type}</data>')
        xml_lines.append(f'      <data key="platform">{ent.platform or "web"}</data>')
        xml_lines.append(f'      <data key="confidence">{ent.confidence}</data>')
        xml_lines.append('    </node>')

        # Edge from target to entity
        xml_lines.append(f'    <edge source="{root_id}" target="{ent_id}">')
        xml_lines.append(f'      <data key="weight">{ent.confidence}</data>')
        xml_lines.append('      <data key="relation">identified</data>')
        xml_lines.append('    </edge>')

    # Semantic relationships
    for rel in relationships:
        xml_lines.append(f'    <edge source="ent_{rel.source_entity_id}" target="ent_{rel.target_entity_id}">')
        xml_lines.append(f'      <data key="weight">{rel.strength}</data>')
        xml_lines.append(f'      <data key="relation">{rel.relation_type}</data>')
        xml_lines.append('    </edge>')

    xml_lines.append('  </graph>')
    xml_lines.append('</graphml>')

    from fastapi.responses import Response
    return Response(
        content="\n".join(xml_lines),
        media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="person_map_{id}.graphml"'},
    )
