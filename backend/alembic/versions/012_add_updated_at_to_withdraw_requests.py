"""Add updated_at column to withdraw_requests

Revision ID: 012_add_updated_at_to_withdraw_requests
Revises: 011_deals_refactor_participations_referral_rewards
Create Date: 2026-03-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "012_add_updated_at_to_withdraw_requests"
down_revision: Union[str, None] = "011_deals_refactor_participations_referral_rewards"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "withdraw_requests",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("withdraw_requests", "updated_at")

