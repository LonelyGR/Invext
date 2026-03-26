from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.system_settings import SystemSettings


@dataclass
class SettingsDTO:
    min_deposit_usdt: Decimal
    max_deposit_usdt: Decimal
    min_withdraw_usdt: Decimal
    max_withdraw_usdt: Decimal
    min_invest_usdt: Decimal
    max_invest_usdt: Decimal
    deal_amount_usdt: Decimal
    allow_deposits: bool
    allow_investments: bool
    allow_withdrawals: bool
    support_contact: str | None


async def get_system_settings(db: AsyncSession) -> SettingsDTO:
    """
    Получить глобальные настройки.
    """
    # В распределённом окружении (несколько воркеров/контейнеров) in-memory кэш
    # может расходиться между инстансами и давать разные лимиты пользователям.
    # Поэтому читаем актуальные настройки напрямую из БД.
    result = await db.execute(select(SystemSettings).limit(1))
    row = result.scalar_one()
    return SettingsDTO(
        min_deposit_usdt=Decimal(row.min_deposit_usdt),
        max_deposit_usdt=Decimal(row.max_deposit_usdt),
        min_withdraw_usdt=Decimal(row.min_withdraw_usdt),
        max_withdraw_usdt=Decimal(row.max_withdraw_usdt),
        min_invest_usdt=Decimal(row.min_invest_usdt),
        max_invest_usdt=Decimal(row.max_invest_usdt),
        deal_amount_usdt=Decimal(row.deal_amount_usdt),
        allow_deposits=bool(row.allow_deposits),
        allow_investments=bool(row.allow_investments),
        allow_withdrawals=bool(getattr(row, "allow_withdrawals", True)),
        support_contact=getattr(row, "support_contact", None),
    )


def invalidate_system_settings_cache() -> None:
    # Совместимость со старым API: кэш отключён, инвалидировать нечего.
    return None

