"""Леджер по внутреннему балансу USDT.

Баланс пользователя считается через сумму записей в этой таблице, а поле
`users.balance_usdt` используется как кэш.

На текущий момент используются типы:
* DEPOSIT  — любое пополнение (например, через Crypto Pay);
* INVEST   — перевод средств из баланса в сделку;
* PROFIT   — начисление прибыли по сделке;
* WITHDRAW — вывод средств.

Поля `chain_id`, `tx_hash`, `log_index`, `blockchain_event_id` оставлены только
для обратной совместимости со старыми данными и в новой логике не используются.
"""
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base

if TYPE_CHECKING:
    from src.models.user import User


class LedgerTransaction(Base):
    """Одна запись = одна операция по внутреннему балансу USDT."""

    __tablename__ = "ledger_transactions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    type: Mapped[str] = mapped_column(String(32), nullable=False)
    amount_usdt: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)

    # Payment provider and external id for audit (e.g. nowpayments, invoice_id/order_id)
    provider: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, index=True)
    external_payment_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    # Источник операции (ранее использовался для блокчейн-депозитов, теперь не используется)
    chain_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True, index=True)
    tx_hash: Mapped[Optional[str]] = mapped_column(String(66), nullable=True, index=True)
    log_index: Mapped[Optional[int]] = mapped_column(nullable=True)
    blockchain_event_id: Mapped[Optional[int]] = mapped_column(
        nullable=True, index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="ledger_transactions")

    def __repr__(self) -> str:
        return (
            f"<LedgerTransaction id={self.id} user_id={self.user_id} "
            f"type={self.type} amount_usdt={self.amount_usdt}>"
        )
