"""Payment invoices (NOWPayments), webhook events, ledger metadata.

Revision ID: 010
Revises: 009
Create Date: 2026-02-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # payment_invoices
    op.create_table(
        "payment_invoices",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="nowpayments"),
        sa.Column("order_id", sa.String(128), nullable=False),
        sa.Column("external_invoice_id", sa.String(128), nullable=True),
        sa.Column("invoice_url", sa.Text(), nullable=True),
        sa.Column("price_amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("price_currency", sa.String(16), nullable=False, server_default="usd"),
        sa.Column("pay_currency", sa.String(32), nullable=False, server_default="usdtbsc"),
        sa.Column("expected_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("actually_paid_amount", sa.Numeric(18, 8), nullable=True),
        sa.Column("network", sa.String(32), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="waiting"),
        sa.Column("is_balance_applied", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("order_id", name="uq_payment_invoices_order_id"),
    )
    op.create_index("ix_payment_invoices_user_id", "payment_invoices", ["user_id"], unique=False)
    op.create_index("ix_payment_invoices_order_id", "payment_invoices", ["order_id"], unique=True)
    op.create_index("ix_payment_invoices_external_invoice_id", "payment_invoices", ["external_invoice_id"], unique=False)
    op.create_index("ix_payment_invoices_status", "payment_invoices", ["status"], unique=False)
    op.create_index("ix_payment_invoices_user_status", "payment_invoices", ["user_id", "status"], unique=False)

    # payment_webhook_events
    op.create_table(
        "payment_webhook_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("external_event_id", sa.String(128), nullable=True),
        sa.Column("order_id", sa.String(128), nullable=True),
        sa.Column("payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("signature_header", sa.String(512), nullable=True),
        sa.Column("processing_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("processing_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_payment_webhook_events_provider", "payment_webhook_events", ["provider"], unique=False)
    op.create_index("ix_payment_webhook_events_external_event_id", "payment_webhook_events", ["external_event_id"], unique=False)
    op.create_index("ix_payment_webhook_events_order_id", "payment_webhook_events", ["order_id"], unique=False)
    op.create_index("ix_payment_webhook_events_processing_status", "payment_webhook_events", ["processing_status"], unique=False)

    # ledger_transactions: add provider, external_payment_id, metadata_json
    op.add_column("ledger_transactions", sa.Column("provider", sa.String(32), nullable=True))
    op.add_column("ledger_transactions", sa.Column("external_payment_id", sa.String(128), nullable=True))
    op.add_column(
        "ledger_transactions",
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_index("ix_ledger_transactions_provider", "ledger_transactions", ["provider"], unique=False)
    op.create_index("ix_ledger_transactions_external_payment_id", "ledger_transactions", ["external_payment_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ledger_transactions_external_payment_id", table_name="ledger_transactions")
    op.drop_index("ix_ledger_transactions_provider", table_name="ledger_transactions")
    op.drop_column("ledger_transactions", "metadata_json")
    op.drop_column("ledger_transactions", "external_payment_id")
    op.drop_column("ledger_transactions", "provider")

    op.drop_index("ix_payment_webhook_events_processing_status", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_order_id", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_external_event_id", table_name="payment_webhook_events")
    op.drop_index("ix_payment_webhook_events_provider", table_name="payment_webhook_events")
    op.drop_table("payment_webhook_events")

    op.drop_index("ix_payment_invoices_user_status", table_name="payment_invoices")
    op.drop_index("ix_payment_invoices_status", table_name="payment_invoices")
    op.drop_index("ix_payment_invoices_external_invoice_id", table_name="payment_invoices")
    op.drop_index("ix_payment_invoices_order_id", table_name="payment_invoices")
    op.drop_index("ix_payment_invoices_user_id", table_name="payment_invoices")
    op.drop_table("payment_invoices")
