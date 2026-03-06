"""
Payment service: apply successful payment to balance (ledger + user balance).

Used by NOWPayments webhook and optionally by sync endpoint.
Idempotent: safe to call multiple times for the same invoice.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import PaymentInvoice, User, LedgerTransaction
from src.models.payment_invoice import PROVIDER_NOWPAYMENTS
from src.services.ledger_service import LEDGER_TYPE_DEPOSIT, get_balance_usdt

logger = logging.getLogger(__name__)


async def apply_payment_to_balance(
    db: AsyncSession,
    invoice: PaymentInvoice,
    amount: Decimal,
    external_payment_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> bool:
    """
    If invoice not yet applied: create ledger entry, update user balance, mark invoice.
    Must be called within an existing transaction (e.g. db.begin()).
    Returns True if balance was applied, False if already applied or skipped.
    """
    if invoice.is_balance_applied:
        logger.info("Payment invoice order_id=%s already applied, skip", invoice.order_id)
        return False

    user_result = await db.execute(
        select(User).where(User.id == invoice.user_id).with_for_update()
    )
    user = user_result.scalar_one_or_none()
    if not user:
        logger.error("Payment invoice order_id=%s user_id=%s not found", invoice.order_id, invoice.user_id)
        return False

    ledger_tx = LedgerTransaction(
        user_id=invoice.user_id,
        type=LEDGER_TYPE_DEPOSIT,
        amount_usdt=amount,
        provider=PROVIDER_NOWPAYMENTS,
        external_payment_id=external_payment_id or invoice.external_invoice_id or invoice.order_id,
        metadata_json=metadata or {
            "order_id": invoice.order_id,
            "invoice_id": invoice.id,
            "pay_currency": invoice.pay_currency,
            "network": invoice.network,
        },
    )
    db.add(ledger_tx)
    await db.flush()

    new_balance = await get_balance_usdt(db, invoice.user_id)
    user.balance_usdt = new_balance

    invoice.is_balance_applied = True
    invoice.actually_paid_amount = amount
    invoice.status = "finished"
    invoice.completed_at = dt.datetime.now(dt.timezone.utc)

    logger.info(
        "Applied payment order_id=%s user_id=%s amount=%s new_balance=%s",
        invoice.order_id,
        invoice.user_id,
        amount,
        new_balance,
    )
    return True
