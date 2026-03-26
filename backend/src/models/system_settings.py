from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Numeric, String, false, true
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
    allow_investments: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    allow_withdrawals: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    admin_2fa_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=false()
    )
    admin_2fa_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)

    deal_amount_usdt: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("50")
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

