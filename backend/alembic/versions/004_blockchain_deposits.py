"""Legacy blockchain deposits migration (now a no-op).

Revision ID: 004
Revises: 003
Create Date: 2026-02-23

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Blockchain-based deposits are no longer used.
    # This migration is kept as a no-op to preserve Alembic history.
    return


def downgrade() -> None:
    # No-op downgrade: legacy blockchain tables are not recreated.
    return
