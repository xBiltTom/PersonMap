"""Persist explainable Exposure Lens reports and content classifications.

Revision ID: bf781b42de01
Revises: a41b9c2e7d63
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg


revision = "bf781b42de01"
down_revision = "a41b9c2e7d63"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "exposure_runs",
        sa.Column("id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", pg.UUID(as_uuid=True),
                  sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_hash", sa.String(length=64), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("analysis_version", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("config", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary", pg.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("findings", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("top_exposures", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("analyzed_content_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_content_count", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'partial', 'failed')",
            name="ck_exposure_runs_valid_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "investigation_id", "dataset_hash", "analysis_version", "config_hash",
            name="uq_exposure_run_dataset_config",
        ),
    )
    op.create_index("ix_exposure_runs_investigation_id", "exposure_runs", ["investigation_id"])
    op.create_index("ix_exposure_runs_dataset_hash", "exposure_runs", ["dataset_hash"])

    op.create_table(
        "exposure_content_cache",
        sa.Column("id", pg.UUID(as_uuid=True), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("analysis_version", sa.String(length=40), nullable=False),
        sa.Column("config_hash", sa.String(length=64), nullable=False),
        sa.Column("model", sa.String(length=200), nullable=True),
        sa.Column("result", pg.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "content_hash", "analysis_version", "config_hash",
            name="uq_exposure_content_cache_key",
        ),
    )


def downgrade() -> None:
    op.drop_table("exposure_content_cache")
    op.drop_index("ix_exposure_runs_dataset_hash", table_name="exposure_runs")
    op.drop_index("ix_exposure_runs_investigation_id", table_name="exposure_runs")
    op.drop_table("exposure_runs")
