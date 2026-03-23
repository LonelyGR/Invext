"""add audience_segment to broadcast_messages

Revision ID: 020
Revises: 019
Create Date: 2026-03-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "broadcast_messages",
        sa.Column("audience_segment", sa.String(length=32), nullable=False, server_default="all"),
    )


def downgrade() -> None:
    op.drop_column("broadcast_messages", "audience_segment")
