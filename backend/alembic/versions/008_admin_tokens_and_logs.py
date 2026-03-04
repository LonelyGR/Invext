"""Admin tokens and logs for dashboard.

Revision ID: 008
Revises: 007
Create Date: 2026-02-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "admin_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_by", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_admin_tokens_token"),
    )
    op.create_index(
        op.f("ix_admin_tokens_token"),
        "admin_tokens",
        ["token"],
        unique=False,
    )

    op.create_table(
        "admin_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("admin_token_id", sa.Integer(), nullable=False),
        sa.Column("action_type", sa.String(length=32), nullable=False),
        sa.Column("entity_type", sa.String(length=32), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["admin_token_id"],
            ["admin_tokens.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        op.f("ix_admin_logs_admin_token_id"),
        "admin_logs",
        ["admin_token_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_admin_logs_admin_token_id"),
        table_name="admin_logs",
    )
    op.drop_table("admin_logs")

    op.drop_index(
        op.f("ix_admin_tokens_token"),
        table_name="admin_tokens",
    )
    op.drop_table("admin_tokens")

