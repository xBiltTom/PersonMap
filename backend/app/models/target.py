import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, DateTime, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class Target(Base):
    __tablename__ = "targets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Input attributes - at least one required to launch scan
    full_name = Column(String(255), nullable=True)
    email = Column(String(255), nullable=True)
    username = Column(String(255), nullable=True)
    phone = Column(String(50), nullable=True)
    dni = Column(String(50), nullable=True)
    university = Column(String(255), nullable=True)

    # Optional description for LLM reasoning / context
    description = Column(Text, nullable=True)

    extra_data = Column(JSONB, default=dict)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    investigations = relationship("Investigation", back_populates="target", cascade="all, delete-orphan")
