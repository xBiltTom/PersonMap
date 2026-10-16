from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.footprint import DataProvenance, DeclaredSeed


ReviewDecisionValue = Literal["confirmed", "rejected", "uncertain"]
ReviewStatus = Literal["not_started", "in_progress", "complete"]


class ReviewDecisionPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: ReviewDecisionValue


class ReviewSource(BaseModel):
    name: str
    evidence_urls: list[str] = Field(default_factory=list)


class ReviewCandidate(BaseModel):
    id: UUID
    entity_type: str
    category: str
    platform: str | None = None
    value: str
    username: str | None = None
    display_name: str | None = None
    avatar_url: str | None = None
    public_url: str | None = None
    bio: str | None = None
    institutions: list[str] = Field(default_factory=list)
    reason: str
    sources: list[ReviewSource] = Field(default_factory=list)
    evidence_urls: list[str] = Field(default_factory=list)
    provenance: DataProvenance
    decision: ReviewDecisionValue | None = None
    decided_at: datetime | None = None


class ReviewCounts(BaseModel):
    pending: int = 0
    confirmed: int = 0
    rejected: int = 0
    uncertain: int = 0


class FairSourceState(BaseModel):
    status: str
    reason: str | None = None
    findings_count: int = 0


class FairReviewState(BaseModel):
    acquisition_finished: bool = False
    partial: bool = False
    warning: str | None = None
    sources: dict[str, FairSourceState] = Field(default_factory=dict)
    social_sources: dict[str, FairSourceState] = Field(default_factory=dict)


class InvestigationReviewResponse(BaseModel):
    version: Literal[1] = 1
    investigation_id: UUID
    review_status: ReviewStatus
    finalized_at: datetime | None = None
    counts: ReviewCounts
    declared_seeds: list[DeclaredSeed] = Field(default_factory=list)
    candidates: list[ReviewCandidate] = Field(default_factory=list)
    fair: FairReviewState


class ReviewFinalizeResponse(BaseModel):
    investigation_id: UUID
    review_status: Literal["complete"] = "complete"
    finalized_at: datetime
    counts: ReviewCounts
    dataset_version: Literal[1] = 1


class ReviewedEntity(BaseModel):
    entity_id: UUID | None = None
    seed_id: str | None = None
    entity_type: str
    platform: str | None = None
    username: str | None = None
    value: str
    display_name: str | None = None
    profile_url: str | None = None
    avatar_url: str | None = None
    bio: str | None = None
    provenance: DataProvenance
    ownership: dict[str, Any] = Field(default_factory=dict)
    source_tool: str | None = None
    source_tools: list[str] = Field(default_factory=list)
    collection_sources: list[dict[str, Any]] = Field(default_factory=list)
    public_content: list[dict[str, Any]] = Field(default_factory=list)
    evidence_urls: list[str] = Field(default_factory=list)
    associated_profile_entity_id: UUID | None = None
    authorship_evidence: dict[str, Any] = Field(default_factory=dict)


class ReviewedDecisionRecord(BaseModel):
    entity_id: UUID
    entity_type: str
    platform: str | None = None
    value: str
    display_name: str | None = None
    decision: ReviewDecisionValue
    decided_at: datetime


class ReviewedDeclaredSeed(BaseModel):
    seed_id: str
    kind: Literal["name", "email", "username", "phone"]
    value: str
    platform: str | None = None
    provenance: DataProvenance


class BreachExposure(BaseModel):
    entity_id: UUID
    email: str
    associated_email_entity_id: UUID | None = None
    associated_declared_email: bool = False
    breaches: list[str] = Field(default_factory=list)
    provenance: DataProvenance
    evidence_urls: list[str] = Field(default_factory=list)
    semantics: Literal["exposure_observed_not_identity_proof"] = "exposure_observed_not_identity_proof"


class ReviewedFootprintDataset(BaseModel):
    version: Literal[1] = 1
    subject: dict[str, list[ReviewedDeclaredSeed]]
    accounts: list[ReviewedEntity] = Field(default_factory=list)
    emails: list[ReviewedEntity] = Field(default_factory=list)
    phones: list[ReviewedEntity] = Field(default_factory=list)
    academic_profiles: list[ReviewedEntity] = Field(default_factory=list)
    documents: list[ReviewedEntity] = Field(default_factory=list)
    breaches: list[BreachExposure] = Field(default_factory=list)
    social_content: list[dict[str, Any]] = Field(default_factory=list)
    review: dict[str, list[ReviewedDecisionRecord]]
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    execution: dict[str, Any]
