"""add system settings versions table

Revision ID: 024
Revises: 023
Create Date: 2026-03-13 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "024"
down_revision = "023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings_versions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("admin_token_id", sa.Integer(), nullable=True),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("changes_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["admin_token_id"], ["admin_tokens.id"], ondelete="SET NULL"),
    )


def downgrade() -> None:
    op.drop_table("system_settings_versions")
