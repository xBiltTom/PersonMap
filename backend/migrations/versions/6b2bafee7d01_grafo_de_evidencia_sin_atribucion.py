"""grafo de evidencia sin atribucion

Revision ID: 6b2bafee7d01
Revises: 26928f6d91e3
Create Date: 2026-09-15 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "6b2bafee7d01"
down_revision: Union[str, Sequence[str], None] = "26928f6d91e3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Las cifras de atribución y la verificación binaria se eliminan en vez de
    # reinterpretar datos históricos como decisiones humanas.
    op.drop_column("entities", "scorer_version")
    op.drop_column("entities", "identity_score")
    op.drop_column("entities", "existence_confidence")
    op.drop_column("entities", "verification_notes")
    op.drop_column("entities", "verified")
    op.drop_column("entities", "confidence")
    op.drop_column("investigations", "risk_score")

    op.drop_index("ix_identity_clusters_investigation_id", table_name="identity_clusters")
    op.rename_table("identity_clusters", "correlation_groups")
    op.drop_column("correlation_groups", "confidence")
    op.drop_column("correlation_groups", "scoring_breakdown")
    op.alter_column("correlation_groups", "reasoning", new_column_name="summary")
    op.add_column(
        "correlation_groups",
        sa.Column("evidence", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_correlation_groups_investigation_id", "correlation_groups", ["investigation_id"])

    op.drop_column("relationships", "strength")
    op.add_column(
        "relationships",
        sa.Column("supports_group", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("relationships", "supports_group", server_default=None)


def downgrade() -> None:
    op.add_column("investigations", sa.Column("risk_score", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("investigations", "risk_score", server_default=None)
    op.drop_column("relationships", "supports_group")
    op.add_column("relationships", sa.Column("strength", sa.Float(), nullable=False, server_default="0"))
    op.alter_column("relationships", "strength", server_default=None)

    op.drop_index("ix_correlation_groups_investigation_id", table_name="correlation_groups")
    op.drop_column("correlation_groups", "evidence")
    op.alter_column("correlation_groups", "summary", new_column_name="reasoning")
    op.add_column("correlation_groups", sa.Column("scoring_breakdown", postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column("correlation_groups", sa.Column("confidence", sa.Float(), nullable=False, server_default="0"))
    op.alter_column("correlation_groups", "confidence", server_default=None)
    op.rename_table("correlation_groups", "identity_clusters")
    op.create_index("ix_identity_clusters_investigation_id", "identity_clusters", ["investigation_id"])

    op.add_column("entities", sa.Column("confidence", sa.Float(), nullable=False, server_default="0"))
    op.add_column("entities", sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("entities", sa.Column("verification_notes", sa.Text(), nullable=True))
    op.add_column("entities", sa.Column("existence_confidence", sa.Float(), nullable=True))
    op.add_column("entities", sa.Column("identity_score", sa.Float(), nullable=True))
    op.add_column("entities", sa.Column("scorer_version", sa.String(length=20), nullable=True))
    op.alter_column("entities", "confidence", server_default=None)
    op.alter_column("entities", "verified", server_default=None)
