from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from app.schemas.entity import EntityRead


class CorrelationGroupRead(BaseModel):
    id: UUID
    investigation_id: UUID
    label: str
    entity_ids: List[str]
    summary: Optional[str] = None
    evidence: Dict[str, Any] = {}
    entities: List[EntityRead] = []

    model_config = ConfigDict(from_attributes=True)
