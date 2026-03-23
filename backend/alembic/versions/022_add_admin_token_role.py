"""add role to admin_tokens

Revision ID: 022
Revises: 021
Create Date: 2026-03-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "admin_tokens",
        sa.Column("role", sa.String(length=16), nullable=False, server_default="admin"),
    )
    op.create_index("ix_admin_tokens_role", "admin_tokens", ["role"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_admin_tokens_role", table_name="admin_tokens")
    op.drop_column("admin_tokens", "role")
