"""set referral_rewards.status default to pending

Revision ID: 035
Revises: 034
Create Date: 2026-04-14

"""
from alembic import op
import sqlalchemy as sa


revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "referral_rewards",
        "status",
        existing_type=sa.String(length=16),
        server_default="pending",
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "referral_rewards",
        "status",
        existing_type=sa.String(length=16),
        server_default="paid",
        existing_nullable=False,
    )
