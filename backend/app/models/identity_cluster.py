import uuid
from sqlalchemy import Column, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.mutable import MutableDict, MutableList
from sqlalchemy.orm import relationship
from app.core.database import Base


class IdentityCluster(Base):
    __tablename__ = "identity_clusters"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    investigation_id = Column(UUID(as_uuid=True), ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False)

    # Label: "Identidad Principal (Confirmada)", "Posible Homónimo #1"
    label = Column(String(255), nullable=False)

    # Confidence score (0.0 to 1.0)
    confidence = Column(Float, default=0.0, nullable=False)

    # List of entity UUID strings that belong to this identity cluster
    entity_ids = Column(MutableList.as_mutable(JSONB), default=list, nullable=False)

    # Reasoning / Explanation
    reasoning = Column(Text, nullable=True)

    # Breakdown: {"name_match": 0.95, "email_crosslink": 1.0, "bio_university": 0.90}
    scoring_breakdown = Column(MutableDict.as_mutable(JSONB), default=dict)

    investigation = relationship("Investigation", back_populates="identity_clusters")
