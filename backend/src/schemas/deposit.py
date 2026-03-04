"""
Схемы для заявок на пополнение.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field


ALLOWED_CURRENCIES = ("USDT", "USDC")


class DepositRequestIn(BaseModel):
    """Создание заявки на пополнение."""
    telegram_id: int
    currency: str = Field(..., pattern="^(USDT|USDC)$")
    amount: Decimal = Field(..., gt=0)


class DepositRequestResponse(BaseModel):
    """Одна заявка на пополнение."""
    id: int
    user_id: int
    currency: str
    amount: Decimal
    comment: Optional[str] = None
    status: str
    created_at: datetime
    decided_at: Optional[datetime] = None
    decided_by: Optional[int] = None

    model_config = {"from_attributes": True}


class DepositRequestWithUserResponse(DepositRequestResponse):
    """Заявка + данные пользователя для админки."""
    user_telegram_id: int
    user_username: Optional[str] = None
    user_name: Optional[str] = None
