"""deal referral_preclose_reminder_sent

Revision ID: 029
Revises: 028
Create Date: 2026-03-28 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "deals",
        sa.Column("referral_preclose_reminder_sent", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.alter_column("deals", "referral_preclose_reminder_sent", server_default=None)


def downgrade() -> None:
    op.drop_column("deals", "referral_preclose_reminder_sent")
