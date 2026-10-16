import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.core.database import Base


class ReconstructionRun(Base):
    __tablename__ = 'reconstruction_runs'
    __table_args__ = (
        UniqueConstraint('investigation_id', 'input_hash', name='uq_reconstruction_input'),
        CheckConstraint("status IN ('completed', 'partial')", name='ck_reconstruction_terminal'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey('investigations.id', ondelete='CASCADE'), nullable=False, index=True)
    dataset_hash = Column(String(64), nullable=False)
    exposure_hash = Column(String(64), nullable=False)
    input_hash = Column(String(64), nullable=False)
    analysis_version = Column(String(40), nullable=False)
    status = Column(String(16), nullable=False)
    snapshot = Column(JSONB, nullable=False)
    config = Column(JSONB, nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=False)


class ReconstructionRequest(Base):
    """Durable handoff from the web UI to a client-side MCP analyst."""
    __tablename__ = 'reconstruction_requests'
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'cancelled')", name='ck_reconstruction_request_status'),
    )
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey('investigations.id', ondelete='CASCADE'), nullable=False, index=True)
    input_hash = Column(String(64), nullable=False)
    dataset_hash = Column(String(64), nullable=False)
    status = Column(String(16), nullable=False, default='pending')
    base_snapshot = Column(JSONB, nullable=False)
    result_snapshot = Column(JSONB, nullable=True)
    progress = Column(JSONB, nullable=False, default=dict)
    claim_token = Column(UUID(as_uuid=True), nullable=True)
    client = Column(String(100), nullable=True)
    model = Column(String(200), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
