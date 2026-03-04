from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class CreateInvoiceRequest(BaseModel):
    telegram_id: int = Field(..., description="Telegram ID пользователя")
    amount: Decimal = Field(..., gt=0, description="Сумма пополнения")
    asset: str = Field(default="USDT", description="Код актива в Crypto Pay (например, USDT)")


class InvoiceResponse(BaseModel):
    invoice_id: int
    user_id: int
    amount: Decimal
    asset: str
    status: str
    bot_invoice_url: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}

