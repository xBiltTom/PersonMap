import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from app.core.database import Base


class EntityObservation(Base):
    """Vincula una observación de herramienta con una entidad canónica del expediente."""

    __tablename__ = "entity_observations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_id = Column(
        UUID(as_uuid=True),
        ForeignKey("entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_execution_id = Column(
        UUID(as_uuid=True),
        ForeignKey("tool_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    observed_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    source_url = Column(String(2048), nullable=True)
    evidence_urls = Column(JSONB, default=list)

    investigation = relationship("Investigation", back_populates="entity_observations")
    entity = relationship("Entity", back_populates="observations")
    tool_execution = relationship("ToolExecution", back_populates="observations")
