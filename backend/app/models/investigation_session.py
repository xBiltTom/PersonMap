"""Durable external-agent sessions; independent of MCP transport connections."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class InvestigationSession(Base):
    __tablename__ = "investigation_sessions"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)
    client = Column(String(100), nullable=False)
    model = Column(String(200), nullable=True)  # Declared by the client, not independently verified.
    status = Column(String(30), nullable=False, default="active")
    started_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    ended_at = Column(DateTime(timezone=True), nullable=True)
    investigation = relationship("Investigation", back_populates="sessions")
    __table_args__ = (Index("uq_active_investigation_session", "investigation_id", unique=True,
                           postgresql_where=text("status = 'active'")),)
