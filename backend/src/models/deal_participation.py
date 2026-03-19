"""
Участие пользователя в сделке. Один пользователь — одно участие в одной сделке (unique deal_id, user_id).
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base

if TYPE_CHECKING:
    from src.models.deal import Deal
    from src.models.user import User

PARTICIPATION_STATUS_ACTIVE = "active"
PARTICIPATION_STATUS_IN_PROGRESS = "in_progress_payout"
PARTICIPATION_STATUS_COMPLETED = "completed"


class DealParticipation(Base):
    """Одно участие пользователя в сделке (одна запись на пару deal_id + user_id)."""

    __tablename__ = "deal_participations"
    __table_args__ = (UniqueConstraint("deal_id", "user_id", name="uq_deal_participations_deal_user"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default=PARTICIPATION_STATUS_ACTIVE, index=True,
    )
    profit_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 6), nullable=True)
    payout_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    deal: Mapped["Deal"] = relationship("Deal", back_populates="participations")
    user: Mapped["User"] = relationship("User", back_populates="deal_participations")

    def __repr__(self) -> str:
        return (
            f"<DealParticipation id={self.id} deal_id={self.deal_id} "
            f"user_id={self.user_id} amount={self.amount} status={self.status}>"
        )
