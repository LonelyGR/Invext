"""Remove NOWPayments: drop nowpayments_payments table and related_payment_id from ledger_transactions

Revision ID: 005
Revises: 004
Create Date: 2026-02-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop FK and column from ledger_transactions
    op.drop_constraint(
        "ledger_transactions_related_payment_id_fkey",
        "ledger_transactions",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_ledger_transactions_related_payment_id"),
        table_name="ledger_transactions",
    )
    op.drop_column("ledger_transactions", "related_payment_id")

    # Drop nowpayments_payments table
    op.drop_index(
        op.f("ix_nowpayments_payments_user_id"),
        table_name="nowpayments_payments",
    )
    op.drop_table("nowpayments_payments")


def downgrade() -> None:
    op.create_table(
        "nowpayments_payments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount_usdt", sa.Numeric(18, 2), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("nowpayments_payment_id", sa.String(128), nullable=False),
        sa.Column("invoice_url", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("credited_at", sa.DateTime(timezone=True), nullable=True),
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

    op.add_column(
        "ledger_transactions",
        sa.Column("related_payment_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "ledger_transactions_related_payment_id_fkey",
        "ledger_transactions",
        "nowpayments_payments",
        ["related_payment_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_ledger_transactions_related_payment_id"),
        "ledger_transactions",
        ["related_payment_id"],
        unique=False,
    )
