"""
NOWPayments service: create invoice, build order_id, map API responses.
"""
from __future__ import annotations

import logging
import secrets
import time
from decimal import Decimal
from typing import Any, Optional

from src.integrations.nowpayments.client import NowPaymentsClient, NowPaymentsAPIError
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
        amount_usd: Decimal,
        ipn_callback_url: str,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        order_description: Optional[str] = None,
    ) -> CreateInvoiceResult:
        """
        Create invoice for user deposit. Amount in USD; pay_currency = usdtbsc.
        """
        order_id = generate_order_id(user_id)
        price_amount = float(amount_usd)

        raw = await self.client.create_invoice(
            order_id=order_id,
            price_amount=price_amount,
            price_currency="usd",
            pay_currency="usdtbsc",
            ipn_callback_url=ipn_callback_url,
            success_url=success_url,
            cancel_url=cancel_url,
            order_description=order_description or f"Deposit user {user_id}",
            is_fixed_rate=True,
        )

        invoice_url = raw.get("invoice_url") or ""
        external_id = raw.get("id") or raw.get("invoice_id")
        if isinstance(external_id, (int, float)):
            external_id = str(external_id)
        pay_amount = raw.get("pay_amount")
        created_at_str = raw.get("created_at")

        return CreateInvoiceResult(
            order_id=order_id,
            external_invoice_id=external_id,
            invoice_url=invoice_url,
            price_amount=Decimal(str(raw.get("price_amount") or price_amount)),
            price_currency=raw.get("price_currency") or "usd",
            pay_currency=raw.get("pay_currency") or "usdtbsc",
            pay_amount=Decimal(str(pay_amount)) if pay_amount is not None else None,
            network="BSC",
            status=_map_status(raw.get("payment_status") or raw.get("status") or "waiting"),
            created_at=None,  # optional: parse created_at_str if needed
            raw_response=raw,
        )
