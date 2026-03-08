"""
NOWPayments service: create invoice, build order_id, map API responses.
"""
from __future__ import annotations

import logging
import secrets
import time
from decimal import Decimal
from typing import Any, Optional

from src.integrations.nowpayments.client import (
    NowPaymentsAPIError,
    NowPaymentsClient,
    NowPaymentsValidationError,
)
from src.integrations.nowpayments.schemas import CreateInvoiceResult

logger = logging.getLogger(__name__)

PROVIDER_NAME = "nowpayments"


def _map_status(api_status: str) -> str:
    """Map NOWPayments API status to our canonical status."""
    s = (api_status or "").lower()
    if s in ("finished", "sent", "confirmed"):
        return "finished"
    if s in ("waiting", "confirming", "partially_paid"):
        return "waiting" if s == "waiting" else "partially_paid"
    if s in ("failed", "expired", "refunded"):
        return s
    return "waiting"


def generate_order_id(user_id: int) -> str:
    """
    Unique, traceable order_id for NOWPayments.
    Format: inv_{user_id}_{ts}_{random} — no sensitive data, safe for logs.
    """
    ts = int(time.time())
    rnd = secrets.token_hex(4)
    return f"inv_{user_id}_{ts}_{rnd}"


class NowPaymentsService:
    """High-level service for NOWPayments operations."""

    def __init__(self, client: NowPaymentsClient):
        self.client = client

    async def create_invoice(
        self,
        user_id: int,
        amount_usdt: Decimal,
        ipn_callback_url: str,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        order_description: Optional[str] = None,
    ) -> CreateInvoiceResult:
        """
        Create invoice for user deposit. Sends price_currency=usd + pay_currency=usdtbsc
        (invoice-compatible; usdt->usdtbsc fails in NOWPayments checkout). Amount sent
        as USD; validation (min 10, step 1) done in client.
        """
        order_id = generate_order_id(user_id)

        normalized = await self.client.create_invoice(
            order_id=order_id,
            price_amount=amount_usdt,
            price_currency="usd",
            pay_currency="usdtbsc",
            ipn_callback_url=ipn_callback_url,
            success_url=success_url,
            cancel_url=cancel_url,
            order_description=order_description or f"Deposit user {user_id}",
            fixed_rate=True,
        )

        pay_amount_decimal: Optional[Decimal] = None
        try:
            pay_amount_decimal = Decimal(normalized.pay_amount)
        except Exception:
            pass
        price_amount_decimal = Decimal(normalized.price_amount)

        return CreateInvoiceResult(
            order_id=order_id,
            external_invoice_id=normalized.invoice_id or None,
            invoice_url=normalized.invoice_url,
            price_amount=price_amount_decimal,
            price_currency=normalized.price_currency,
            pay_currency=normalized.pay_currency,
            pay_amount=pay_amount_decimal,
            network="BSC",
            status="waiting",
            created_at=None,
            raw_response=normalized.model_dump(),
        )
