from __future__ import annotations

import csv
import datetime as dt
import io
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy import and_, desc, func, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_auth import (
    JWT_COOKIE_NAME,
    create_admin_jwt,
    get_admin_context,
    log_admin_action,
    validate_admin_token,
)
from src.db.session import get_db
from src.models import (
    AdminToken,
    User,
    LedgerTransaction,
    Deal,
    DealInvestment,
    DealParticipation,
    WithdrawRequest,
    AdminLog,
    PaymentInvoice,
    PaymentWebhookEvent,
    SystemSettings,
)
from src.schemas.admin_dashboard import (
    DashboardStats,
    LedgerItem,
    LedgerList,
    LoginRequest,
    PaginatedUsers,
    UserRow,
    UserDetail,
    UserInvestment,
    UserWithdrawRequest,
    PaginatedAdminLogs,
    AdminLogItem,
    DealRow,
    DealUpdateRequest,
    DepositRow,
    DepositDetail,
    PaginatedDeposits,
)
from src.services.ledger_service import (
    LEDGER_TYPE_DEPOSIT,
    LEDGER_TYPE_INVEST,
    LEDGER_TYPE_PROFIT,
    LEDGER_TYPE_WITHDRAW,
    get_balance_usdt,
)
from src.services.deal_service import get_active_deal, get_active_deal_legacy, open_new_deal
from src.services.settings_service import invalidate_system_settings_cache


router = APIRouter(prefix="/database/api", tags=["admin-dashboard"])


@router.post("/login")
async def admin_login(
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Логин по одноразовому токену admin_tokens.token."""
    token = await validate_admin_token(db, body.token.strip())

    # Можно пометить токен как использованный (по желанию).
    if not token.is_used:
        token.is_used = True
        await db.flush()

    jwt_token = create_admin_jwt(token)
    # HttpOnly cookie на 24 часа.
    response.set_cookie(
        key=JWT_COOKIE_NAME,
        value=jwt_token,
        httponly=True,
        secure=False,  # в проде лучше True
        samesite="Lax",
        path="/database",
        max_age=60 * 60 * 24,
    )

    # Логируем вход.
    await log_admin_action(
        db=db,
        admin_token_id=token.id,
        action_type="LOGIN",
        entity_type="ADMIN",
        entity_id=token.created_by,
    )

    return {"ok": True}


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    # Кол-во пользователей.
    users_count_result = await db.execute(select(func.count(User.id)))
    users_count = int(users_count_result.scalar() or 0)

    # Общий баланс по ledger.
    # Баланс = DEPOSIT + PROFIT − INVEST − WITHDRAW
    deposits_profit_result = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            LedgerTransaction.type.in_((LEDGER_TYPE_DEPOSIT, LEDGER_TYPE_PROFIT))
        )
    )
    invest_withdraw_result = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            LedgerTransaction.type.in_((LEDGER_TYPE_INVEST, LEDGER_TYPE_WITHDRAW))
        )
    )
    credits = deposits_profit_result.scalar() or Decimal("0")
    debits = invest_withdraw_result.scalar() or Decimal("0")
    total_balance = credits - debits

    # Активная сделка (новая логика: active + окно, или legacy: open).
    active_deal = await get_active_deal(db) or await get_active_deal_legacy(db)
    active_deal_number = None
    active_deal_percent: Optional[Decimal] = None
    active_deal_invested: Optional[Decimal] = None
    active_deal_closes_at = None
    if active_deal:
        active_deal_number = active_deal.number
        active_deal_percent = active_deal.profit_percent or active_deal.percent
        active_deal_closes_at = active_deal.end_at or active_deal.closed_at

        invested_p = await db.execute(
            select(func.coalesce(func.sum(DealParticipation.amount), 0)).where(
                DealParticipation.deal_id == active_deal.id,
            )
        )
        invested_i = await db.execute(
            select(func.coalesce(func.sum(DealInvestment.amount), 0)).where(
                DealInvestment.deal_id == active_deal.id,
                DealInvestment.status == "active",
            )
        )
        active_deal_invested = (invested_p.scalar() or Decimal("0")) + (invested_i.scalar() or Decimal("0"))

    # Pending выводы.
    pending_withdrawals_result = await db.execute(
        select(func.count(WithdrawRequest.id)).where(WithdrawRequest.status == "PENDING")
    )
    pending_withdrawals_count = int(pending_withdrawals_result.scalar() or 0)

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_DASHBOARD",
        entity_type="DASHBOARD",
        entity_id=0,
    )

    return DashboardStats(
        users_count=users_count,
        total_ledger_balance_usdt=total_balance,
        active_deal_number=active_deal_number,
        active_deal_percent=active_deal_percent,
        active_deal_invested_usdt=active_deal_invested,
        active_deal_closes_at=active_deal_closes_at,
        pending_withdrawals_count=pending_withdrawals_count,
    )


@router.get("/users", response_model=PaginatedUsers)
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    query = select(User)
    if search:
        s = f"%{search.strip()}%"
        query = query.where(
            or_(
                User.username.ilike(s),
                func.cast(User.telegram_id, String).ilike(s),
            )
        )
    total_result = await db.execute(
        query.with_only_columns(func.count()).order_by(None)
    )
    total = int(total_result.scalar() or 0)

    query = query.order_by(desc(User.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    users = list(result.scalars().all())

    items = []
    for u in users:
        ledger_balance = await get_balance_usdt(db, u.id)

        # Текущие активные участия (deal_participations в active + deal_investments в open/closed).
        invested_p = await db.execute(
            select(func.coalesce(func.sum(DealParticipation.amount), 0))
            .join(Deal, DealParticipation.deal_id == Deal.id)
            .where(
                DealParticipation.user_id == u.id,
                Deal.status == "active",
            )
        )
        invested_i = await db.execute(
            select(func.coalesce(func.sum(DealInvestment.amount), 0))
            .join(Deal, DealInvestment.deal_id == Deal.id)
            .where(
                DealInvestment.user_id == u.id,
                DealInvestment.status == "active",
                Deal.status.in_(("open", "closed")),
            )
        )
        invested_now = (invested_p.scalar() or Decimal("0")) + (invested_i.scalar() or Decimal("0"))

        items.append(
            UserRow(
                id=u.id,
                telegram_id=u.telegram_id,
                username=u.username,
                balance_usdt=u.balance_usdt,
                ledger_balance_usdt=ledger_balance,
                invested_now_usdt=invested_now,
                created_at=u.created_at,
            )
        )

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_USERS",
        entity_type="USER_LIST",
        entity_id=0,
    )

    return PaginatedUsers(items=items, total=total, page=page, page_size=page_size)


@router.get("/users/{user_id}/ledger", response_model=LedgerList)
async def user_ledger(
    request: Request,
    user_id: int,
    type: Optional[str] = Query(None, description="Фильтр по типу операции"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    # Базовый запрос: выбираем только нужные поля, без legacy-полей блокчейна.
    query = select(
        LedgerTransaction.created_at,
        LedgerTransaction.type,
        LedgerTransaction.amount_usdt,
    ).where(LedgerTransaction.user_id == user_id)

    if type:
        query = query.where(LedgerTransaction.type == type)

    # Фильтры по дате (если переданы ISO-строки).
    if date_from:
        try:
            dt_from = dt.datetime.fromisoformat(date_from)
            query = query.where(LedgerTransaction.created_at >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from")
    if date_to:
        try:
            dt_to = dt.datetime.fromisoformat(date_to)
            query = query.where(LedgerTransaction.created_at <= dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to")

    query = query.order_by(desc(LedgerTransaction.created_at))
    result = await db.execute(query)
    rows = result.all()

    items = []
    for created_at, tx_type, amount_usdt in rows:
        items.append(
            LedgerItem(
                created_at=created_at,
                type=tx_type,
                amount_usdt=amount_usdt,
                deal_id=None,
                comment=None,
            )
        )

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_LEDGER",
        entity_type="USER",
        entity_id=user_id,
    )

    return LedgerList(items=items)


@router.get(
    "/ledger/{user_id}/export",
    response_class=PlainTextResponse,
)
async def export_ledger_csv(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    result = await db.execute(
        select(
            LedgerTransaction.created_at,
            LedgerTransaction.type,
            LedgerTransaction.amount_usdt,
        )
        .where(LedgerTransaction.user_id == user_id)
        .order_by(LedgerTransaction.created_at.asc())
    )
    rows = list(result.all())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "type", "amount_usdt", "comment", "deal_id"])
    for created_at, tx_type, amount_usdt in rows:
        writer.writerow(
            [
                created_at.isoformat(),
                tx_type,
                str(amount_usdt),
                "",
                "",
            ]
        )

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="EXPORT_LEDGER",
        entity_type="USER",
        entity_id=user_id,
    )

    return PlainTextResponse(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=ledger_{user_id}.csv"},
    )


@router.get("/deposits", response_model=PaginatedDeposits)
async def list_deposits(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status_filter: Optional[str] = Query(None, description="waiting, finished, failed, expired, partially_paid"),
    provider_filter: Optional[str] = Query(None, description="nowpayments"),
    user_id_filter: Optional[int] = Query(None),
    order_id_search: Optional[str] = Query(None),
    external_id_search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    sort: str = Query("created_at_desc", description="created_at_desc, created_at_asc, amount_desc, amount_asc, status"),
    db: AsyncSession = Depends(get_db),
):
    """Список пополнений (PaymentInvoice, NOWPayments) с фильтрацией и поиском."""
    admin_token_id, _ = await get_admin_context(request)

    query = (
        select(PaymentInvoice, User.telegram_id, User.username)
        .join(User, PaymentInvoice.user_id == User.id)
    )
    count_stmt = select(func.count(PaymentInvoice.id)).join(User, PaymentInvoice.user_id == User.id)

    if status_filter:
        query = query.where(PaymentInvoice.status == status_filter.strip().lower())
        count_stmt = count_stmt.where(PaymentInvoice.status == status_filter.strip().lower())
    if provider_filter:
        query = query.where(PaymentInvoice.provider == provider_filter.strip().lower())
        count_stmt = count_stmt.where(PaymentInvoice.provider == provider_filter.strip().lower())
    if user_id_filter is not None:
        query = query.where(PaymentInvoice.user_id == user_id_filter)
        count_stmt = count_stmt.where(PaymentInvoice.user_id == user_id_filter)
    if order_id_search and order_id_search.strip():
        query = query.where(PaymentInvoice.order_id.ilike(f"%{order_id_search.strip()}%"))
        count_stmt = count_stmt.where(PaymentInvoice.order_id.ilike(f"%{order_id_search.strip()}%"))
    if external_id_search and external_id_search.strip():
        query = query.where(PaymentInvoice.external_invoice_id.ilike(f"%{external_id_search.strip()}%"))
        count_stmt = count_stmt.where(PaymentInvoice.external_invoice_id.ilike(f"%{external_id_search.strip()}%"))
    if date_from:
        try:
            t_from = dt.datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            query = query.where(PaymentInvoice.created_at >= t_from)
            count_stmt = count_stmt.where(PaymentInvoice.created_at >= t_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from")
    if date_to:
        try:
            t_to = dt.datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            query = query.where(PaymentInvoice.created_at <= t_to)
            count_stmt = count_stmt.where(PaymentInvoice.created_at <= t_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to")

    total_result = await db.execute(count_stmt)
    total = int(total_result.scalar() or 0)

    if sort == "created_at_asc":
        query = query.order_by(PaymentInvoice.created_at.asc())
    elif sort == "amount_desc":
        query = query.order_by(PaymentInvoice.price_amount.desc())
    elif sort == "amount_asc":
        query = query.order_by(PaymentInvoice.price_amount.asc())
    elif sort == "status":
        query = query.order_by(PaymentInvoice.status.asc(), PaymentInvoice.created_at.desc())
    else:
        query = query.order_by(desc(PaymentInvoice.created_at))

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = result.all()

    items = [
        DepositRow(
            id=inv.id,
            order_id=inv.order_id,
            external_invoice_id=inv.external_invoice_id,
            user_id=inv.user_id,
            telegram_id=tg_id,
            username=username,
            amount=inv.price_amount,
            asset="USDT",
            pay_currency=inv.pay_currency,
            network=inv.network,
            provider=inv.provider,
            status=inv.status,
            created_at=inv.created_at,
            paid_at=inv.completed_at,
            completed_at=inv.completed_at,
            balance_credited=inv.is_balance_applied,
        )
        for inv, tg_id, username in rows
    ]

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_DEPOSITS",
        entity_type="DEPOSIT_LIST",
        entity_id=0,
    )

    return PaginatedDeposits(items=items, total=total, page=page, page_size=page_size)


@router.get("/deposits/{deposit_id}", response_model=DepositDetail)
async def get_deposit_detail(
    request: Request,
    deposit_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Детали одного пополнения (PaymentInvoice) и raw webhook payloads."""
    admin_token_id, _ = await get_admin_context(request)

    result = await db.execute(
        select(PaymentInvoice, User.telegram_id, User.username)
        .join(User, PaymentInvoice.user_id == User.id)
        .where(PaymentInvoice.id == deposit_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Deposit not found")

    inv, tg_id, username = row

    webhook_events_result = await db.execute(
        select(PaymentWebhookEvent.payload_json)
        .where(PaymentWebhookEvent.order_id == inv.order_id)
        .order_by(PaymentWebhookEvent.created_at.asc())
    )
    raw_payloads = [r[0] for r in webhook_events_result.all()]

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_DEPOSIT",
        entity_type="PAYMENT_INVOICE",
        entity_id=deposit_id,
    )

    return DepositDetail(
        id=inv.id,
        order_id=inv.order_id,
        external_invoice_id=inv.external_invoice_id,
        invoice_url=inv.invoice_url,
        user_id=inv.user_id,
        telegram_id=tg_id,
        username=username,
        amount=inv.price_amount,
        asset="USDT",
        pay_currency=inv.pay_currency,
        network=inv.network,
        provider=inv.provider,
        status=inv.status,
        created_at=inv.created_at,
        paid_at=inv.completed_at,
        completed_at=inv.completed_at,
        balance_credited=inv.is_balance_applied,
        raw_webhook_payloads=raw_payloads if raw_payloads else None,
    )


@router.get("/deals", response_model=list[DealRow])
async def list_deals(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Список сделок: номер, статус, profit_percent, даты окна."""
    admin_token_id, _ = await get_admin_context(request)

    result = await db.execute(
        select(Deal).order_by(desc(Deal.updated_at))
    )
    deals = result.scalars().all()

    items = [
        DealRow(
            id=d.id,
            number=d.number,
            title=d.title,
            start_at=d.start_at,
            end_at=d.end_at,
            status=d.status,
            profit_percent=d.profit_percent,
            referral_processed=d.referral_processed,
            close_notification_sent=d.close_notification_sent,
            created_at=getattr(d, "created_at", None),
            updated_at=getattr(d, "updated_at", None),
            percent=d.percent,
            opened_at=d.opened_at,
            closed_at=d.closed_at,
            finished_at=d.finished_at,
        )
        for d in deals
    ]

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_DEALS",
        entity_type="DEAL_LIST",
        entity_id=0,
    )

    return items


@router.patch("/deals/{deal_id}", response_model=DealRow)
async def update_deal_percent(
    request: Request,
    deal_id: int,
    body: DealUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Обновить сделку: profit_percent, title, start_at, end_at (для draft/active)."""
    admin_token_id, _ = await get_admin_context(request)

    async with db.begin():
        result = await db.execute(
            select(Deal).where(Deal.id == deal_id).with_for_update()
        )
        deal = result.scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")

        if deal.status not in ("draft", "active", "open", "closed"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Можно менять только для сделок в статусе draft/active/open/closed",
            )

        if body.profit_percent is not None:
            deal.profit_percent = body.profit_percent
        if body.percent is not None:
            deal.percent = body.percent
        if body.title is not None:
            deal.title = body.title
        if body.start_at is not None:
            deal.start_at = body.start_at
        if body.end_at is not None:
            deal.end_at = body.end_at

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="UPDATE_DEAL",
        entity_type="DEAL",
        entity_id=deal_id,
    )

    return DealRow(
        id=deal.id,
        number=deal.number,
        title=deal.title,
        start_at=deal.start_at,
        end_at=deal.end_at,
        status=deal.status,
        profit_percent=deal.profit_percent,
        referral_processed=deal.referral_processed,
        close_notification_sent=deal.close_notification_sent,
        created_at=getattr(deal, "created_at", None),
        updated_at=getattr(deal, "updated_at", None),
        percent=deal.percent,
        opened_at=deal.opened_at,
        closed_at=deal.closed_at,
        finished_at=deal.finished_at,
    )


@router.post("/deals/open-now", response_model=DealRow)
async def open_deal_now(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Создать новую сделку вручную (draft без окна)."""
    admin_token_id, _ = await get_admin_context(request)

    async with db.begin():
        deal = await open_new_deal(db)

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="OPEN_DEAL_MANUAL",
        entity_type="DEAL",
        entity_id=deal.id,
    )

    return DealRow(
        id=deal.id,
        number=deal.number,
        title=deal.title,
        start_at=deal.start_at,
        end_at=deal.end_at,
        status=deal.status,
        profit_percent=deal.profit_percent,
        referral_processed=deal.referral_processed,
        close_notification_sent=deal.close_notification_sent,
        created_at=getattr(deal, "created_at", None),
        updated_at=getattr(deal, "updated_at", None),
        percent=deal.percent,
        opened_at=deal.opened_at,
        closed_at=deal.closed_at,
        finished_at=deal.finished_at,
    )


@router.get("/users/{user_id}", response_model=UserDetail)
async def get_user_detail(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    user_result = await db.execute(select(User).where(User.id == user_id))
    u = user_result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    ledger_balance = await get_balance_usdt(db, u.id)

    investments = []
    part_result = await db.execute(
        select(DealParticipation, Deal)
        .join(Deal, DealParticipation.deal_id == Deal.id)
        .where(DealParticipation.user_id == u.id)
        .order_by(desc(DealParticipation.created_at))
    )
    for p, deal in part_result.all():
        investments.append(
            UserInvestment(
                deal_id=deal.id,
                deal_number=deal.number,
                deal_status=deal.status,
                amount=p.amount,
                profit_amount=None,
                created_at=p.created_at,
            )
        )
    inv_result = await db.execute(
        select(DealInvestment, Deal)
        .join(Deal, DealInvestment.deal_id == Deal.id)
        .where(DealInvestment.user_id == u.id)
        .order_by(desc(DealInvestment.created_at))
    )
    for inv, deal in inv_result.all():
        investments.append(
            UserInvestment(
                deal_id=deal.id,
                deal_number=deal.number,
                deal_status=deal.status,
                amount=inv.amount,
                profit_amount=inv.profit_amount,
                created_at=inv.created_at,
            )
        )
    investments.sort(key=lambda x: x.created_at, reverse=True)

    withdraw_result = await db.execute(
        select(WithdrawRequest)
        .where(WithdrawRequest.user_id == u.id)
        .order_by(desc(WithdrawRequest.created_at))
    )
    withdraws = list(withdraw_result.scalars().all())

    withdrawals = [
        UserWithdrawRequest(
            id=w.id,
            amount=w.amount,
            currency=w.currency,
            address=w.address,
            status=w.status,
            created_at=w.created_at,
            decided_at=w.decided_at,
        )
        for w in withdraws
    ]

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_USER",
        entity_type="USER",
        entity_id=user_id,
    )

    return UserDetail(
        user=UserRow(
            id=u.id,
            telegram_id=u.telegram_id,
            username=u.username,
            balance_usdt=u.balance_usdt,
            ledger_balance_usdt=ledger_balance,
            invested_now_usdt=Decimal("0"),  # можно посчитать при необходимости
            created_at=u.created_at,
        ),
        investments=investments,
        withdrawals=withdrawals,
    )


@router.get("/withdrawals")
async def list_withdrawals(
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    query = select(WithdrawRequest, User).join(User, WithdrawRequest.user_id == User.id)
    if status_filter:
        query = query.where(WithdrawRequest.status == status_filter)
    query = query.order_by(desc(WithdrawRequest.created_at))
    result = await db.execute(query)
    rows = result.all()

    items = [
        {
            "id": req.id,
            "user_id": req.user_id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "amount": str(req.amount),
            "currency": req.currency,
            "address": req.address,
            "status": req.status,
            "created_at": req.created_at.isoformat(),
        }
        for req, user in rows
    ]

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_WITHDRAWALS",
        entity_type="WITHDRAW",
        entity_id=0,
    )

    return {"items": items}


@router.post("/withdrawals/{withdraw_id}/approve")
async def approve_withdrawal(
    request: Request,
    withdraw_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, admin_telegram_id = await get_admin_context(request)

    async with db.begin():
        result = await db.execute(
            select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id).with_for_update()
        )
        req = result.scalar_one_or_none()
        if not req:
            raise HTTPException(status_code=404, detail="Withdraw request not found")
        if req.status != "PENDING":
            # Уже обработано — идемпотентность
            return {"status": req.status}

        user = await db.get(User, req.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Проверяем баланс по леджеру.
        balance = await get_balance_usdt(db, user.id)
        if balance < req.amount:
            raise HTTPException(status_code=400, detail="Недостаточно средств")

        # Создаём ledger WITHDRAW (списание).
        tx = LedgerTransaction(
            user_id=user.id,
            type=LEDGER_TYPE_WITHDRAW,
            amount_usdt=req.amount,
        )
        db.add(tx)

        req.status = "APPROVED"
        req.decided_by = admin_telegram_id
        req.decided_at = dt.datetime.now(dt.timezone.utc)

        # Обновляем кэш баланса.
        new_balance = balance - req.amount
        user.balance_usdt = new_balance

        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="WITHDRAW_APPROVE",
            entity_type="WITHDRAW",
            entity_id=req.id,
        )

    return {"status": "APPROVED"}


@router.post("/withdrawals/{withdraw_id}/reject")
async def reject_withdrawal(
    request: Request,
    withdraw_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, admin_telegram_id = await get_admin_context(request)

    async with db.begin():
        result = await db.execute(
            select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id).with_for_update()
        )
        req = result.scalar_one_or_none()
        if not req:
            raise HTTPException(status_code=404, detail="Withdraw request not found")
        if req.status != "PENDING":
            return {"status": req.status}

        req.status = "REJECTED"
        req.decided_by = admin_telegram_id
        req.decided_at = dt.datetime.now(dt.timezone.utc)

        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="WITHDRAW_REJECT",
            entity_type="WITHDRAW",
            entity_id=req.id,
        )

    return {"status": "REJECTED"}


@router.get("/logs", response_model=PaginatedAdminLogs)
async def list_admin_logs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    query = select(AdminLog)
    if date_from:
        try:
            dt_from = dt.datetime.fromisoformat(date_from)
            query = query.where(AdminLog.created_at >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from")
    if date_to:
        try:
            dt_to = dt.datetime.fromisoformat(date_to)
            query = query.where(AdminLog.created_at <= dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to")
    if search:
        s = f"%{search.strip()}%"
        query = query.where(
            or_(
                AdminLog.action_type.ilike(s),
                AdminLog.entity_type.ilike(s),
            )
        )

    total_result = await db.execute(
        query.with_only_columns(func.count()).order_by(None)
    )
    total = int(total_result.scalar() or 0)

    query = query.order_by(desc(AdminLog.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    logs = list(result.scalars().all())

    items = [
        AdminLogItem(
            id=log.id,
            admin_token_id=log.admin_token_id,
            action_type=log.action_type,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            created_at=log.created_at,
        )
        for log in logs
    ]

    return PaginatedAdminLogs(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/system-settings")
async def get_system_settings_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    result = await db.execute(select(SystemSettings).limit(1))
    row = result.scalar_one()

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_SYSTEM_SETTINGS",
        entity_type="SYSTEM_SETTINGS",
        entity_id=0,
    )

    return {
        "min_deposit_usdt": str(row.min_deposit_usdt),
        "max_deposit_usdt": str(row.max_deposit_usdt),
        "min_withdraw_usdt": str(row.min_withdraw_usdt),
        "max_withdraw_usdt": str(row.max_withdraw_usdt),
        "min_invest_usdt": str(row.min_invest_usdt),
        "max_invest_usdt": str(row.max_invest_usdt),
        "deal_amount_usdt": str(row.deal_amount_usdt),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.patch("/system-settings")
async def update_system_settings_admin(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    field = (str(body.get("field", "")).strip() if body.get("field") is not None else "")
    raw_value = str(body.get("value", "")).replace(",", ".").strip()

    if not field:
        raise HTTPException(status_code=400, detail="field is required")
    try:
        value = Decimal(raw_value)
    except Exception:
        raise HTTPException(status_code=400, detail="value must be a number")
    if value <= 0:
        raise HTTPException(status_code=400, detail="value must be greater than 0")

    allowed_fields = {
        "min_deposit_usdt",
        "max_deposit_usdt",
        "min_withdraw_usdt",
        "max_withdraw_usdt",
        "min_invest_usdt",
        "max_invest_usdt",
        "deal_amount_usdt",
    }
    if field not in allowed_fields:
        raise HTTPException(status_code=400, detail="unknown field")

    async with db.begin():
        result = await db.execute(select(SystemSettings).limit(1).with_for_update())
        row = result.scalar_one()

        if field == "min_deposit_usdt" and value >= row.max_deposit_usdt:
            raise HTTPException(status_code=400, detail="Минимальный депозит должен быть меньше максимального")
        if field == "max_deposit_usdt" and value <= row.min_deposit_usdt:
            raise HTTPException(status_code=400, detail="Максимальный депозит должен быть больше минимального")
        if field == "min_withdraw_usdt" and value >= row.max_withdraw_usdt:
            raise HTTPException(status_code=400, detail="Минимальный вывод должен быть меньше максимального")
        if field == "max_withdraw_usdt" and value <= row.min_withdraw_usdt:
            raise HTTPException(status_code=400, detail="Максимальный вывод должен быть больше минимального")
        if field == "min_invest_usdt" and value >= row.max_invest_usdt:
            raise HTTPException(status_code=400, detail="Минимальная инвестиция должна быть меньше максимальной")
        if field == "max_invest_usdt" and value <= row.min_invest_usdt:
            raise HTTPException(status_code=400, detail="Максимальная инвестиция должна быть больше минимальной")

        setattr(row, field, value)

        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="UPDATE_SYSTEM_SETTINGS",
            entity_type="SYSTEM_SETTINGS",
            entity_id=row.id,
        )

    invalidate_system_settings_cache()
    return {"ok": True}

