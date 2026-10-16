from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


ExposureStatus = Literal["pending", "running", "completed", "partial", "failed"]
ExposureSeverity = Literal["high", "medium", "low", "informational"]
ExposureBasis = Literal["observed", "inferred"]
ExposureMethod = Literal["deterministic", "ai"]
ExposurePartialReason = Literal["acquisition_partial", "content_limit_reached", "ai_failure"]
ExposureCategory = Literal[
    "contact_exposure",
    "alias_reuse",
    "cross_platform_correlation",
    "location_disclosure",
    "temporal_exposure",
    "education_work_context",
    "biographical_identifiers",
    "public_documents",
    "breach_exposure",
    "infostealer_exposure",
    "content_disclosure",
]


class ExposureEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_type: Literal["entity", "content", "breach", "infostealer", "document"]
    source_id: str | None = None
    platform: str | None = None
    account: str | None = None
    url: str | None = None
    occurred_at: str | None = None
    excerpt: str = Field(default="", max_length=280)


class ExposureFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: ExposureCategory
    severity: ExposureSeverity
    title: str = Field(max_length=160)
    summary: str = Field(max_length=500)
    why_it_matters: str = Field(max_length=500)
    evidence: list[ExposureEvidence] = Field(default_factory=list, max_length=20)
    source_entity_ids: list[str] = Field(default_factory=list, max_length=100)
    source_content_ids: list[str] = Field(default_factory=list, max_length=100)
    recommendations: list[str] = Field(default_factory=list, max_length=8)
    basis: ExposureBasis = "observed"
    analysis_method: ExposureMethod = "deterministic"
    signals: list[str] = Field(default_factory=list, max_length=12)


class ExposureSummary(BaseModel):
    high: int = 0
    medium: int = 0
    low: int = 0
    informational: int = 0


class ExposureTopItem(BaseModel):
    id: str
    platform: str | None = None
    account: str | None = None
    published_at: str | None = None
    excerpt: str = Field(max_length=280)
    severity: ExposureSeverity
    analysis_method: ExposureMethod = "deterministic"
    reveals: list[str] = Field(default_factory=list, max_length=8)
    why_it_matters: str
    evidence: list[ExposureEvidence] = Field(default_factory=list, max_length=10)
    recommendations: list[str] = Field(default_factory=list, max_length=8)


class ExposureReport(BaseModel):
    version: Literal[1] = 1
    investigation_id: str
    dataset_hash: str | None = None
    current_dataset_hash: str | None = None
    analysis_version: str = "exposure-v2"
    status: ExposureStatus = "pending"
    partial_reasons: list[ExposurePartialReason] = Field(default_factory=list, max_length=3)
    stale: bool = False
    cache_hit: bool = False
    summary: ExposureSummary = Field(default_factory=ExposureSummary)
    categories: dict[str, int] = Field(default_factory=dict)
    findings: list[ExposureFinding] = Field(default_factory=list)
    top_exposures: list[ExposureTopItem] = Field(default_factory=list)
    analyzed_content_count: int = 0
    skipped_content_count: int = 0
    generated_at: datetime | None = None
    model: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
