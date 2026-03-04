"""
Integration with Crypto Pay API (CryptoBot).

Only deposit-related methods are used:
- create_invoice: create a new invoice for user deposit
- get_balance: get app balances
- set_webhook: helper that returns the URL to configure in @CryptoBot (no HTTP call)
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Dict, List, Optional

import httpx

from src.core.config import get_settings

logger = logging.getLogger(__name__)

API_BASE_URL = "https://pay.crypt.bot"


class CryptoPayError(RuntimeError):
    pass


async def _call_api(method: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """Low-level helper for calling Crypto Pay API."""
    settings = get_settings()
    headers = {"Crypto-Pay-API-Token": settings.crypto_pay_token}

    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=10.0) as client:
        resp = await client.post(f"/api/{method}", json=params or {}, headers=headers)

    try:
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.error("Crypto Pay HTTP error in %s: %s", method, e)
        raise CryptoPayError(f"HTTP error calling {method}") from e

    data = resp.json()
    if not data.get("ok"):
        logger.error("Crypto Pay API error in %s: %s", method, data)
        raise CryptoPayError(f"Crypto Pay API error in {method}: {data.get('error') or data}")

    return data.get("result")


async def create_invoice(user_id: int, amount: Decimal, asset: str = "USDT", description: str | None = None) -> Dict[str, Any]:
    """
    Create a new Crypto Pay invoice for the given user and amount.

    Returns raw Crypto Pay Invoice object (dict).
    """
    params: Dict[str, Any] = {
        "currency_type": "crypto",
        "asset": asset,
        "amount": str(amount),
        "payload": str(user_id),
    }
    if description:
        params["description"] = description

    invoice = await _call_api("createInvoice", params)
    return invoice


async def get_balance() -> List[Dict[str, Any]]:
    """Get app balance from Crypto Pay API."""
    balances = await _call_api("getBalance")
    # balances is a list of Balance objects
    return balances


async def get_invoice(invoice_id: int) -> Optional[Dict[str, Any]]:
    """
    Get single invoice by id using getInvoices.
    Returns Invoice object or None if not found.
    """
    result = await _call_api("getInvoices", {"invoice_ids": str(invoice_id)})
    if not result:
        return None
    # API returns array of invoices
    return result[0]


def set_webhook(url: str) -> str:
    """
    Crypto Pay webhooks are configured via @CryptoBot UI, not via HTTP API.

    This helper returns the URL that should be set in the app's Webhook settings.
    """
    settings = get_settings()
    full_url = url or f"{settings.app_url.rstrip('/')}/crypto/webhook"
    logger.info(
        "Set this URL as webhook in @CryptoBot / Crypto Pay app settings: %s",
        full_url,
    )
    return full_url

