"""Persist deterministic reconstruction snapshots and Graph V2.

Revision ID: c62d914ae306
Revises: bf781b42de01
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

revision = 'c62d914ae306'
down_revision = 'bf781b42de01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('reconstruction_runs',
        sa.Column('id', pg.UUID(as_uuid=True), primary_key=True),
        sa.Column('investigation_id', pg.UUID(as_uuid=True), sa.ForeignKey('investigations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('dataset_hash', sa.String(64), nullable=False),
        sa.Column('exposure_hash', sa.String(64), nullable=False),
        sa.Column('input_hash', sa.String(64), nullable=False),
        sa.Column('analysis_version', sa.String(40), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('snapshot', pg.JSONB(), nullable=False),
        sa.Column('config', pg.JSONB(), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('investigation_id', 'input_hash', name='uq_reconstruction_input'),
        sa.CheckConstraint("status IN ('completed', 'partial')", name='ck_reconstruction_terminal'),
    )
    op.create_index('ix_reconstruction_runs_investigation_id', 'reconstruction_runs', ['investigation_id'])


def downgrade():
    op.drop_table('reconstruction_runs')
