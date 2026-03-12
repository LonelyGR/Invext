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


_SETTINGS_CACHE: Optional[SettingsDTO] = None


async def get_system_settings(db: AsyncSession) -> SettingsDTO:
    """
    Получить глобальные настройки.

    Значения кэшируются в памяти процесса; кэш очищается через
    invalidate_system_settings_cache() после изменения настроек.
    """
    global _SETTINGS_CACHE
    if _SETTINGS_CACHE is not None:
        return _SETTINGS_CACHE

    result = await db.execute(select(SystemSettings).limit(1))
    row = result.scalar_one()
    _SETTINGS_CACHE = SettingsDTO(
        min_deposit_usdt=Decimal(row.min_deposit_usdt),
        max_deposit_usdt=Decimal(row.max_deposit_usdt),
        min_withdraw_usdt=Decimal(row.min_withdraw_usdt),
        max_withdraw_usdt=Decimal(row.max_withdraw_usdt),
        min_invest_usdt=Decimal(row.min_invest_usdt),
        max_invest_usdt=Decimal(row.max_invest_usdt),
        deal_amount_usdt=Decimal(row.deal_amount_usdt),
    )
    return _SETTINGS_CACHE


def invalidate_system_settings_cache() -> None:
    global _SETTINGS_CACHE
    _SETTINGS_CACHE = None

