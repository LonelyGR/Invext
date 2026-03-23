"""add user block fields

Revision ID: 018
Revises: 017
Create Date: 2026-03-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("is_blocked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("blocked_reason", sa.Text(), nullable=True),
    )
    op.create_index("ix_users_is_blocked", "users", ["is_blocked"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_users_is_blocked", table_name="users")
    op.drop_column("users", "blocked_reason")
    op.drop_column("users", "is_blocked")
