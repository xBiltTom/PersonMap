"""Authored analysis kept apart from observations produced by OSINT tools."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class AnalysisNote(Base):
    __tablename__ = "analysis_notes"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id = Column(UUID(as_uuid=True), ForeignKey("investigation_sessions.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(30), nullable=False)
    title = Column(String(200), nullable=False)
    content = Column(Text, nullable=False)
    author = Column(String(100), nullable=False)
    author_type = Column(String(20), nullable=False)
    evidence_urls = Column(JSONB, nullable=False, default=list)
    entity_ids = Column(JSONB, nullable=False, default=list)
    execution_ids = Column(JSONB, nullable=False, default=list)
    details = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    investigation = relationship("Investigation", back_populates="analysis_notes")
