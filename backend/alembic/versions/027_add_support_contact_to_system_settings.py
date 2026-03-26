"""add support_contact to system_settings

Revision ID: 027
Revises: 026
Create Date: 2026-03-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "027"
down_revision = "026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("system_settings", sa.Column("support_contact", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("system_settings", "support_contact")
