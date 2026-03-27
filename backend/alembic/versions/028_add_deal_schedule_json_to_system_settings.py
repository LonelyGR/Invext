"""add deal_schedule_json to system_settings

Revision ID: 028
Revises: 027
Create Date: 2026-03-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("system_settings", sa.Column("deal_schedule_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("system_settings", "deal_schedule_json")
