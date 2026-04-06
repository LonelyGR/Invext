"""
Payments API: NOWPayments deposit (create invoice, history, webhook).
"""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
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
from src.services.nowpayments_aggregate import (
    compute_aggregated_nowpayments_paid,
    parse_actually_paid_for_ipn,
)
from src.services.nowpayments_ipn import (
    NOWPAYMENTS_CREDIT_ELIGIBLE_STATUSES,
    NOWPAYMENTS_PARTIAL_STATUS,
    NOWPAYMENTS_TERMINAL_NEGATIVE_STATUSES,
    expected_deposit_amount_for_tolerance,
    is_paid_amount_sufficient_for_credit,
    normalize_ipn_payment_status,
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
    if getattr(user, "is_blocked", False):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Аккаунт временно заблокирован администратором.",
        )

    # Глобальный флаг: временный запрет пополнений.
    sys_settings = await get_system_settings(db)
    if not sys_settings.allow_deposits:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="На данный момент пополнение недоступно. Пожалуйста, ожидайте.",
        )

    # Schema already enforces min 10 USDT, step 1; enforce dynamic min/max from SystemSettings.
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

    # Номинал депозита в USDT (то, что выбрал пользователь). Совпадает с price_amount в запросе к NOWPayments (usd 1:1).
    nominal_usdt = payload.amount
    invoice = PaymentInvoice(
        user_id=user.id,
        provider=PROVIDER_NOWPAYMENTS,
        order_id=create_result.order_id,
        external_invoice_id=create_result.external_invoice_id,
        invoice_url=create_result.invoice_url,
        price_amount=nominal_usdt,
        price_currency=create_result.price_currency,
        pay_currency=create_result.pay_currency,
        expected_amount=nominal_usdt,
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
        currency="usdt",
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
    NOWPayments IPN: подпись, запись события, обновление инвойса, зачисление при допустимой сумме.

    Решение о зачислении — по агрегированной сумме max(actually_paid) по каждому payment_id
    по всем сохранённым IPN для order_id (multi-payment / parent+child), затем tolerance.

    partially_paid — пока aggregate < expected*tolerance: статус/actually_paid, без кредита.
    Идемпотентность: is_balance_applied + проверка дублей ledger (в т.ч. по order_id).
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
    payment_status = normalize_ipn_payment_status(payload)
    actually_paid_raw = payload.get("actually_paid")
    payment_id = payload.get("payment_id")

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
        event.processing_error = "skipped:missing_order_id"
        logger.warning("NOWPayments webhook missing order_id")
        return {"ok": True}

    result = await db.execute(
        select(PaymentInvoice)
        .where(PaymentInvoice.order_id == order_id)
        .with_for_update()
    )
    invoice = result.scalar_one_or_none()
    if invoice is None:
        event.processing_status = PROCESSING_STATUS_SKIPPED
        event.processing_error = "skipped:invoice_not_found"
        logger.warning("NOWPayments webhook order_id=%s invoice not found", order_id)
        return {"ok": True}

    amount_this_ipn = parse_actually_paid_for_ipn(actually_paid_raw)

    # Терминальные неуспехи: обновить статус инвойса, не кредитовать.
    if payment_status in NOWPAYMENTS_TERMINAL_NEGATIVE_STATUSES:
        invoice.status = payment_status
        if amount_this_ipn is not None:
            invoice.actually_paid_amount = amount_this_ipn
        event.processing_status = PROCESSING_STATUS_PROCESSED
        event.processing_error = f"terminal:{payment_status}:no_credit"
        return {"ok": True}

    # Уже зачислено — только синхронизация фактической суммы с aggregate, без кредита.
    if invoice.is_balance_applied:
        aggregated, _, _ = await compute_aggregated_nowpayments_paid(db, invoice, payload)
        invoice.actually_paid_amount = aggregated
        event.processing_status = PROCESSING_STATUS_PROCESSED
        event.processing_error = "already_applied"
        return {"ok": True}

    aggregated, payment_ids_used, agg_note = await compute_aggregated_nowpayments_paid(
        db, invoice, payload
    )
    expected = expected_deposit_amount_for_tolerance(invoice)

    if is_paid_amount_sufficient_for_credit(aggregated, expected):
        # На баланс — ровно номинал депозита; фактически полученное по IPN храним отдельно.
        applied = await apply_payment_to_balance(
            db,
            invoice,
            expected,
            external_payment_id=str(invoice.order_id),
            metadata={
                "payment_status": payment_status,
                "ipn_event_id": event.id,
                "aggregated_payment_ids": payment_ids_used,
                "aggregation_note": agg_note,
                "actually_paid_aggregate": str(aggregated),
            },
            invoice_factually_paid=aggregated,
        )
        if applied:
            event.processing_status = PROCESSING_STATUS_PROCESSED
            event.processing_error = "credited"
        else:
            event.processing_status = PROCESSING_STATUS_SKIPPED
            event.processing_error = "skipped:already_applied_or_ledger_duplicate"
        return {"ok": True}

    # Недостаточно aggregate: отразить сумму; при ненулевом aggregate — partially_paid.
    invoice.actually_paid_amount = aggregated
    if aggregated > 0:
        invoice.status = "partially_paid"
        event.processing_status = PROCESSING_STATUS_PROCESSED
        if payment_status == NOWPAYMENTS_PARTIAL_STATUS:
            event.processing_error = "partial_only:no_credit"
        elif payment_status in NOWPAYMENTS_CREDIT_ELIGIBLE_STATUSES:
            event.processing_error = (
                f"insufficient_for_credit:aggregated={aggregated}:threshold_of_expected={expected}"
            )
        else:
            event.processing_error = (
                f"insufficient_aggregate:aggregated={aggregated}:status={payment_status}"
            )
        logger.info(
            "NOWPayments webhook order_id=%s aggregated=%s insufficient vs expected=%s, no credit",
            order_id,
            aggregated,
            expected,
        )
        return {"ok": True}

    # aggregated == 0: прежнее поведение для «пустых» IPN
    if payment_status in NOWPAYMENTS_CREDIT_ELIGIBLE_STATUSES:
        event.processing_status = PROCESSING_STATUS_ERROR
        event.processing_error = "error:credit_eligible_but_missing_or_invalid_actually_paid"
        logger.warning(
            "NOWPayments webhook order_id=%s status=%s no countable actually_paid in aggregate",
            order_id,
            payment_status,
        )
        return {"ok": True}

    if payment_status == NOWPAYMENTS_PARTIAL_STATUS:
        invoice.status = "partially_paid"
        event.processing_status = PROCESSING_STATUS_PROCESSED
        event.processing_error = "partial_only:no_credit"
        logger.info(
            "NOWPayments webhook order_id=%s partially_paid, invoice updated, no credit",
            order_id,
        )
        return {"ok": True}

    event.processing_status = PROCESSING_STATUS_SKIPPED
    event.processing_error = f"skipped:non_final_status:{payment_status}"
    logger.info("NOWPayments webhook order_id=%s status=%s skipped (non-final)", order_id, payment_status)
    return {"ok": True}
