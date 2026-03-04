"""
Ledger: одна запись = одна операция по балансу.
Баланс пользователя по валюте = сумма amount по транзакциям с status=COMPLETED и type DEPOSIT минус WITHDRAW.
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


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)  # DEPOSIT, WITHDRAW
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)  # всегда положительное
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # COMPLETED, CANCELED
    related_deposit_request_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    related_withdraw_request_id: Mapped[Optional[int]] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship("User", back_populates="wallet_transactions")

    def __repr__(self) -> str:
        return f"<WalletTransaction id={self.id} user_id={self.user_id} {self.type} {self.currency} {self.amount}>"
