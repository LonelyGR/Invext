from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base

if TYPE_CHECKING:
    from src.models.deal import Deal
    from src.models.user import User


class DealInvestment(Base):
    """Инвестиция пользователя в конкретную сделку."""

    __tablename__ = "deal_investments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    deal_id: Mapped[int] = mapped_column(ForeignKey("deals.id"), nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    profit_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(18, 6), nullable=True
    )

    # active — ожидает начисления прибыли; paid — тело и прибыль выплачены
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    deal: Mapped["Deal"] = relationship("Deal", back_populates="investments")
    user: Mapped["User"] = relationship("User", back_populates="deal_investments")

    def __repr__(self) -> str:
        return (
            f"<DealInvestment id={self.id} deal_id={self.deal_id} "
            f"user_id={self.user_id} amount={self.amount} status={self.status}>"
        )

