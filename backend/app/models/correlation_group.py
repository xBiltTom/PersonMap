import uuid
from sqlalchemy import Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import relationship
from app.core.database import Base


class CorrelationGroup(Base):
    """Componente de observaciones conectadas por evidencia explícita."""

    __tablename__ = "correlation_groups"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)

    # Etiqueta neutral y estable: "Grupo 01", "Grupo 02", etc.
    label = Column(String(255), nullable=False)

    # Lista materializada para cargar el expediente sin resolver el grafo de
    # nuevo. No significa que las observaciones pertenezcan a una persona.
    entity_ids = Column(MutableList.as_mutable(JSONB), default=list, nullable=False)

    summary = Column(Text, nullable=True)

    # Aristas que explican por qué estas observaciones comparten espacio.
    evidence = Column(MutableDict.as_mutable(JSONB), default=dict)

    investigation = relationship("Investigation", back_populates="correlation_groups")
