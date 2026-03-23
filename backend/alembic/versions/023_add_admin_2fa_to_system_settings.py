"""add admin 2fa fields to system_settings

Revision ID: 023
Revises: 022
Create Date: 2026-03-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("admin_2fa_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "system_settings",
        sa.Column("admin_2fa_secret", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "admin_2fa_secret")
    op.drop_column("system_settings", "admin_2fa_enabled")
