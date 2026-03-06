"""
Payment invoice (NOWPayments): one record per created invoice for user deposit.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base

if TYPE_CHECKING:
    from src.models.user import User

PROVIDER_NOWPAYMENTS = "nowpayments"


class PaymentInvoice(Base):
    """One invoice for deposit (NOWPayments)."""

    __tablename__ = "payment_invoices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default=PROVIDER_NOWPAYMENTS)

    order_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    external_invoice_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    invoice_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    price_amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    price_currency: Mapped[str] = mapped_column(String(16), nullable=False, default="usd")
    pay_currency: Mapped[str] = mapped_column(String(32), nullable=False, default="usdtbsc")
    expected_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    actually_paid_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(18, 8), nullable=True)
    network: Mapped[Optional[str]] = mapped_column(String(32), nullable=True, default="BSC")

    status: Mapped[str] = mapped_column(String(32), nullable=False, default="waiting", index=True)
    is_balance_applied: Mapped[bool] = mapped_column(nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    raw_response_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="payment_invoices")

    __table_args__ = (
        Index("ix_payment_invoices_user_status", "user_id", "status"),
    )

    def __repr__(self) -> str:
        return (
            f"<PaymentInvoice id={self.id} order_id={self.order_id} "
            f"user_id={self.user_id} status={self.status}>"
        )
