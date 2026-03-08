"""
HTTP client for NOWPayments REST API.

- All requests go through this client.
- Timeouts and error handling centralized.
- No logging of API keys; log request/response without secrets.
- Invoice creation: USDT only (BSC), exact amount, Decimal-based.
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal
from typing import Any, Optional

import httpx

from src.integrations.nowpayments.schemas import CreateInvoiceNormalizedResponse

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0

# Deposit rules: exact USDT amounts only
MIN_DEPOSIT_USDT = Decimal("10")
STEP_DEPOSIT_USDT = Decimal("1")

# order_id: alphanumeric, underscore, hyphen; max length for API safety
ORDER_ID_MAX_LENGTH = 128
ORDER_ID_SAFE_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


class NowPaymentsAPIError(Exception):
    """Raised when NOWPayments API returns an error or non-2xx."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        body: Any = None,
    ):
        self.message = message
        self.status_code = status_code
        self.body = body
        super().__init__(message)


class NowPaymentsValidationError(Exception):
    """Raised when invoice parameters fail validation (amount, order_id)."""


def _sanitize_order_id(order_id: str) -> str:
    """Return order_id safe for API: strip and ensure allowed chars only."""
    if not order_id or not isinstance(order_id, str):
        raise NowPaymentsValidationError("order_id is required and must be a non-empty string")
    s = order_id.strip()
    if len(s) > ORDER_ID_MAX_LENGTH:
        s = s[:ORDER_ID_MAX_LENGTH]
    if not ORDER_ID_SAFE_PATTERN.match(s):
        # Keep only safe chars
        s = "".join(c for c in s if c.isalnum() or c in "_-")
        if not s:
            raise NowPaymentsValidationError("order_id must contain at least one alphanumeric or _- character")
    return s


def _validate_deposit_amount(amount: Decimal) -> None:
    """Validate deposit: > 0, >= MIN_DEPOSIT_USDT, step STEP_DEPOSIT_USDT."""
    if amount <= 0:
        raise NowPaymentsValidationError("Amount must be greater than zero")
    if amount < MIN_DEPOSIT_USDT:
        raise NowPaymentsValidationError(
            f"Minimum deposit is {MIN_DEPOSIT_USDT} USDT"
        )
    # Step = 1: amount must be integer
    if amount % STEP_DEPOSIT_USDT != 0:
        raise NowPaymentsValidationError(
            f"Amount must be a whole number (step {STEP_DEPOSIT_USDT} USDT)"
        )


class NowPaymentsClient:
    """Sync/async client for NOWPayments API."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }

    def _safe_log_response(self, response: httpx.Response, response_json: Any) -> None:
        """Log response without leaking API key or full payload."""
        logger.info(
            "NOWPayments API response status=%s path=%s",
            response.status_code,
            response.url.path,
        )
        if response.status_code >= 400:
            logger.warning(
                "NOWPayments API error: status=%s body_preview=%s",
                response.status_code,
                str(response_json)[:500] if response_json else response.text[:500],
            )

    async def create_invoice(
        self,
        order_id: str,
        price_amount: Decimal,
        price_currency: str = "usd",
        pay_currency: str = "usdtbsc",
        ipn_callback_url: Optional[str] = None,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        order_description: Optional[str] = None,
        fixed_rate: bool = True,
    ) -> CreateInvoiceNormalizedResponse:
        """
        Create an invoice via POST /v1/invoice.

        - Amount is exact USDT (no USD conversion). User sees the same amount they entered.
        - price_amount sent as string; no pay_amount in request.
        - Validates: amount > 0, min 10 USDT, step 1 USDT; sanitizes order_id.
        - Logs payload before request; raises on API errors.
        """
        _validate_deposit_amount(price_amount)
        safe_order_id = _sanitize_order_id(order_id)

        # Build payload: price_amount as string. Do not send fixed_rate — API rejects it.
        payload: dict[str, Any] = {
            "price_amount": str(price_amount),
            "price_currency": price_currency,
            "pay_currency": pay_currency,
            "order_id": safe_order_id,
        }
        if ipn_callback_url is not None:
            payload["ipn_callback_url"] = ipn_callback_url
        if success_url is not None:
            payload["success_url"] = success_url
        if cancel_url is not None:
            payload["cancel_url"] = cancel_url
        if order_description is not None:
            payload["order_description"] = order_description

        logger.info(
            "NOWPayments create_invoice request order_id=%s price_amount=%s pay_currency=%s",
            safe_order_id,
            payload["price_amount"],
            pay_currency,
        )

        url = f"{self.base_url}/v1/invoice"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                url,
                json=payload,
                headers=self._headers(),
            )

        try:
            response_json = response.json()
        except Exception as e:
            logger.exception("NOWPayments create_invoice invalid JSON response: %s", e)
            raise NowPaymentsAPIError(
                message="Invalid JSON response from NOWPayments",
                status_code=response.status_code,
                body=response.text,
            ) from e

        self._safe_log_response(response, response_json)

        if response.status_code >= 400:
            raise NowPaymentsAPIError(
                message=f"NOWPayments create invoice failed: {response.status_code}",
                status_code=response.status_code,
                body=response_json,
            )

        if not isinstance(response_json, dict):
            raise NowPaymentsAPIError(
                message="NOWPayments create invoice returned non-dict response",
                status_code=response.status_code,
                body=response_json,
            )

        return _normalize_invoice_response(response_json)

    async def get_invoice(self, invoice_id: str) -> Optional[dict[str, Any]]:
        """
        Get invoice by id (GET /v1/invoice/{invoice_id}).
        Returns None if not found or error.
        """
        url = f"{self.base_url}/v1/invoice/{invoice_id}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(url, headers=self._headers())

        try:
            response_json = response.json()
        except Exception:
            response_json = None

        self._safe_log_response(response, response_json)

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise NowPaymentsAPIError(
                message=f"NOWPayments get invoice failed: {response.status_code}",
                status_code=response.status_code,
                body=response_json,
            )

        return response_json if isinstance(response_json, dict) else None


def _normalize_invoice_response(raw: dict[str, Any]) -> CreateInvoiceNormalizedResponse:
    """Map NOWPayments response to normalized fields: invoice_id, invoice_url, pay_address, pay_amount, pay_currency."""
    invoice_id = raw.get("id") or raw.get("invoice_id")
    if invoice_id is not None and not isinstance(invoice_id, str):
        invoice_id = str(invoice_id)
    invoice_url = raw.get("invoice_url") or ""
    pay_address = raw.get("pay_address") or ""
    pay_amount = raw.get("pay_amount")
    if pay_amount is not None and not isinstance(pay_amount, str):
        pay_amount = str(pay_amount)
    pay_amount = pay_amount or "0"
    pay_currency = raw.get("pay_currency") or "usdtbsc"

    return CreateInvoiceNormalizedResponse(
        invoice_id=invoice_id or "",
        invoice_url=invoice_url,
        pay_address=pay_address,
        pay_amount=pay_amount,
        pay_currency=pay_currency,
    )
