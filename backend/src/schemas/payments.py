"""
Schemas for payments (NOWPayments deposit) API.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field


class CreateDepositInvoiceRequest(BaseModel):
    """Body for POST /v1/payments/deposit/create-invoice."""
    telegram_id: int = Field(..., description="Telegram ID пользователя")
    amount: Decimal = Field(..., gt=0, description="Сумма пополнения в USD")


class DepositInvoiceResponse(BaseModel):
    """Response after creating an invoice."""
    invoice_id: int = Field(..., description="Internal invoice id")
    order_id: str = Field(..., description="Unique order id for tracing")
    external_invoice_id: Optional[str] = None
    invoice_url: str = Field(..., description="URL for user to pay")
    amount: Decimal = Field(..., description="Price amount (USD)")
    currency: str = Field(default="usd")
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
