"""
Pydantic-схемы для пользователя и авторизации через Telegram.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


class TelegramAuthIn(BaseModel):
    """Тело запроса POST /v1/telegram/auth."""
    telegram_id: int
    username: Optional[str] = None
    name: Optional[str] = None
    ref_code_from_start: Optional[str] = None  # реферальный код из /start ref_code


class UserUpdateIn(BaseModel):
    """Тело PATCH /v1/telegram/me — обновление профиля."""
    name: Optional[str] = None
    email: Optional[str] = None
    country: Optional[str] = None


class UserResponse(BaseModel):
    """Пользователь в ответах API."""
    id: int
    telegram_id: int
    username: Optional[str] = None
    name: Optional[str] = None
    email: Optional[str] = None
    country: Optional[str] = None
    ref_code: str
    referrer_id: Optional[int] = None
    created_at: datetime
    # Статистика для профиля/оборота
    referrals_count: int = 0
    team_deposits_usdt: Decimal = Decimal("0")
    team_deposits_usdc: Decimal = Decimal("0")
    my_deposits_total_usdt: Decimal = Decimal("0")
    my_deposits_total_usdc: Decimal = Decimal("0")
    my_withdrawals_total_usdt: Decimal = Decimal("0")
    my_withdrawals_total_usdc: Decimal = Decimal("0")
    deposits_count: int = 0
    withdrawals_count: int = 0

    model_config = {"from_attributes": True}
