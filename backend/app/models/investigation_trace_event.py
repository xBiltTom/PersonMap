import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import relationship

from app.core.database import Base


class InvestigationTraceEvent(Base):
    """Evento estructural de la ejecución: rondas, pivotes, turnos o llamadas omitidas."""

    __tablename__ = "investigation_trace_events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type = Column(String(50), nullable=False)
    engine = Column(String(50), nullable=False)
    engine_layer = Column(String(50), nullable=True)
    round_index = Column(Integer, nullable=True)
    turn_index = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    data = Column(MutableDict.as_mutable(JSONB), default=dict)

    investigation = relationship("Investigation", back_populates="trace_events")
