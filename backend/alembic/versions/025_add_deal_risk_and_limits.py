"""add deal risk and participation limits

Revision ID: 025
Revises: 024
Create Date: 2026-03-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deals", sa.Column("min_participation_usdt", sa.Numeric(18, 2), nullable=True))
    op.add_column("deals", sa.Column("max_participation_usdt", sa.Numeric(18, 2), nullable=True))
    op.add_column("deals", sa.Column("max_participants", sa.Integer(), nullable=True))
    op.add_column("deals", sa.Column("risk_level", sa.String(length=16), nullable=True))
    op.add_column("deals", sa.Column("risk_note", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("deals", "risk_note")
    op.drop_column("deals", "risk_level")
    op.drop_column("deals", "max_participants")
    op.drop_column("deals", "max_participation_usdt")
    op.drop_column("deals", "min_participation_usdt")
