import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import relationship
from app.core.database import Base


class Entity(Base):
    __tablename__ = "entities"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # PostgreSQL no indexa automáticamente las claves foráneas, y todas las
    # consultas del expediente filtran por esta columna.
    investigation_id = Column(
        UUID(as_uuid=True),
        ForeignKey("investigations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Entity type: 'social_account', 'email', 'phone', 'academic', 'breach', 'search_mention'
    entity_type = Column(String(50), nullable=False)

    # Platform: 'instagram', 'github', 'linkedin', 'google_scholar', 'pastebin', etc.
    platform = Column(String(100), nullable=True)

    # Core value: URL, handle, email string, paper title
    value = Column(Text, nullable=False)
    display_name = Column(String(255), nullable=True)

    # Rich metadata: bio, photo_url, extracted links, emails, etc.
    # MutableDict: sin esto, las mutaciones in-place posteriores al flush no las
    # detecta SQLAlchemy y nunca llegan a la BD (p. ej. el flag avatar_correlated
    # que escribe identity/resolver.py tras puntuar las entidades).
    metadata_info = Column(MutableDict.as_mutable(JSONB), default=dict)

    # Confianza mostrada al usuario. Se conserva por compatibilidad y porque es
    # la que ordena las vistas; es el máximo entre las dos métricas de abajo.
    confidence = Column(Float, default=0.5, nullable=False)

    # --- Dos preguntas distintas, antes colapsadas en una sola columna -------
    #
    # `existence_confidence` responde "¿existe realmente esta cuenta?": la
    # certeza de detección que reporta la herramienta OSINT.
    #
    # `identity_score` responde "¿es del objetivo?": la probabilidad posterior
    # del modelo Fellegi-Sunter.
    #
    # Son ortogonales: un perfil puede existir con total certeza y no ser de la
    # persona investigada. Mezclarlas con `max()` hacía que la confianza fija
    # que cada herramienta escribe a mano (0.85-1.0) tapara siempre al modelo
    # probabilístico, de modo que los clusters de identidad los decidía esa
    # constante y no el modelo que sustenta el artículo.
    existence_confidence = Column(Float, nullable=True)
    identity_score = Column(Float, nullable=True)
    # Versión del modelo que produjo `identity_score`, para que un recalibrado
    # no vuelva incomparables las investigaciones anteriores.
    scorer_version = Column(String(20), nullable=True)

    # Manual verification state by user
    verified = Column(Boolean, default=False, nullable=False)
    verification_notes = Column(Text, nullable=True)

    # Source tool that discovered this entity
    source_tool = Column(String(100), nullable=False)
    discovered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    investigation = relationship("Investigation", back_populates="entities")
