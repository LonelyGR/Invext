from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, true
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from src.db.base import Base


class SystemSettings(Base):
    """
    Глобальные финансовые настройки проекта (singleton-запись).
    """

    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    min_deposit_usdt: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("10")
    )
    max_deposit_usdt: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("100000")
    )

    min_withdraw_usdt: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("10")
    )
    max_withdraw_usdt: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("100000")
    )

    min_invest_usdt: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("50")
    )
    max_invest_usdt: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("100000")
    )

    allow_deposits: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )

    deal_amount_usdt: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("50")
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

