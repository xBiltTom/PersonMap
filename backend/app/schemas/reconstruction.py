"""Versioned, evidence referenced public footprint contracts."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.exposure import ExposureSeverity, ExposureStatus, ExposureSummary

Basis = Literal['DECLARED', 'OBSERVED', 'CORRELATED', 'INFERRED']
FactKind = Literal['subject', 'name', 'email', 'phone', 'alias', 'domain', 'url', 'account',
                   'academic_profile', 'document', 'publication', 'repository', 'post', 'breach', 'infostealer', 'exposure', 'context']
Group = Literal['identity', 'accounts', 'content', 'documents', 'breaches', 'exposure']
RelationType = Literal['DECLARES', 'ATTRIBUTED_ACCOUNT', 'ATTRIBUTED_PROFILE', 'USES_ALIAS',
                       'USES_EMAIL', 'USES_PHONE', 'PUBLIC_EMAIL_ON', 'PUBLIC_PHONE_ON',
                       'LINKS_TO', 'SAME_ALIAS', 'SAME_EMAIL', 'PUBLISHED', 'COAUTHORED', 'AUTHORED',
                       'ASSOCIATED_WITH', 'MENTIONED_IN', 'EXPOSED_IN_BREACH', 'EXPOSED_IN_INFOSTEALER', 'HAS_EXPOSURE_SIGNAL']


class EvidenceRef(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    source_type: str
    source_entity_ids: list[str] = Field(default_factory=list)
    source_content_ids: list[str] = Field(default_factory=list)
    platform: str | None = None
    url: str | None = None
    excerpt: str = Field(max_length=280)


class ReconstructionFact(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    kind: FactKind
    label: str = Field(max_length=160)
    basis: Basis
    group: Group
    ring: int = Field(ge=0, le=4)
    platform: str | None = None
    url: str | None = None
    safe_summary: str = Field(default='', max_length=500)
    ownership_basis: str | None = None
    source_tools: list[str] = Field(default_factory=list)
    source_entity_ids: list[str] = Field(default_factory=list)
    source_content_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    evidence_types: list[str] = Field(default_factory=list)
    severity: ExposureSeverity | None = None
    date: str | None = None


class ReconstructionRelation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str
    source: str
    target: str
    type: RelationType
    basis: Basis
    why: str
    source_entity_ids: list[str] = Field(default_factory=list)
    source_content_ids: list[str] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    evidence_count: int = 0
    evidence_types: list[str] = Field(default_factory=list)


class GraphV2(BaseModel):
    version: Literal['graph-v2'] = 'graph-v2'
    nodes: list[ReconstructionFact] = Field(default_factory=list)
    edges: list[ReconstructionRelation] = Field(default_factory=list)
    omitted_nodes: int = 0
    omitted_by_type: dict[str, int] = Field(default_factory=dict)


class NarrativeClaim(BaseModel):
    text: str
    fact_ids: list[str]
    basis: Literal['DECLARED', 'OBSERVED', 'CORRELATED'] | None = None
    caveat: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class TimelineItem(BaseModel):
    id: str
    date: str
    kind: FactKind
    label: str
    platform: str | None = None
    fact_ids: list[str]
    evidence_refs: list[str]
    basis: Literal['OBSERVED'] = 'OBSERVED'


class ReconstructionIdentity(BaseModel):
    declared: list[str] = Field(default_factory=list)
    accounts: list[str] = Field(default_factory=list)
    public_identifiers: list[str] = Field(default_factory=list)
    academic_presence: list[str] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)
    public_content: list[str] = Field(default_factory=list)
    breach_exposure: list[str] = Field(default_factory=list)


class PostRiskSignal(BaseModel):
    category: str
    label: str
    severity: ExposureSeverity
    observation: str
    why_it_matters: str
    recommendations: list[str]
    evidence_refs: list[str]
    analysis_method: Literal['deterministic', 'ai'] = 'deterministic'


class PostAssessment(BaseModel):
    fact_id: str
    severity: ExposureSeverity | None = None
    status: Literal['signals_detected', 'no_signals', 'no_text']
    signals: list[PostRiskSignal] = Field(default_factory=list)
    explanation: str
    recommendations: list[str] = Field(default_factory=list)
    title: str = ''
    context: str = ''
    limitations: list[str] = Field(default_factory=list)
    analysis_method: Literal['deterministic', 'ai'] = 'deterministic'


class DigitalFootprintReconstruction(BaseModel):
    version: Literal[1] = 1
    reconstruction_version: Literal['reconstruction-v1'] = 'reconstruction-v1'
    investigation_id: str
    dataset_hash: str
    exposure_dataset_hash: str
    exposure_hash: str
    input_hash: str
    coverage: Literal['observed', 'partial']
    coverage_reasons: list[str] = Field(default_factory=list)
    identity: ReconstructionIdentity
    facts: list[ReconstructionFact]
    evidence: dict[str, EvidenceRef]
    correlations: list[ReconstructionRelation]
    summary: list[NarrativeClaim]
    identity_portrait: list[NarrativeClaim] = Field(default_factory=list)
    post_assessments: list[PostAssessment] = Field(default_factory=list)
    content_analysis_status: Literal['deterministic', 'completed', 'partial', 'fallback'] = 'deterministic'
    narrative_highlights: list[NarrativeClaim] = Field(default_factory=list)
    narrative_method: Literal["deterministic", "ai_assisted"] = "deterministic"
    narrative_status: Literal["deterministic", "completed", "fallback"] = "deterministic"
    narrative_model: str | None = None
    counts: dict[str, int]
    content_by_platform: dict[str, int]
    exposure_summary: ExposureSummary
    timeline: list[TimelineItem]
    graph: GraphV2
    generated_at: datetime


class ReconstructionReport(BaseModel):
    version: Literal[1] = 1
    investigation_id: str
    status: ExposureStatus = 'pending'
    stale: bool = False
    cache_hit: bool = False
    input_hash: str | None = None
    current_input_hash: str | None = None
    snapshot: DigitalFootprintReconstruction | None = None
