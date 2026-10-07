from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class AwarenessSurveyCreate(BaseModel):
    investigation_id: UUID
    pre_awareness: int = Field(ge=1, le=5, description="Puntuación pre-exposición (1-5)")
    post_awareness: int = Field(ge=1, le=5, description="Puntuación post-exposición (1-5)")
    reused_alias: bool = Field(default=True)
    knew_commit_leak: bool = Field(default=False)
    will_change_habits: bool = Field(default=True)


class AwarenessSurveyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    investigation_id: UUID
    pre_awareness: int
    post_awareness: int
    reused_alias: bool
    knew_commit_leak: bool
    will_change_habits: bool
    created_at: datetime
