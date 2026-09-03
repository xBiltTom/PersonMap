import uuid
from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from app.core.database import Base


class AwarenessSurvey(Base):
    __tablename__ = "awareness_surveys"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False)

    # Pre-exposure perception (1-5: 1 = "no me preocupaba", 5 = "muy preocupado")
    pre_awareness = Column(Integer, default=1, nullable=False)
    # Post-exposure perception (1-5)
    post_awareness = Column(Integer, default=5, nullable=False)

    reused_alias = Column(Boolean, default=True, nullable=False)
    knew_commit_leak = Column(Boolean, default=False, nullable=False)
    will_change_habits = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    investigation = relationship("Investigation")
