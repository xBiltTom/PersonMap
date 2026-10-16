"""Persist Verification Gate human decisions.

Revision ID: 4f0d2b61a9c7
Revises: d72c3a140e91
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


revision = "4f0d2b61a9c7"
down_revision = "d72c3a140e91"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "review_decisions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("investigation_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("entity_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("entities.id", ondelete="CASCADE"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("history", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.UniqueConstraint("investigation_id", "entity_id", name="uq_review_decision_entity"),
    )
    op.create_index("ix_review_decisions_investigation_id", "review_decisions", ["investigation_id"])
    op.create_index("ix_review_decisions_entity_id", "review_decisions", ["entity_id"])


def downgrade():
    op.drop_index("ix_review_decisions_entity_id", table_name="review_decisions")
    op.drop_index("ix_review_decisions_investigation_id", table_name="review_decisions")
    op.drop_table("review_decisions")
