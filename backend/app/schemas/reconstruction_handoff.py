"""The external analyst can author interpretation, never replace reviewed facts."""
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.exposure import ExposureCategory, ExposureSeverity
from app.schemas.reconstruction import ReconstructionReport

Text = Annotated[str, Field(min_length=1, max_length=900)]
Ref = Annotated[str, Field(min_length=1, max_length=160)]


class Strict(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)


class AgentEvidence(Strict):
    id: Ref
    fact_id: Ref
    excerpt: str = Field(min_length=4, max_length=280)
    media_id: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')
    region: str | None = Field(default=None, max_length=160)


class AgentClaim(Strict):
    text: Text
    fact_ids: list[Ref] = Field(min_length=1, max_length=100)
    basis: Literal['OBSERVED', 'CORRELATED'] = 'OBSERVED'
    caveat: Text | None = None
    evidence_refs: list[Ref] = Field(default_factory=list, max_length=30)


class AgentSignal(Strict):
    category: ExposureCategory
    severity: ExposureSeverity
    observation: Text
    why_it_matters: Text
    recommendations: list[Text] = Field(min_length=1, max_length=5)
    evidence_refs: list[Ref] = Field(min_length=1, max_length=10)


class AgentPost(Strict):
    fact_id: Ref
    title: str = Field(min_length=4, max_length=160)
    context: Text
    severity: ExposureSeverity | None = None
    status: Literal['signals_detected', 'no_signals', 'no_text', 'not_analyzed']
    explanation: Text
    signals: list[AgentSignal] = Field(default_factory=list, max_length=8)
    recommendations: list[Text] = Field(default_factory=list, max_length=5)
    limitations: list[Text] = Field(min_length=1, max_length=5)


class McpReconstructionResult(Strict):
    summary: list[AgentClaim] = Field(min_length=1, max_length=8)
    identity_portrait: list[AgentClaim] = Field(min_length=1, max_length=8)
    post_analyses: list[AgentPost] = Field(max_length=2000)
    evidence: list[AgentEvidence] = Field(default_factory=list, max_length=4000)
    inspected_media_ids: list[Annotated[str, Field(pattern=r'^[a-f0-9]{64}$')]] = Field(default_factory=list, max_length=4000)


class McpReconstructionProgress(Strict):
    message: str = Field(min_length=1, max_length=500)
    analyzed_post_ids: list[Ref] = Field(default_factory=list, max_length=2000)
    failed: bool = False


class ReconstructionRequestRead(BaseModel):
    id: UUID
    investigation_id: UUID
    status: Literal['pending', 'running', 'completed', 'failed', 'cancelled']
    stale: bool
    dataset_hash: str
    input_hash: str
    client: str | None
    model: str | None
    progress: dict
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    command: str
    prompt: str
    result: ReconstructionReport | None = None
