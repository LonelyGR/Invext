"""
Pydantic schemas for NOWPayments API request/response and internal DTOs.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field


# --- API request (create invoice) ---
class NowPaymentsCreateInvoiceRequest(BaseModel):
    """Body for POST /v1/invoice. Use price_currency=usd + pay_currency=usdtbsc (usdt->usdtbsc fails in checkout)."""
    order_id: str
    price_amount: Decimal
    price_currency: str = "usd"
    pay_currency: str = "usdtbsc"
    ipn_callback_url: Optional[str] = None
    success_url: Optional[str] = None
    cancel_url: Optional[str] = None
    order_description: Optional[str] = None
    fixed_rate: bool = True


# --- Normalized create-invoice response (for consumers) ---
class CreateInvoiceNormalizedResponse(BaseModel):
    """Normalized response from create_invoice: exact fields for payment flow."""
    invoice_id: str
    invoice_url: str
    pay_address: str
    pay_amount: str
    pay_currency: str
    price_amount: str
    price_currency: str


# --- API response (create invoice) ---
class NowPaymentsInvoiceResponse(BaseModel):
    """Response from NOWPayments after creating an invoice."""
    id: Optional[str] = None
    order_id: Optional[str] = None
    invoice_id: Optional[str] = None
    invoice_url: Optional[str] = None
    price_amount: Optional[Decimal] = None
    price_currency: Optional[str] = None
    pay_currency: Optional[str] = None
    pay_amount: Optional[Decimal] = None
    actually_paid: Optional[Decimal] = None
    outcome_amount: Optional[Decimal] = None
    outcome_currency: Optional[str] = None
    order_description: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    expiration_estimate: Optional[str] = None

    class Config:
        extra = "allow"


# --- IPN webhook payload (incoming) ---
class NowPaymentsIPNPayload(BaseModel):
    """Minimal structure for IPN webhook; full payload stored as raw JSON."""
    payment_id: Optional[int] = None
    payment_status: Optional[str] = None
    pay_address: Optional[str] = None
    price_amount: Optional[Decimal] = None
    price_currency: Optional[str] = None
    pay_amount: Optional[Decimal] = None
    actually_paid: Optional[Decimal] = None
    pay_currency: Optional[str] = None
    order_id: Optional[str] = None
    order_description: Optional[str] = None
    outcome_amount: Optional[Decimal] = None
    outcome_currency: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    model_config = {"extra": "allow"}

    @classmethod
    def from_raw(cls, data: dict[str, Any]) -> "NowPaymentsIPNPayload":
        return cls.model_validate(data)


# --- Internal DTOs for service layer ---
class CreateInvoiceResult(BaseModel):
    """Result of creating an invoice (for our DB + API response)."""
    order_id: str
    external_invoice_id: Optional[str] = None
    invoice_url: str
    price_amount: Decimal
    price_currency: str
    pay_currency: str
    pay_amount: Optional[Decimal] = None
    network: str = "BSC"
    status: str = "waiting"
    created_at: Optional[datetime] = None
    raw_response: Optional[dict[str, Any]] = None
