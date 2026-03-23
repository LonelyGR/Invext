"""add broadcast messages and deliveries

Revision ID: 017
Revises: 016
Create Date: 2026-03-13 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "broadcast_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("text_html", sa.Text(), nullable=False),
        sa.Column("image_path", sa.String(length=512), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("total_recipients", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sent_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_broadcast_messages_status", "broadcast_messages", ["status"], unique=False)

    op.create_table(
        "broadcast_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("broadcast_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["broadcast_id"], ["broadcast_messages.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("broadcast_id", "user_id", name="uq_broadcast_delivery_per_user"),
    )
    op.create_index("ix_broadcast_deliveries_broadcast_id", "broadcast_deliveries", ["broadcast_id"], unique=False)
    op.create_index("ix_broadcast_deliveries_user_id", "broadcast_deliveries", ["user_id"], unique=False)
    op.create_index("ix_broadcast_deliveries_telegram_id", "broadcast_deliveries", ["telegram_id"], unique=False)
    op.create_index("ix_broadcast_deliveries_status", "broadcast_deliveries", ["status"], unique=False)
    op.create_index("ix_broadcast_deliveries_next_attempt_at", "broadcast_deliveries", ["next_attempt_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_broadcast_deliveries_next_attempt_at", table_name="broadcast_deliveries")
    op.drop_index("ix_broadcast_deliveries_status", table_name="broadcast_deliveries")
    op.drop_index("ix_broadcast_deliveries_telegram_id", table_name="broadcast_deliveries")
    op.drop_index("ix_broadcast_deliveries_user_id", table_name="broadcast_deliveries")
    op.drop_index("ix_broadcast_deliveries_broadcast_id", table_name="broadcast_deliveries")
    op.drop_table("broadcast_deliveries")
    op.drop_index("ix_broadcast_messages_status", table_name="broadcast_messages")
    op.drop_table("broadcast_messages")
