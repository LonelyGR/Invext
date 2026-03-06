"""
NOWPayments IPN webhook signature verification.

Official: sort payload keys alphabetically, JSON stringify, HMAC-SHA512 with IPN secret.
Header: x-nowpayments-sig
"""
from __future__ import annotations

import hmac
import hashlib
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

HEADER_SIGNATURE = "x-nowpayments-sig"


def _sorted_json_dumps(obj: dict[str, Any]) -> str:
    """Serialize dict with keys sorted alphabetically (as NOWPayments expects)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def verify_ipn_signature(ipn_secret: str, raw_body: bytes, signature_header: str | None) -> bool:
    """
    Verify x-nowpayments-sig HMAC-SHA512 signature.

    Args:
        ipn_secret: IPN secret from NOWPayments dashboard.
        raw_body: Raw request body (JSON).
        signature_header: Value of x-nowpayments-sig header.

    Returns:
        True if signature is valid.
    """
    if not ipn_secret or not signature_header:
        logger.warning("IPN verification skipped: missing secret or signature header")
        return False

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("IPN invalid body: %s", e)
        return False

    if not isinstance(payload, dict):
        return False

    message = _sorted_json_dumps(payload)
    expected = hmac.new(
        ipn_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha512,
    ).hexdigest()

    return hmac.compare_digest(expected, signature_header.strip())
