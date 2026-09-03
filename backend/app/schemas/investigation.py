from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict
from app.schemas.target import TargetCreate, TargetRead
from app.schemas.entity import EntityRead
from app.schemas.identity import IdentityClusterRead


class InvestigationCreate(BaseModel):
    target: TargetCreate
    # Strategy: "auto" (uses LLM if available, otherwise rule_engine), "rule_based", "agentic"
    strategy: str = "auto"


class InvestigationRead(BaseModel):
    id: UUID
    target_id: UUID
    strategy: str
    status: str
    risk_score: int
    summary: Optional[str] = None
    metrics: Dict[str, Any] = {}
    created_at: datetime
    completed_at: Optional[datetime] = None
    target: Optional[TargetRead] = None

    model_config = ConfigDict(from_attributes=True)


class InvestigationDetail(InvestigationRead):
    entities: List[EntityRead] = []
    identity_clusters: List[IdentityClusterRead] = []
