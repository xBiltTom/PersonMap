"""Restrict persisted human review decisions to supported values.

Revision ID: a41b9c2e7d63
Revises: 4f0d2b61a9c7
"""
from alembic import op


revision = "a41b9c2e7d63"
down_revision = "4f0d2b61a9c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_check_constraint(
        "ck_review_decisions_valid_decision",
        "review_decisions",
        "decision IN ('confirmed', 'rejected', 'uncertain')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_review_decisions_valid_decision",
        "review_decisions",
        type_="check",
    )
