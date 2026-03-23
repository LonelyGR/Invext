"""add admin login events

Revision ID: 021
Revises: 020
Create Date: 2026-03-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "admin_login_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("admin_token_id", sa.Integer(), nullable=True),
        sa.Column("success", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["admin_token_id"], ["admin_tokens.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_admin_login_events_admin_token_id", "admin_login_events", ["admin_token_id"], unique=False)
    op.create_index("ix_admin_login_events_success", "admin_login_events", ["success"], unique=False)
    op.create_index("ix_admin_login_events_created_at", "admin_login_events", ["created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_admin_login_events_created_at", table_name="admin_login_events")
    op.drop_index("ix_admin_login_events_success", table_name="admin_login_events")
    op.drop_index("ix_admin_login_events_admin_token_id", table_name="admin_login_events")
    op.drop_table("admin_login_events")
