import uuid
from sqlalchemy import Boolean, Column, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import relationship
from app.core.database import Base


class Relationship(Base):
    __tablename__ = "relationships"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False, index=True)

    source_entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)
    target_entity_id = Column(UUID(as_uuid=True), ForeignKey("entities.id", ondelete="CASCADE"), nullable=False, index=True)

    # Una arista describe un hecho observado entre dos nodos; nunca atribuye
    # propiedad o identidad a una persona.
    relation_type = Column(String(50), default="linked_to", nullable=False)
    # Solo las relaciones deterministas forman grupos visuales. Las demás se
    # muestran como contexto para que el analista las valore por su cuenta.
    supports_group = Column(Boolean, default=False, nullable=False)
    evidence = Column(MutableDict.as_mutable(JSONB), default=dict)

    investigation = relationship("Investigation", back_populates="relationships")
    source_entity = relationship("Entity", foreign_keys=[source_entity_id])
    target_entity = relationship("Entity", foreign_keys=[target_entity_id])
