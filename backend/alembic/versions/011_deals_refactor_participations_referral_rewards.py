"""Deals refactor: new deal fields, deal_participations, referral_rewards.

Revision ID: 011
Revises: 010
Create Date: 2026-02-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Добавляем новые колонки в deals
    op.add_column("deals", sa.Column("title", sa.String(255), nullable=True))
    op.add_column("deals", sa.Column("start_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deals", sa.Column("end_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "deals",
        sa.Column("profit_percent", sa.Numeric(5, 2), nullable=True),
    )
    op.add_column(
        "deals",
        sa.Column("referral_processed", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "deals",
        sa.Column("close_notification_sent", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "deals",
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.add_column(
        "deals",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    # Делаем старые колонки nullable для совместимости
    op.alter_column(
        "deals",
        "percent",
        existing_type=sa.Numeric(5, 2),
        nullable=True,
    )
    op.alter_column(
        "deals",
        "opened_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=True,
    )

    # Backfill: для существующих строк status open -> active, finished -> completed
    op.execute(
        "UPDATE deals SET status = 'active' WHERE status = 'open'"
    )
    op.execute(
        "UPDATE deals SET status = 'completed' WHERE status = 'finished'"
    )

    # deal_participations
    op.create_table(
        "deal_participations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("deal_id", "user_id", name="uq_deal_participations_deal_user"),
    )
    op.create_index("ix_deal_participations_deal_id", "deal_participations", ["deal_id"], unique=False)
    op.create_index("ix_deal_participations_user_id", "deal_participations", ["user_id"], unique=False)

    # referral_rewards
    op.create_table(
        "referral_rewards",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("deal_id", sa.Integer(), nullable=False),
        sa.Column("from_user_id", sa.Integer(), nullable=False),
        sa.Column("to_user_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("amount", sa.Numeric(18, 6), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="paid"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["deal_id"], ["deals.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["from_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_referral_rewards_deal_id", "referral_rewards", ["deal_id"], unique=False)
    op.create_index("ix_referral_rewards_from_user_id", "referral_rewards", ["from_user_id"], unique=False)
    op.create_index("ix_referral_rewards_to_user_id", "referral_rewards", ["to_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_referral_rewards_to_user_id", table_name="referral_rewards")
    op.drop_index("ix_referral_rewards_from_user_id", table_name="referral_rewards")
    op.drop_index("ix_referral_rewards_deal_id", table_name="referral_rewards")
    op.drop_table("referral_rewards")

    op.drop_index("ix_deal_participations_user_id", table_name="deal_participations")
    op.drop_index("ix_deal_participations_deal_id", table_name="deal_participations")
    op.drop_table("deal_participations")

    op.alter_column(
        "deals",
        "opened_at",
        existing_type=sa.DateTime(timezone=True),
        nullable=False,
    )
    op.alter_column(
        "deals",
        "percent",
        existing_type=sa.Numeric(5, 2),
        nullable=False,
    )

    op.drop_column("deals", "updated_at")
    op.drop_column("deals", "created_at")
    op.drop_column("deals", "close_notification_sent")
    op.drop_column("deals", "referral_processed")
    op.drop_column("deals", "profit_percent")
    op.drop_column("deals", "end_at")
    op.drop_column("deals", "start_at")
    op.drop_column("deals", "title")
