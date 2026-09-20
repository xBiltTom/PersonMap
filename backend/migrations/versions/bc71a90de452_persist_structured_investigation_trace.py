"""persist structured investigation trace

Revision ID: bc71a90de452
Revises: 6b2bafee7d01
Create Date: 2026-09-20 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "bc71a90de452"
down_revision: Union[str, Sequence[str], None] = "6b2bafee7d01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tool_executions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_name", sa.String(length=100), nullable=False),
        sa.Column("tool_description", sa.String(length=255), nullable=True),
        sa.Column("engine", sa.String(length=50), nullable=False),
        sa.Column("engine_layer", sa.String(length=50), nullable=True),
        sa.Column("round_index", sa.Integer(), nullable=True),
        sa.Column("turn_index", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("findings_count", sa.Integer(), nullable=False),
        sa.Column("input_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_tool_executions_investigation_id", "tool_executions", ["investigation_id"])

    op.create_table(
        "investigation_trace_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("engine", sa.String(length=50), nullable=False),
        sa.Column("engine_layer", sa.String(length=50), nullable=True),
        sa.Column("round_index", sa.Integer(), nullable=True),
        sa.Column("turn_index", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_investigation_trace_events_investigation_id", "investigation_trace_events", ["investigation_id"])

    op.create_table(
        "entity_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("investigation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tool_execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("evidence_urls", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.ForeignKeyConstraint(["entity_id"], ["entities.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["investigation_id"], ["investigations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tool_execution_id"], ["tool_executions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_entity_observations_entity_id", "entity_observations", ["entity_id"])
    op.create_index("ix_entity_observations_investigation_id", "entity_observations", ["investigation_id"])
    op.create_index("ix_entity_observations_tool_execution_id", "entity_observations", ["tool_execution_id"])


def downgrade() -> None:
    op.drop_index("ix_entity_observations_tool_execution_id", table_name="entity_observations")
    op.drop_index("ix_entity_observations_investigation_id", table_name="entity_observations")
    op.drop_index("ix_entity_observations_entity_id", table_name="entity_observations")
    op.drop_table("entity_observations")
    op.drop_index("ix_investigation_trace_events_investigation_id", table_name="investigation_trace_events")
    op.drop_table("investigation_trace_events")
    op.drop_index("ix_tool_executions_investigation_id", table_name="tool_executions")
    op.drop_table("tool_executions")
