from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class GraphNodePosition(BaseModel):
    x: float
    y: float


class GraphNodeData(BaseModel):
    label: str
    entity_type: str
    platform: Optional[str] = None
    value: str
    display_name: Optional[str] = None
    metadata_info: Dict[str, Any] = {}
    # Trazabilidad de la observación. Se exponen junto a metadata_info para que
    # el inspector no tenga que deducir procedencia a partir del valor del nodo.
    source_tool: Optional[str] = None
    discovered_at: Optional[str] = None
    is_root: bool = False
    group_id: Optional[str] = None


class GraphNode(BaseModel):
    id: str
    type: str = "customEntity"
    position: GraphNodePosition
    data: GraphNodeData


class GraphEdge(BaseModel):
    id: str
    source: str
    target: str
    label: Optional[str] = None
    relation_type: str = "linked_to"
    animated: bool = False
    style: Dict[str, Any] = {}
    evidence: Dict[str, Any] = {}
    supports_group: bool = False


class GraphResponse(BaseModel):
    investigation_id: str
    nodes: List[GraphNode]
    edges: List[GraphEdge]
