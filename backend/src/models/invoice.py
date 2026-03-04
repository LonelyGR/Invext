"""
Invoice: пополнение баланса через Crypto Pay API.
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
    from src.models.user import User


class Invoice(Base):
    __tablename__ = "invoices"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)

    # Идентификатор инвойса в Crypto Pay API
    invoice_id: Mapped[int] = mapped_column(index=True, unique=True)

    amount: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    asset: Mapped[str] = mapped_column(String(16), nullable=False, default="USDT")

    # pending / paid / expired
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="invoices")

    def __repr__(self) -> str:
        return f"<Invoice id={self.id} user_id={self.user_id} invoice_id={self.invoice_id} status={self.status}>"

