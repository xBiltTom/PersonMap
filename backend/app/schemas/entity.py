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
    # Valor mostrado: el máximo de las dos métricas de abajo.
    confidence: float
    # Certeza de DETECCIÓN que reporta la herramienta ("esta cuenta existe").
    existence_confidence: Optional[float] = None
    # Probabilidad de ATRIBUCIÓN del modelo Fellegi-Sunter ("es del objetivo").
    identity_score: Optional[float] = None
    scorer_version: Optional[str] = None
    verified: bool
    verification_notes: Optional[str] = None
    source_tool: str
    discovered_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EntityVerifyRequest(BaseModel):
    verified: bool
    verification_notes: Optional[str] = None
