import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import relationship
from app.core.database import Base


class Investigation(Base):
    __tablename__ = "investigations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    target_id = Column(UUID(as_uuid=True), ForeignKey("targets.id", ondelete="CASCADE"), nullable=False, index=True)

    # Strategy: "auto", "rule_based", "agentic"
    strategy = Column(String(50), default="auto", nullable=False)

    # Status: "pending", "running", "completed", "failed"
    status = Column(String(50), default="pending", nullable=False, index=True)

    # Summary of the observed evidence graph.
    summary = Column(Text, nullable=True)

    # Metrics for academic paper: execution_time, tool_calls, entities_count, etc.
    metrics = Column(MutableDict.as_mutable(JSONB), default=dict)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    target = relationship("Target", back_populates="investigations")
    entities = relationship("Entity", back_populates="investigation", cascade="all, delete-orphan")
    relationships = relationship("Relationship", back_populates="investigation", cascade="all, delete-orphan")
    correlation_groups = relationship("CorrelationGroup", back_populates="investigation", cascade="all, delete-orphan")
    tool_executions = relationship("ToolExecution", back_populates="investigation", cascade="all, delete-orphan")
    entity_observations = relationship("EntityObservation", back_populates="investigation", cascade="all, delete-orphan")
    trace_events = relationship("InvestigationTraceEvent", back_populates="investigation", cascade="all, delete-orphan")


# Registra los modelos relacionados incluso cuando un endpoint importa solamente
# `Investigation`; SQLAlchemy necesita conocerlos antes de configurar los mappers.
from app.models.correlation_group import CorrelationGroup  # noqa: E402, F401
from app.models.entity import Entity  # noqa: E402, F401
from app.models.relationship import Relationship  # noqa: E402, F401
from app.models.target import Target  # noqa: E402, F401
from app.models.tool_execution import ToolExecution  # noqa: E402, F401
from app.models.entity_observation import EntityObservation  # noqa: E402, F401
from app.models.investigation_trace_event import InvestigationTraceEvent  # noqa: E402, F401
