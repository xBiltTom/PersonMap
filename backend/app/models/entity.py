import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, ForeignKey, String, Text
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

    # Source tool that discovered this entity
    source_tool = Column(String(100), nullable=False)
    discovered_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    investigation = relationship("Investigation", back_populates="entities")
