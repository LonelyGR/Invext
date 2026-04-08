"""add unique constraint for referral reward idempotency

Revision ID: 031
Revises: 030
Create Date: 2026-04-07 00:00:00.000000
"""

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Безопасность для прод-данных:
    # если исторически уже есть дубли одной и той же награды, оставляем
    # самую раннюю запись (минимальный id), остальные удаляем.
    op.execute(
        """
        WITH ranked AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY deal_id, from_user_id, to_user_id, level
                    ORDER BY id
                ) AS rn
            FROM referral_rewards
        )
        DELETE FROM referral_rewards rr
        USING ranked r
        WHERE rr.id = r.id
          AND r.rn > 1
        """
    )

    op.create_unique_constraint(
        "uq_referral_rewards_deal_from_to_level",
        "referral_rewards",
        ["deal_id", "from_user_id", "to_user_id", "level"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_referral_rewards_deal_from_to_level",
        "referral_rewards",
        type_="unique",
    )

