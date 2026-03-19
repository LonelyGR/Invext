"""add status, profit_amount, payout_at to deal_participations

Revision ID: 014
Revises: 013
Create Date: 2026-03-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "014"
down_revision = "013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deal_participations",
        sa.Column("status", sa.String(24), nullable=False, server_default="active"),
    )
    op.add_column(
        "deal_participations",
        sa.Column("profit_amount", sa.Numeric(18, 6), nullable=True),
    )
    op.add_column(
        "deal_participations",
        sa.Column("payout_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_deal_participations_status", "deal_participations", ["status"])

    # Mark existing participations from closed deals as completed
    op.execute(
        """
        UPDATE deal_participations
        SET status = 'completed'
        WHERE deal_id IN (
            SELECT id FROM deals WHERE status IN ('closed', 'completed')
        )
        """
    )


def downgrade() -> None:
    op.drop_index("ix_deal_participations_status", table_name="deal_participations")
    op.drop_column("deal_participations", "payout_at")
    op.drop_column("deal_participations", "profit_amount")
    op.drop_column("deal_participations", "status")
