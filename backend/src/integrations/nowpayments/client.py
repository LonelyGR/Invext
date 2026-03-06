"""
HTTP client for NOWPayments REST API.

- All requests go through this client.
- Timeouts and error handling centralized.
- No logging of API keys; log request/response without secrets.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from src.integrations.nowpayments.schemas import (
    NowPaymentsCreateInvoiceRequest,
    NowPaymentsInvoiceResponse,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0


class NowPaymentsAPIError(Exception):
    """Raised when NOWPayments API returns an error or non-2xx."""
    def __init__(self, message: str, status_code: Optional[int] = None, body: Any = None):
        self.message = message
        self.status_code = status_code
        self.body = body
        super().__init__(message)


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
        price_amount: float,
        price_currency: str = "usd",
        pay_currency: str = "usdtbsc",
        ipn_callback_url: Optional[str] = None,
        success_url: Optional[str] = None,
        cancel_url: Optional[str] = None,
        order_description: Optional[str] = None,
        is_fixed_rate: bool = True,
    ) -> dict[str, Any]:
        """
        Create an invoice via POST /v1/invoice.

        Returns raw dict for DB storage and parsing.
        """
        body = NowPaymentsCreateInvoiceRequest(
            order_id=order_id,
            price_amount=price_amount,
            price_currency=price_currency,
            pay_currency=pay_currency,
            ipn_callback_url=ipn_callback_url,
            success_url=success_url,
            cancel_url=cancel_url,
            order_description=order_description,
            is_fixed_rate=is_fixed_rate,
        )
        payload = body.model_dump(exclude_none=True)

        url = f"{self.base_url}/v1/invoice"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                url,
                json=payload,
                headers=self._headers(),
            )

        try:
            response_json = response.json()
        except Exception:
            response_json = None

        self._safe_log_response(response, response_json)

        if response.status_code >= 400:
            raise NowPaymentsAPIError(
                message=f"NOWPayments create invoice failed: {response.status_code}",
                status_code=response.status_code,
                body=response_json,
            )

        return response_json if isinstance(response_json, dict) else {}

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
