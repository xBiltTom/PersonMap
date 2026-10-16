import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from app.core.database import Base


class ReviewDecision(Base):
    """One active human decision per persisted finding, with a small change log."""

    __tablename__ = "review_decisions"
    __table_args__ = (
        UniqueConstraint("investigation_id", "entity_id", name="uq_review_decision_entity"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(
        UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    entity_id = Column(
        UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    decision = Column(String(20), nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    history = Column(JSONB, nullable=False, default=list)
