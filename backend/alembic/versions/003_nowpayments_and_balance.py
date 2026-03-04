"""
Add users.balance_usdt, nowpayments_payments and ledger_transactions

Revision ID: 003
Revises: 002
Create Date: 2026-02-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # users.balance_usdt
    op.add_column(
        "users",
        sa.Column(
            "balance_usdt",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
    )

    # nowpayments_payments
    op.create_table(
        "nowpayments_payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount_usdt", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("nowpayments_payment_id", sa.String(128), nullable=False),
        sa.Column("invoice_url", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="created",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "credited_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.UniqueConstraint("nowpayments_payment_id"),
    )
    op.create_index(
        op.f("ix_nowpayments_payments_user_id"),
        "nowpayments_payments",
        ["user_id"],
        unique=False,
    )

    # ledger_transactions
    op.create_table(
        "ledger_transactions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("amount_usdt", sa.Numeric(18, 2), nullable=False),
        sa.Column("related_payment_id", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["related_payment_id"], ["nowpayments_payments.id"]),
    )
    op.create_index(
        op.f("ix_ledger_transactions_user_id"),
        "ledger_transactions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_ledger_transactions_related_payment_id"),
        "ledger_transactions",
        ["related_payment_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_ledger_transactions_related_payment_id"),
        table_name="ledger_transactions",
    )
    op.drop_index(
        op.f("ix_ledger_transactions_user_id"),
        table_name="ledger_transactions",
    )
    op.drop_table("ledger_transactions")

    op.drop_index(
        op.f("ix_nowpayments_payments_user_id"),
        table_name="nowpayments_payments",
    )
    op.drop_table("nowpayments_payments")

    op.drop_column("users", "balance_usdt")

