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
    WithdrawRequest,
    AdminLog,
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
)
from src.services.ledger_service import (
    LEDGER_TYPE_DEPOSIT,
    LEDGER_TYPE_INVEST,
    LEDGER_TYPE_PROFIT,
    LEDGER_TYPE_WITHDRAW,
    get_balance_usdt,
)


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

    # Активная сделка.
    active_deal_result = await db.execute(
        select(Deal).where(Deal.status == "open").order_by(Deal.opened_at.desc()).limit(1)
    )
    active_deal = active_deal_result.scalar_one_or_none()
    active_deal_number = None
    active_deal_percent: Optional[Decimal] = None
    active_deal_invested: Optional[Decimal] = None
    active_deal_closes_at = None
    if active_deal:
        active_deal_number = active_deal.number
        active_deal_percent = active_deal.percent
        active_deal_closes_at = active_deal.closed_at

        invested_result = await db.execute(
            select(func.coalesce(func.sum(DealInvestment.amount), 0)).where(
                DealInvestment.deal_id == active_deal.id,
                DealInvestment.status == "active",
            )
        )
        active_deal_invested = invested_result.scalar() or Decimal("0")

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

        # Текущие активные инвестиции пользователя.
        invested_result = await db.execute(
            select(func.coalesce(func.sum(DealInvestment.amount), 0))
            .join(Deal, DealInvestment.deal_id == Deal.id)
            .where(
                DealInvestment.user_id == u.id,
                DealInvestment.status == "active",
                Deal.status.in_(("open", "closed")),
            )
        )
        invested_now = invested_result.scalar() or Decimal("0")

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

    # Базовый запрос.
    query = select(LedgerTransaction).where(LedgerTransaction.user_id == user_id)

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
    txs = list(result.scalars().all())

    items = [
        LedgerItem(
            created_at=tx.created_at,
            type=tx.type,
            amount_usdt=tx.amount_usdt,
            deal_id=None,
            comment=None,
        )
        for tx in txs
    ]

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
        select(LedgerTransaction)
        .where(LedgerTransaction.user_id == user_id)
        .order_by(LedgerTransaction.created_at.asc())
    )
    txs = list(result.scalars().all())

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["date", "type", "amount_usdt", "comment", "deal_id"])
    for tx in txs:
        writer.writerow(
            [
                tx.created_at.isoformat(),
                tx.type,
                str(tx.amount_usdt),
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

    invested_result = await db.execute(
        select(DealInvestment, Deal)
        .join(Deal, DealInvestment.deal_id == Deal.id)
        .where(DealInvestment.user_id == u.id)
        .order_by(desc(DealInvestment.created_at))
    )
    investments_rows = invested_result.all()
    investments = [
        UserInvestment(
            deal_id=deal.id,
            deal_number=deal.number,
            deal_status=deal.status,
            amount=inv.amount,
            profit_amount=inv.profit_amount,
            created_at=inv.created_at,
        )
        for inv, deal in investments_rows
    ]

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

