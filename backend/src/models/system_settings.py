from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, Text, false, true
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
    allow_welcome_bonus: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    welcome_bonus_amount_usdt: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("100")
    )
    welcome_bonus_for_new_users: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    welcome_bonus_for_zero_balance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=true()
    )
    welcome_bonus_new_user_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=30, server_default="30"
    )
    support_contact: Mapped[str | None] = mapped_column(String(255), nullable=True)
    deal_schedule_json: Mapped[str | None] = mapped_column(Text, nullable=True)
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

