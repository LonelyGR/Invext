"""welcome bonus amount and eligibility criteria in system_settings

Revision ID: 033
Revises: 032
Create Date: 2026-04-11

"""
from alembic import op
import sqlalchemy as sa


revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "welcome_bonus_amount_usdt",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="100",
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "welcome_bonus_for_new_users",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "welcome_bonus_for_zero_balance",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "system_settings",
        sa.Column(
            "welcome_bonus_new_user_days",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "welcome_bonus_new_user_days")
    op.drop_column("system_settings", "welcome_bonus_for_zero_balance")
    op.drop_column("system_settings", "welcome_bonus_for_new_users")
    op.drop_column("system_settings", "welcome_bonus_amount_usdt")
