"""add scheduled_at to broadcast_messages

Revision ID: 019
Revises: 018
Create Date: 2026-03-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "broadcast_messages",
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_broadcast_messages_scheduled_at", "broadcast_messages", ["scheduled_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_broadcast_messages_scheduled_at", table_name="broadcast_messages")
    op.drop_column("broadcast_messages", "scheduled_at")
