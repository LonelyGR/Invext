"""
Заявка на пополнение: пользователь, валюта, сумма, статус.
"""
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base

if TYPE_CHECKING:
    from src.models.user import User


class DepositRequest(Base):
    __tablename__ = "deposit_requests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)  # USDT, USDC
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    comment: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # tx_hash позже
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[Optional[int]] = mapped_column(nullable=True)  # telegram_id админа

    user: Mapped["User"] = relationship("User", back_populates="deposit_requests")

    def __repr__(self) -> str:
        return f"<DepositRequest id={self.id} user_id={self.user_id} {self.currency} {self.amount} {self.status}>"
