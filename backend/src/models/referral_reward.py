"""
Реферальное начисление по сделке: от участника (from_user) к рефереру (to_user) за участие в одной сделке.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base

if TYPE_CHECKING:
    from src.models.deal import Deal
    from src.models.user import User

STATUS_PENDING = "pending"
STATUS_PAID = "paid"


class ReferralReward(Base):
    """Начисление реферального бонуса по сделке (to_user получил бонус за from_user на уровне level)."""

    __tablename__ = "referral_rewards"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True)
    from_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    to_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    level: Mapped[int] = mapped_column(nullable=False)  # 1..10
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_PAID)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    deal: Mapped["Deal"] = relationship("Deal", back_populates="referral_rewards")
    from_user: Mapped["User"] = relationship("User", foreign_keys=[from_user_id])
    to_user: Mapped["User"] = relationship("User", foreign_keys=[to_user_id])

    def __repr__(self) -> str:
        return (
            f"<ReferralReward id={self.id} deal_id={self.deal_id} "
            f"from={self.from_user_id} to={self.to_user_id} level={self.level} amount={self.amount}>"
        )
