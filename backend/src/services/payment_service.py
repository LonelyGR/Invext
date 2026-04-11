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

from src.models import LedgerTransaction, PaymentInvoice, User
from src.models.payment_invoice import PROVIDER_NOWPAYMENTS
from src.services.ledger_service import LEDGER_TYPE_DEPOSIT, sync_user_balance
from src.services.notification_service import notify_deposit_success

logger = logging.getLogger(__name__)


async def ledger_nowpayments_deposit_exists(
    db: AsyncSession,
    user_id: int,
    *,
    external_payment_id: Optional[str],
    order_id: str,
) -> bool:
    """
    Защита от дубля ledger без миграции: DEPOSIT с тем же provider и тем же ключом
    (payment_id из IPN или order_id, как в external_payment_id у записи).
    """
    keys: list[str] = []
    if external_payment_id:
        keys.append(str(external_payment_id))
    if order_id:
        keys.append(order_id)
    # Уникальные непустые
    uniq = list(dict.fromkeys(k for k in keys if k))
    if not uniq:
        return False
    q = (
        select(LedgerTransaction.id)
        .where(
            LedgerTransaction.user_id == user_id,
            LedgerTransaction.type == LEDGER_TYPE_DEPOSIT,
            LedgerTransaction.provider == PROVIDER_NOWPAYMENTS,
            LedgerTransaction.external_payment_id.in_(uniq),
        )
        .limit(1)
    )
    r = await db.execute(q)
    return r.scalar_one_or_none() is not None


async def apply_payment_to_balance(
    db: AsyncSession,
    invoice: PaymentInvoice,
    amount: Decimal,
    external_payment_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    *,
    invoice_factually_paid: Optional[Decimal] = None,
) -> bool:
    """
    If invoice not yet applied: create ledger entry, update user balance, mark invoice.
    `amount` — сумма зачисления на баланс (номинал депозита).
    `invoice_factually_paid` — если задано, пишется в invoice.actually_paid_amount (факт из IPN).
    Must be called within an existing transaction (e.g. db.begin()).
    Returns True if balance was applied, False if already applied or skipped.
    """
    if invoice.is_balance_applied:
        logger.info("Payment invoice order_id=%s already applied, skip", invoice.order_id)
        return False

    if await ledger_nowpayments_deposit_exists(
        db,
        invoice.user_id,
        external_payment_id=external_payment_id,
        order_id=invoice.order_id,
    ):
        logger.warning(
            "Ledger DEPOSIT already exists for order_id=%s user_id=%s, skip credit",
            invoice.order_id,
            invoice.user_id,
        )
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

    new_balance = await sync_user_balance(db, invoice.user_id)

    # Отметить, что депозит применён к балансу (идемпотентность сохранена).
    invoice.is_balance_applied = True
    invoice.actually_paid_amount = invoice_factually_paid if invoice_factually_paid is not None else amount
    invoice.status = "finished"
    invoice.completed_at = dt.datetime.now(dt.timezone.utc)

    # Реферальный бонус с депозита временно отключён (код сохранён).
    # try:
    #     await apply_referral_rewards_for_deposit(
    #         db=db,
    #         from_user=user,
    #         deposit_amount=amount,
    #         source_invoice_id=invoice.id,
    #         external_payment_id=external_payment_id or ledger_tx.external_payment_id,
    #     )
    # except Exception as e:
    #     # Не падаем из-за ошибок реферальной системы; логируем и продолжаем.
    #     logger.exception(
    #         "Failed to apply referral rewards for invoice_id=%s user_id=%s: %s",
    #         invoice.id,
    #         invoice.user_id,
    #         e,
    #     )

    logger.info(
        "Applied payment order_id=%s user_id=%s amount=%s new_balance=%s",
        invoice.order_id,
        invoice.user_id,
        amount,
        new_balance,
    )

    if user.telegram_id:
        try:
            await notify_deposit_success(user.telegram_id, str(amount))
        except Exception as e:
            logger.warning(
                "Failed to send deposit success notification to telegram_id=%s: %s",
                user.telegram_id,
                e,
            )

    return True
