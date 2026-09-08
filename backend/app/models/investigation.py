import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
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

    # Risk Score: 0 - 100
    risk_score = Column(Integer, default=0, nullable=False)

    # Auto-generated intelligence summary / awareness narrative
    summary = Column(Text, nullable=True)

    # Metrics for academic paper: execution_time, tool_calls, entities_count, etc.
    metrics = Column(MutableDict.as_mutable(JSONB), default=dict)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)

    target = relationship("Target", back_populates="investigations")
    entities = relationship("Entity", back_populates="investigation", cascade="all, delete-orphan")
    relationships = relationship("Relationship", back_populates="investigation", cascade="all, delete-orphan")
    identity_clusters = relationship("IdentityCluster", back_populates="investigation", cascade="all, delete-orphan")
