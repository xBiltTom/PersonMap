"""Persist web-to-MCP reconstruction handoffs.

Revision ID: e31d4598a207
Revises: c62d914ae306
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = 'e31d4598a207'
down_revision = 'c62d914ae306'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('reconstruction_requests',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('investigation_id', pg.UUID(as_uuid=True), sa.ForeignKey('investigations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('dataset_hash', sa.String(64), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('base_snapshot', pg.JSONB(), nullable=False),
        sa.Column('result_snapshot', pg.JSONB()),
        sa.Column('progress', pg.JSONB(), nullable=False),
        sa.Column('claim_token', pg.UUID(as_uuid=True)),
        sa.Column('client', sa.String(100)), sa.Column('model', sa.String(200)),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('pending', 'running', 'completed', 'failed', 'cancelled')", name='ck_reconstruction_request_status'))
    op.create_index('ix_reconstruction_requests_investigation_id', 'reconstruction_requests', ['investigation_id'])
    op.create_index('uq_reconstruction_active_request', 'reconstruction_requests', ['investigation_id'], unique=True,
                    postgresql_where=sa.text("status IN ('pending', 'running')"))


def downgrade():
    op.drop_table('reconstruction_requests')
