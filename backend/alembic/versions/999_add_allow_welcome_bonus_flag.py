"""add allow_welcome_bonus flag to system_settings

Revision ID: 999_add_allow_welcome_bonus_flag
Revises: 015_add_allow_deposits_to_system_settings
Create Date: 2026-03-31
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "999_add_allow_welcome_bonus_flag"
down_revision: Union[str, None] = "015_add_allow_deposits_to_system_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column("allow_welcome_bonus", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "allow_welcome_bonus")

