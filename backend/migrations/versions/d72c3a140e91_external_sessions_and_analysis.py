"""External execution sessions and authored analysis.

Revision ID: d72c3a140e91
Revises: bc71a90de452
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = "d72c3a140e91"
down_revision = "bc71a90de452"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("investigations", sa.Column("execution_mode", sa.String(20), nullable=False, server_default="internal"))
    op.add_column("investigations", sa.Column("revision", sa.Integer(), nullable=False, server_default="0"))
    op.create_table("investigation_sessions",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("investigation_id", pg.UUID(as_uuid=True), sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client", sa.String(100), nullable=False),
        sa.Column("model", sa.String(200)),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)))
    op.create_index("ix_investigation_sessions_investigation_id", "investigation_sessions", ["investigation_id"])
    op.create_index("uq_active_investigation_session", "investigation_sessions", ["investigation_id"], unique=True, postgresql_where=sa.text("status = 'active'"))
    op.add_column("tool_executions", sa.Column("session_id", pg.UUID(as_uuid=True), sa.ForeignKey("investigation_sessions.id", ondelete="SET NULL")))
    op.add_column("tool_executions", sa.Column("input_fingerprint", sa.String(64)))
    op.create_index("ix_tool_executions_session_id", "tool_executions", ["session_id"])
    op.create_index("ix_tool_executions_input_fingerprint", "tool_executions", ["input_fingerprint"])
    op.create_table("analysis_notes",
        sa.Column("id", pg.UUID(as_uuid=True), primary_key=True),
        sa.Column("investigation_id", pg.UUID(as_uuid=True), sa.ForeignKey("investigations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("session_id", pg.UUID(as_uuid=True), sa.ForeignKey("investigation_sessions.id", ondelete="SET NULL")),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("author", sa.String(100), nullable=False),
        sa.Column("author_type", sa.String(20), nullable=False),
        sa.Column("evidence_urls", pg.JSONB(), nullable=False),
        sa.Column("entity_ids", pg.JSONB(), nullable=False),
        sa.Column("execution_ids", pg.JSONB(), nullable=False),
        sa.Column("details", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_index("ix_analysis_notes_investigation_id", "analysis_notes", ["investigation_id"])


def downgrade():
    op.drop_table("analysis_notes")
    op.drop_index("ix_tool_executions_input_fingerprint", "tool_executions")
    op.drop_index("ix_tool_executions_session_id", "tool_executions")
    op.drop_column("tool_executions", "input_fingerprint")
    op.drop_column("tool_executions", "session_id")
    op.drop_table("investigation_sessions")
    op.drop_column("investigations", "revision")
    op.drop_column("investigations", "execution_mode")
