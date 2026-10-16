from datetime import datetime
from typing import Any, Dict, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, computed_field
from app.schemas.footprint import DataProvenance, discovered_provenance


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

    @computed_field
    @property
    def provenance(self) -> DataProvenance:
        return DataProvenance.model_validate(self.metadata_info.get("provenance") or discovered_provenance(
            self.metadata_info.get("evidence_urls", [])))

    model_config = ConfigDict(from_attributes=True)
