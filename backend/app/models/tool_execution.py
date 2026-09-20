import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import relationship

from app.core.database import Base


class ToolExecution(Base):
    """Una ejecución real de una herramienta, independiente de sus hallazgos deduplicados."""

    __tablename__ = "tool_executions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tool_name = Column(String(100), nullable=False)
    tool_description = Column(String(255), nullable=True)
    engine = Column(String(50), nullable=False)
    engine_layer = Column(String(50), nullable=True)
    round_index = Column(Integer, nullable=True)
    turn_index = Column(Integer, nullable=True)
    started_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(30), nullable=False, default="running")
    findings_count = Column(Integer, nullable=False, default=0)
    # Agregado seguro: tipos de entrada/contexto, nunca valores, claves ni prompts.
    input_summary = Column(MutableDict.as_mutable(JSONB), default=dict)
    error_summary = Column(Text, nullable=True)

    investigation = relationship("Investigation", back_populates="tool_executions")
    observations = relationship("EntityObservation", back_populates="tool_execution", cascade="all, delete-orphan")
