"""default profit percent for new deals in system_settings

Revision ID: 034
Revises: 033
Create Date: 2026-04-11

"""
from alembic import op
import sqlalchemy as sa


revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "deal_default_profit_percent",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="3.00",
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "deal_default_profit_percent")
