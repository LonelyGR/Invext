"""
Схемы для заявок на вывод.
"""
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, computed_field


class WithdrawRequestIn(BaseModel):
    """Создание заявки на вывод."""
    telegram_id: int
    currency: str = Field(..., pattern="^(USDT|USDC)$")
    amount: Decimal = Field(
        ...,
        gt=0,
        description="Сумма списания с баланса (к выплате на адрес — та же сумма)",
    )
    address: str = Field(..., min_length=1, max_length=512)


class WithdrawRequestResponse(BaseModel):
    """Одна заявка на вывод."""
    id: int
    user_id: int
    currency: str
    amount: Decimal
    address: str
    status: str
    created_at: datetime
    decided_at: Optional[datetime] = None
    decided_by: Optional[int] = None
    updated_at: datetime

    model_config = {"from_attributes": True}

    @computed_field
    def fee_amount(self) -> Decimal:
        return Decimal("0")

    @computed_field
    def net_amount(self) -> Decimal:
        return self.amount


class WithdrawRequestWithUserResponse(WithdrawRequestResponse):
    """Заявка + данные пользователя для админки."""
    user_telegram_id: int
    user_username: Optional[str] = None
    user_name: Optional[str] = None
