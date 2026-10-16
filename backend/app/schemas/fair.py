"""Versioned acquisition contracts; none of these fields attributes discoveries."""
from typing import Literal
from pydantic import BaseModel, Field

SourceStatus = Literal["pending", "running", "completed", "partial", "timeout", "skipped",
                       "budget_exhausted", "provider_unavailable", "not_applicable", "failed"]


class FairSourceProgress(BaseModel):
    status: SourceStatus = "pending"
    critical: bool
    reason: str | None = None
    findings_count: int = 0
    attempts: list[dict] = Field(default_factory=list)


class FairProgress(BaseModel):
    version: Literal[1] = 1
    mode: Literal["fair"] = "fair"
    phase: str
    elapsed_seconds: float
    deadline_seconds: float
    sources: dict[str, FairSourceProgress]
    social_sources: dict[str, dict] = Field(default_factory=dict)


class FairSnapshot(BaseModel):
    version: Literal[1] = 1
    mode: Literal["fair"] = "fair"
    declared: list[dict]
    findings: list[dict]
    sources: dict[str, FairSourceProgress]
    pivots: dict
    social_content: list[dict]
    breaches: list[dict]
    academic: list[dict]
    documents: list[dict]
    execution: dict
    plan: dict
