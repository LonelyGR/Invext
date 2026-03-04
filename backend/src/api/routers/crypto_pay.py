"""
Crypto Pay (CryptoBot) invoice-based deposits.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.db.session import get_db
from src.models import Invoice, User, LedgerTransaction
from src.schemas.crypto_pay import CreateInvoiceRequest, InvoiceResponse
from src.services.crypto_pay_service import (
    CryptoPayError,
    create_invoice as cp_create_invoice,
    get_invoice as cp_get_invoice,
)
from src.services.ledger_service import (
    LEDGER_TYPE_DEPOSIT,
    get_balance_usdt,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/crypto", tags=["crypto-pay"])


@router.post("/invoices", response_model=InvoiceResponse)
async def create_deposit_invoice(
    payload: CreateInvoiceRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Создать инвойс на пополнение баланса пользователя.

    Бот вызывает этот endpoint, затем отправляет пользователю ссылку bot_invoice_url.
    """
    result = await db.execute(select(User).where(User.telegram_id == payload.telegram_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    try:
        cp_invoice = await cp_create_invoice(user.id, payload.amount, asset=payload.asset)
    except CryptoPayError as e:
        logger.exception("Failed to create Crypto Pay invoice for user_id=%s: %s", user.id, e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to create invoice")

    invoice = Invoice(
        user_id=user.id,
        invoice_id=cp_invoice["invoice_id"],
        amount=Decimal(str(cp_invoice["amount"])),
        asset=cp_invoice.get("asset", payload.asset),
        status="pending",
    )
    db.add(invoice)
    await db.flush()
    await db.refresh(invoice)

    return InvoiceResponse(
        invoice_id=invoice.invoice_id,
        user_id=invoice.user_id,
        amount=invoice.amount,
        asset=invoice.asset,
        status=invoice.status,
        bot_invoice_url=cp_invoice.get("bot_invoice_url") or cp_invoice.get("pay_url"),
        created_at=invoice.created_at,
    )


def _verify_signature(token: str, body: bytes, signature: str | None) -> bool:
    if not signature:
        return False
    secret = hashlib.sha256(token.encode("utf-8")).digest()
    check_string = body.decode("utf-8")
    h = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    return h == signature


@router.post("/invoices/{invoice_id}/sync", response_model=InvoiceResponse)
async def sync_invoice_status(
    invoice_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Ручная проверка статуса инвойса без вебхука.

    Вызывается ботом или админкой, когда пользователь нажимает «Проверить оплату».
    """
    # Получаем локальный инвойс
    result = await db.execute(
        select(Invoice)
        .where(Invoice.invoice_id == invoice_id)
    )
    local_invoice = result.scalar_one_or_none()
    if local_invoice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    # Если уже paid — просто отдаём текущее состояние
    if local_invoice.status == "paid":
        return InvoiceResponse(
            invoice_id=local_invoice.invoice_id,
            user_id=local_invoice.user_id,
            amount=local_invoice.amount,
            asset=local_invoice.asset,
            status=local_invoice.status,
            bot_invoice_url=None,
            created_at=local_invoice.created_at,
        )

    try:
        remote = await cp_get_invoice(invoice_id)
    except CryptoPayError as e:
        logger.exception("Failed to get Crypto Pay invoice %s: %s", invoice_id, e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail="Failed to fetch invoice status")

    if not remote:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found in Crypto Pay")

    remote_status = remote.get("status")
    remote_amount = remote.get("amount")
    remote_asset = remote.get("asset")

    # Если в Crypto Pay инвойс ещё не оплачен — просто возвращаем текущий статус
    if remote_status != "paid":
        return InvoiceResponse(
            invoice_id=local_invoice.invoice_id,
            user_id=local_invoice.user_id,
            amount=local_invoice.amount,
            asset=local_invoice.asset,
            status=local_invoice.status,
            bot_invoice_url=remote.get("bot_invoice_url") or remote.get("pay_url"),
            created_at=local_invoice.created_at,
        )

    # Если оплачен — применяем ту же транзакционную логику, что и в webhook
    async with db.begin():
        result = await db.execute(
            select(Invoice)
            .where(Invoice.invoice_id == invoice_id)
            .with_for_update()
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

        if invoice.status == "paid":
            return InvoiceResponse(
                invoice_id=invoice.invoice_id,
                user_id=invoice.user_id,
                amount=invoice.amount,
                asset=invoice.asset,
                status=invoice.status,
                bot_invoice_url=remote.get("bot_invoice_url") or remote.get("pay_url"),
                created_at=invoice.created_at,
            )

        user_result = await db.execute(
            select(User)
            .where(User.id == invoice.user_id)
            .with_for_update()
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            logger.error("Invoice %s refers to missing user_id=%s", invoice.invoice_id, invoice.user_id)
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        credit_amount = Decimal(str(remote_amount if remote_amount is not None else invoice.amount))

        # Леджер: фиксируем пополнение
        ledger_tx = LedgerTransaction(
            user_id=invoice.user_id,
            type=LEDGER_TYPE_DEPOSIT,
            amount_usdt=credit_amount,
        )
        db.add(ledger_tx)
        await db.flush()

        # Обновляем кэш баланса пользователя по леджеру
        new_balance = await get_balance_usdt(db, invoice.user_id)
        user.balance_usdt = new_balance

        invoice.status = "paid"
        invoice.asset = remote_asset or invoice.asset
        invoice.paid_at = dt.datetime.now(dt.timezone.utc)

    return InvoiceResponse(
        invoice_id=invoice.invoice_id,
        user_id=invoice.user_id,
        amount=invoice.amount,
        asset=invoice.asset,
        status=invoice.status,
        bot_invoice_url=remote.get("bot_invoice_url") or remote.get("pay_url"),
        created_at=invoice.created_at,
    )


@router.post("/webhook")
async def crypto_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Webhook для Crypto Pay.

    Обрабатываем только update_type == invoice_paid.
    """
    raw_body = await request.body()
    settings = get_settings()
    signature = request.headers.get("crypto-pay-api-signature")

    if not _verify_signature(settings.crypto_pay_token, raw_body, signature):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    if payload.get("update_type") != "invoice_paid":
        return {"ok": True}

    invoice_payload = payload.get("payload") or {}
    invoice_id = invoice_payload.get("invoice_id")
    amount = invoice_payload.get("amount")
    asset = invoice_payload.get("asset")

    if invoice_id is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing invoice_id")

    # Транзакция: защита от двойного начисления
    async with db.begin():
        result = await db.execute(
            select(Invoice)
            .where(Invoice.invoice_id == invoice_id)
            .with_for_update()
        )
        invoice = result.scalar_one_or_none()
        if invoice is None:
            # Инвойс не наш — игнорируем
            return {"ok": True}

        if invoice.status == "paid":
            # Уже обработан (идемпотентность)
            return {"ok": True}

        user_result = await db.execute(
            select(User)
            .where(User.id == invoice.user_id)
            .with_for_update()
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            logger.error("Invoice %s refers to missing user_id=%s", invoice.invoice_id, invoice.user_id)
            return {"ok": True}

        # Баланс фиксируем через ledger
        credit_amount = Decimal(str(amount if amount is not None else invoice.amount))

        ledger_tx = LedgerTransaction(
            user_id=invoice.user_id,
            type=LEDGER_TYPE_DEPOSIT,
            amount_usdt=credit_amount,
        )
        db.add(ledger_tx)
        await db.flush()

        new_balance = await get_balance_usdt(db, invoice.user_id)
        user.balance_usdt = new_balance

        invoice.status = "paid"
        invoice.asset = asset or invoice.asset
        invoice.paid_at = dt.datetime.now(dt.timezone.utc)

    return {"ok": True}

