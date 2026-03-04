"""Add deals and deal_investments tables.

Revision ID: 007
Revises: 006
Create Date: 2026-02-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "deals",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("percent", sa.Numeric(5, 2), nullable=False, server_default="3.00"),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column(
            "opened_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("number", name="uq_deals_number"),
    )
    op.create_index(op.f("ix_deals_number"), "deals", ["number"], unique=False)

    op.create_table(
        "deal_investments",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("profit_amount", sa.Numeric(18, 6), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="active",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        op.f("ix_deal_investments_deal_id"),
        "deal_investments",
        ["deal_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_deal_investments_user_id"),
        "deal_investments",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_deal_investments_user_id"), table_name="deal_investments"
    )
    op.drop_index(
        op.f("ix_deal_investments_deal_id"), table_name="deal_investments"
    )
    op.drop_table("deal_investments")

    op.drop_index(op.f("ix_deals_number"), table_name="deals")
    op.drop_table("deals")

