"""
Payments API: NOWPayments deposit (create invoice, history, webhook).
"""
from __future__ import annotations

import json
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.integrations.nowpayments import (
    NowPaymentsAPIError,
    NowPaymentsClient,
    NowPaymentsService,
    NowPaymentsValidationError,
    verify_ipn_signature,
)
from src.models import PaymentInvoice, PaymentWebhookEvent, User
from src.models.payment_invoice import PROVIDER_NOWPAYMENTS
from src.models.payment_webhook_event import (
    PROCESSING_STATUS_ERROR,
    PROCESSING_STATUS_PROCESSED,
    PROCESSING_STATUS_SKIPPED,
)
from src.schemas.payments import (
    CreateDepositInvoiceRequest,
    DepositHistoryItem,
    DepositHistoryResponse,
    DepositInvoiceResponse,
)
from src.services.payment_service import apply_payment_to_balance
from src.services.settings_service import get_system_settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/payments", tags=["payments"])

IPN_SIGNATURE_HEADER = "x-nowpayments-sig"


def _get_nowpayments_client() -> NowPaymentsClient:
    settings = get_settings()
    return NowPaymentsClient(
        base_url=settings.nowpayments_base_url,
        api_key=settings.nowpayments_api_key,
    )


def _get_nowpayments_service() -> NowPaymentsService:
    return NowPaymentsService(_get_nowpayments_client())


@router.post("/deposit/create-invoice", response_model=DepositInvoiceResponse)
async def create_deposit_invoice(
    payload: CreateDepositInvoiceRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Create NOWPayments invoice for user deposit (USDT BEP20).
    Caller passes telegram_id and amount in USDT; user pays exactly that amount.
    """
    settings = get_settings()
    if not settings.nowpayments_api_key or not settings.nowpayments_callback_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Payments not configured",
        )

    result = await db.execute(select(User).where(User.telegram_id == payload.telegram_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Schema already enforces min 10 USDT, step 1; enforce dynamic min/max from SystemSettings.
    sys_settings = await get_system_settings(db)
    if payload.amount < sys_settings.min_deposit_usdt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Минимальная сумма пополнения: {sys_settings.min_deposit_usdt} USDT",
        )
    if payload.amount > sys_settings.max_deposit_usdt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Amount must not exceed {sys_settings.max_deposit_usdt} USDT",
        )

    callback_url = settings.nowpayments_callback_url.rstrip("/")
    success_url = (settings.nowpayments_success_url or callback_url).rstrip("/")
    cancel_url = (settings.nowpayments_cancel_url or callback_url).rstrip("/")

    service = _get_nowpayments_service()
    try:
        create_result = await service.create_invoice(
            user_id=user.id,
            amount_usdt=payload.amount,
            ipn_callback_url=f"{callback_url}/v1/payments/webhook/nowpayments",
            success_url=success_url,
            cancel_url=cancel_url,
            order_description=f"Deposit user {user.id}",
        )
    except NowPaymentsValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e.args[0]) if e.args else "Invalid deposit amount or order",
        ) from e
    except NowPaymentsAPIError as e:
        logger.exception("NOWPayments create invoice failed user_id=%s: %s", user.id, e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create invoice",
        ) from e

    invoice = PaymentInvoice(
        user_id=user.id,
        provider=PROVIDER_NOWPAYMENTS,
        order_id=create_result.order_id,
        external_invoice_id=create_result.external_invoice_id,
        invoice_url=create_result.invoice_url,
        price_amount=create_result.price_amount,
        price_currency=create_result.price_currency,
        pay_currency=create_result.pay_currency,
        expected_amount=create_result.pay_amount,
        network=create_result.network,
        status=create_result.status,
        raw_response_json=create_result.raw_response,
    )
    db.add(invoice)
    await db.flush()
    await db.refresh(invoice)

    logger.info(
        "Created NOWPayments invoice id=%s order_id=%s user_id=%s amount=%s",
        invoice.id,
        invoice.order_id,
        user.id,
        invoice.price_amount,
    )

    return DepositInvoiceResponse(
        invoice_id=invoice.id,
        order_id=invoice.order_id,
        external_invoice_id=invoice.external_invoice_id,
        invoice_url=invoice.invoice_url or "",
        amount=invoice.price_amount,
        currency=invoice.price_currency,
        pay_currency=invoice.pay_currency,
        network=invoice.network or "BSC",
        status=invoice.status,
        created_at=invoice.created_at,
    )


@router.get("/deposit/history", response_model=DepositHistoryResponse)
async def get_deposit_history(
    telegram_id: int,
    limit: int = 20,
    offset: int = 0,
    status_filter: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Paginated deposit history for user (by telegram_id)."""
    if limit < 1 or limit > 100:
        limit = 20
    if offset < 0:
        offset = 0

    result = await db.execute(select(User.id).where(User.telegram_id == telegram_id))
    user_id = result.scalar_one_or_none()
    if user_id is None:
        return DepositHistoryResponse(items=[], total=0, limit=limit, offset=offset)

    query = select(PaymentInvoice).where(PaymentInvoice.user_id == user_id)
    if status_filter and status_filter.strip():
        query = query.where(PaymentInvoice.status == status_filter.strip().lower())
    count_query = select(func.count(PaymentInvoice.id)).where(PaymentInvoice.user_id == user_id)
    if status_filter and status_filter.strip():
        count_query = count_query.where(PaymentInvoice.status == status_filter.strip().lower())

    total_result = await db.execute(count_query)
    total = int(total_result.scalar() or 0)

    query = query.order_by(desc(PaymentInvoice.created_at)).limit(limit).offset(offset)
    rows = await db.execute(query)
    invoices = list(rows.scalars().all())

    items = [
        DepositHistoryItem(
            id=inv.id,
            order_id=inv.order_id,
            external_invoice_id=inv.external_invoice_id,
            invoice_url=inv.invoice_url,
            price_amount=inv.price_amount,
            price_currency=inv.price_currency,
            pay_currency=inv.pay_currency,
            network=inv.network,
            status=inv.status,
            is_balance_applied=inv.is_balance_applied,
            created_at=inv.created_at,
            completed_at=inv.completed_at,
        )
        for inv in invoices
    ]
    return DepositHistoryResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/deposit/{invoice_id}", response_model=DepositHistoryItem)
async def get_deposit_by_id(
    invoice_id: int,
    telegram_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get one deposit invoice by internal id; must belong to user (telegram_id)."""
    result = await db.execute(select(User.id).where(User.telegram_id == telegram_id))
    user_id = result.scalar_one_or_none()
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    result = await db.execute(
        select(PaymentInvoice)
        .where(PaymentInvoice.id == invoice_id, PaymentInvoice.user_id == user_id)
    )
    inv = result.scalar_one_or_none()
    if inv is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invoice not found")

    return DepositHistoryItem(
        id=inv.id,
        order_id=inv.order_id,
        external_invoice_id=inv.external_invoice_id,
        invoice_url=inv.invoice_url,
        price_amount=inv.price_amount,
        price_currency=inv.price_currency,
        pay_currency=inv.pay_currency,
        network=inv.network,
        status=inv.status,
        is_balance_applied=inv.is_balance_applied,
        created_at=inv.created_at,
        completed_at=inv.completed_at,
    )


@router.post("/webhook/nowpayments")
async def webhook_nowpayments(request: Request, db: AsyncSession = Depends(get_db)):
    """
    NOWPayments IPN callback. Verify signature, log event, process only 'finished' status.
    Idempotent: duplicate webhooks do not double-credit balance.
    """
    raw_body = await request.body()
    signature = request.headers.get(IPN_SIGNATURE_HEADER)
    settings = get_settings()

    if not settings.nowpayments_ipn_secret:
        logger.warning("NOWPayments IPN secret not set, rejecting webhook")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Webhook not configured")

    if not verify_ipn_signature(settings.nowpayments_ipn_secret, raw_body, signature):
        logger.warning("NOWPayments webhook invalid signature")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid signature")

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except json.JSONDecodeError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")

    order_id = payload.get("order_id")
    payment_status = (payload.get("payment_status") or payload.get("status") or "").lower()
    actually_paid = payload.get("actually_paid")
    payment_id = payload.get("payment_id")

    # Log webhook event
    event = PaymentWebhookEvent(
        provider=PROVIDER_NOWPAYMENTS,
        external_event_id=str(payment_id) if payment_id is not None else None,
        order_id=order_id,
        payload_json=payload,
        signature_header=signature,
    )
    db.add(event)
    await db.flush()

    if not order_id:
        event.processing_status = PROCESSING_STATUS_SKIPPED
        event.processing_error = "Missing order_id"
        logger.warning("NOWPayments webhook missing order_id")
        return {"ok": True}

    # Only credit on final success status
    if payment_status not in ("finished", "sent", "confirmed"):
        event.processing_status = PROCESSING_STATUS_SKIPPED
        event.processing_error = f"Status not applicable: {payment_status}"
        logger.info("NOWPayments webhook order_id=%s status=%s skipped", order_id, payment_status)
        return {"ok": True}

    amount = Decimal(str(actually_paid)) if actually_paid is not None else None
    if amount is None or amount <= 0:
        event.processing_status = PROCESSING_STATUS_ERROR
        event.processing_error = "Missing or invalid actually_paid"
        logger.warning("NOWPayments webhook order_id=%s invalid actually_paid", order_id)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid amount")

    result = await db.execute(
        select(PaymentInvoice)
        .where(PaymentInvoice.order_id == order_id)
        .with_for_update()
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        event.processing_status = PROCESSING_STATUS_SKIPPED
        event.processing_error = "Invoice not found"
        logger.warning("NOWPayments webhook order_id=%s invoice not found", order_id)
        return {"ok": True}

    applied = await apply_payment_to_balance(
        db,
        invoice,
        amount,
        external_payment_id=str(payment_id) if payment_id is not None else None,
        metadata={"payment_status": payment_status, "ipn_event_id": event.id},
    )
    event.processing_status = PROCESSING_STATUS_PROCESSED if applied else PROCESSING_STATUS_SKIPPED
    if not applied:
        event.processing_error = "Already applied"

    return {"ok": True}
