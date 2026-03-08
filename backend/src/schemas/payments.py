"""
Schemas for payments (NOWPayments deposit) API.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


# Deposit rules: exact USDT amounts only (min 10, step 1)
MIN_DEPOSIT_USDT = Decimal("10")
STEP_DEPOSIT_USDT = Decimal("1")


class CreateDepositInvoiceRequest(BaseModel):
    """Body for POST /v1/payments/deposit/create-invoice. Amount in USDT (BSC)."""
    telegram_id: int = Field(..., description="Telegram ID пользователя")
    amount: Decimal = Field(
        ...,
        ge=MIN_DEPOSIT_USDT,
        multiple_of=STEP_DEPOSIT_USDT,
        description="Сумма пополнения в USDT (минимум 10, шаг 1)",
    )


class DepositInvoiceResponse(BaseModel):
    """Response after creating an invoice."""
    invoice_id: int = Field(..., description="Internal invoice id")
    order_id: str = Field(..., description="Unique order id for tracing")
    external_invoice_id: Optional[str] = None
    invoice_url: str = Field(..., description="URL for user to pay")
    amount: Decimal = Field(..., description="Price amount (USDT)")
    currency: str = Field(default="usdt")
    pay_currency: str = Field(default="usdtbsc", description="Payment currency (USDT BEP20)")
    network: str = Field(default="BSC")
    status: str = Field(..., description="waiting | partially_paid | finished | failed | expired")
    created_at: datetime = Field(...)

    model_config = {"from_attributes": True}


class DepositHistoryItem(BaseModel):
    """One item in deposit history list."""
    id: int
    order_id: str
    external_invoice_id: Optional[str] = None
    invoice_url: Optional[str] = None
    price_amount: Decimal
    price_currency: str
    pay_currency: str
    network: Optional[str] = None
    status: str
    is_balance_applied: bool
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DepositHistoryResponse(BaseModel):
    """Paginated deposit history."""
    items: List[DepositHistoryItem]
    total: int
    limit: int
    offset: int
