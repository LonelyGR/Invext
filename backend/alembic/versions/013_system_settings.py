"""system settings singleton table

Revision ID: 013
Revises: 012
Create Date: 2026-03-12 00:00:00.000000
"""

from decimal import Decimal

from alembic import op
import sqlalchemy as sa


revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("min_deposit_usdt", sa.Numeric(18, 2), nullable=False, server_default="10"),
        sa.Column("max_deposit_usdt", sa.Numeric(18, 2), nullable=False, server_default="100000"),
        sa.Column("min_withdraw_usdt", sa.Numeric(18, 2), nullable=False, server_default="10"),
        sa.Column("max_withdraw_usdt", sa.Numeric(18, 2), nullable=False, server_default="100000"),
        sa.Column("min_invest_usdt", sa.Numeric(18, 2), nullable=False, server_default="50"),
        sa.Column("max_invest_usdt", sa.Numeric(18, 2), nullable=False, server_default="100000"),
        sa.Column("deal_amount_usdt", sa.Numeric(18, 2), nullable=False, server_default="50"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    # Вставляем одну запись по умолчанию (singleton).
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO system_settings (
                min_deposit_usdt,
                max_deposit_usdt,
                min_withdraw_usdt,
                max_withdraw_usdt,
                min_invest_usdt,
                max_invest_usdt,
                deal_amount_usdt
            ) VALUES (:min_dep, :max_dep, :min_wd, :max_wd, :min_inv, :max_inv, :deal_amt)
            """
        ),
        {
            "min_dep": Decimal("10"),
            "max_dep": Decimal("100000"),
            "min_wd": Decimal("10"),
            "max_wd": Decimal("100000"),
            "min_inv": Decimal("50"),
            "max_inv": Decimal("100000"),
            "deal_amt": Decimal("50"),
        },
    )


def downgrade() -> None:
    op.drop_table("system_settings")

