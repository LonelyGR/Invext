"""
Модель пользователя: telegram, реферальный код, реферер.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, ForeignKey, String, BigInteger, Text, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base

if TYPE_CHECKING:
    from src.models.deposit_request import DepositRequest
    from src.models.user_wallet import UserWallet
    from src.models.withdraw_request import WithdrawRequest
    from src.models.wallet_transaction import WalletTransaction
    from src.models.ledger_transaction import LedgerTransaction
    from src.models.invoice import Invoice
    from src.models.deal_investment import DealInvestment


def _short_ref_code() -> str:
    """Короткий уникальный реферальный код (8 символов)."""
    return uuid.uuid4().hex[:8].upper()


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, nullable=False, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    ref_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, default=_short_ref_code)
    referrer_id: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"), nullable=True, index=True)
    balance_usdt: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Связи
    referrer: Mapped[Optional["User"]] = relationship("User", remote_side=[id], back_populates="referrals")
    referrals: Mapped[List["User"]] = relationship("User", back_populates="referrer")
    deposit_requests: Mapped[List["DepositRequest"]] = relationship("DepositRequest", back_populates="user")
    withdraw_requests: Mapped[List["WithdrawRequest"]] = relationship("WithdrawRequest", back_populates="user")
    wallet_transactions: Mapped[List["WalletTransaction"]] = relationship(
        "WalletTransaction", back_populates="user"
    )
    user_wallets: Mapped[List["UserWallet"]] = relationship(
        "UserWallet", back_populates="user", cascade="all, delete-orphan"
    )
    ledger_transactions: Mapped[List["LedgerTransaction"]] = relationship(
        "LedgerTransaction", back_populates="user"
    )
    invoices: Mapped[List["Invoice"]] = relationship(
        "Invoice", back_populates="user", cascade="all, delete-orphan"
    )
    deal_investments: Mapped[List["DealInvestment"]] = relationship(
        "DealInvestment", back_populates="user", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User id={self.id} telegram_id={self.telegram_id} ref_code={self.ref_code}>"
