from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict


class EntityRead(BaseModel):
    id: UUID
    investigation_id: UUID
    entity_type: str
    platform: Optional[str] = None
    value: str
    display_name: Optional[str] = None
    metadata_info: Dict[str, Any] = {}
    source_tool: str
    discovered_at: datetime

    model_config = ConfigDict(from_attributes=True)
