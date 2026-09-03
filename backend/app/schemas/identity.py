from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from app.schemas.entity import EntityRead


class IdentityClusterRead(BaseModel):
    id: UUID
    investigation_id: UUID
    label: str
    confidence: float
    entity_ids: List[str]
    reasoning: Optional[str] = None
    scoring_breakdown: Dict[str, Any] = {}
    entities: List[EntityRead] = []

    model_config = ConfigDict(from_attributes=True)
