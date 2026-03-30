"""withdraw_requests.decided_by BIGINT для telegram_id > int32

Revision ID: 030
Revises: 029
Create Date: 2026-03-30 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "withdraw_requests",
        "decided_by",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "withdraw_requests",
        "decided_by",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="decided_by::integer",
    )
