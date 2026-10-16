import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.core.database import Base


class ExposureRun(Base):
    __tablename__ = "exposure_runs"
    __table_args__ = (
        UniqueConstraint("investigation_id", "dataset_hash", "analysis_version", "config_hash",
                         name="uq_exposure_run_dataset_config"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(
        UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    dataset_hash = Column(String(64), nullable=False, index=True)
    config_hash = Column(String(64), nullable=False)
    analysis_version = Column(String(40), nullable=False)
    status = Column(String(16), nullable=False, default="pending")
    started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    completed_at = Column(DateTime(timezone=True), nullable=True)
    model = Column(String(200), nullable=True)
    config = Column(JSONB, nullable=False, default=dict)
    summary = Column(JSONB, nullable=False, default=dict)
    findings = Column(JSONB, nullable=False, default=list)
    top_exposures = Column(JSONB, nullable=False, default=list)
    analyzed_content_count = Column(Integer, nullable=False, default=0)
    skipped_content_count = Column(Integer, nullable=False, default=0)


class ExposureContentCache(Base):
    __tablename__ = "exposure_content_cache"
    __table_args__ = (
        UniqueConstraint("content_hash", "analysis_version", "config_hash",
                         name="uq_exposure_content_cache_key"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_hash = Column(String(64), nullable=False)
    analysis_version = Column(String(40), nullable=False)
    config_hash = Column(String(64), nullable=False)
    model = Column(String(200), nullable=True)
    result = Column(JSONB, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
