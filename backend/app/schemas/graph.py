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
    confidence: float
    # Las dos métricas que `confidence` resume: detección y atribución.
    existence_confidence: Optional[float] = None
    identity_score: Optional[float] = None
    verified: bool
    metadata_info: Dict[str, Any] = {}
    is_root: bool = False


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
    strength: float = 0.5
    animated: bool = False
    style: Dict[str, Any] = {}


class GraphResponse(BaseModel):
    investigation_id: str
    nodes: List[GraphNode]
    edges: List[GraphEdge]
