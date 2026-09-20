from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TraceEntity(BaseModel):
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


class ToolExecutionRead(BaseModel):
    id: UUID
    tool_name: str
    tool_description: Optional[str] = None
    engine: str
    engine_layer: Optional[str] = None
    round_index: Optional[int] = None
    turn_index: Optional[int] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    status: str
    findings_count: int
    input_summary: Dict[str, Any] = {}
    error_summary: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class EntityObservationRead(BaseModel):
    id: UUID
    entity_id: UUID
    tool_execution_id: UUID
    observed_at: datetime
    source_url: Optional[str] = None
    evidence_urls: List[str] = []
    entity: TraceEntity

    model_config = ConfigDict(from_attributes=True)


class InvestigationTraceEventRead(BaseModel):
    id: UUID
    event_type: str
    engine: str
    engine_layer: Optional[str] = None
    round_index: Optional[int] = None
    turn_index: Optional[int] = None
    created_at: datetime
    data: Dict[str, Any] = {}

    model_config = ConfigDict(from_attributes=True)


class InvestigationTraceResponse(BaseModel):
    investigation_id: UUID
    available: bool
    executions: List[ToolExecutionRead] = []
    observations: List[EntityObservationRead] = []
    events: List[InvestigationTraceEventRead] = []
