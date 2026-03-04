"""user_wallets table

Revision ID: 002
Revises: 001
Create Date: 2025-02-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_wallets",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("currency", sa.String(10), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(op.f("ix_user_wallets_user_id"), "user_wallets", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_wallets_user_id"), table_name="user_wallets")
    op.drop_table("user_wallets")
