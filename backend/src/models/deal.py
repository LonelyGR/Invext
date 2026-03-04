from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, List, Optional

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from src.db.base import Base

if TYPE_CHECKING:
    from src.models.deal_investment import DealInvestment


class Deal(Base):
    """Инвестиционная сделка.

    number  — порядковый номер (для пользователя);
    percent — доходность в % (по умолчанию 3);
    status  — open / closed / finished.
    """

    __tablename__ = "deals"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    number: Mapped[int] = mapped_column(unique=True, index=True)
    percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2), nullable=False
    )  # например, 3.00 = 3%
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")

    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    investments: Mapped[List["DealInvestment"]] = relationship(
        "DealInvestment",
        back_populates="deal",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<Deal id={self.id} number={self.number} status={self.status} percent={self.percent}>"

