"""
Админ-эндпоинты: список pending заявок, approve/reject, выдача токена для админ-сайта.
Защита: X-ADMIN-KEY или Authorization: Bearer <key>.
"""
import asyncio
import uuid
from datetime import datetime, timezone, timedelta
import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.security import require_admin_key
from src.db.session import get_db
from src.models import AdminToken, User, Deal, WithdrawRequest, PaymentInvoice, AdminLog, BroadcastMessage, BroadcastDelivery, ReferralReward, DealParticipation, DealInvestment, PaymentWebhookEvent, Invoice
from src.models.ledger_transaction import LedgerTransaction
from src.services.ledger_service import (
    LEDGER_TYPE_DEPOSIT,
    LEDGER_TYPE_WITHDRAW,
    get_balance_usdt,
)
from src.services.withdraw_service import (
    get_pending_withdrawals_with_users,
    approve_withdraw,
    reject_withdraw,
)
from src.services.deal_service import (
    get_active_deal,
    open_new_deal,
    process_pending_payouts,
    collection_end_local_for_start,
)
from src.services.notification_service import broadcast_deal_opened

router = APIRouter(prefix="/v1/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])
ADMIN_MAINTENANCE_LOCK = asyncio.Lock()


@router.get("/withdrawals/pending")
async def admin_pending_withdrawals(db: AsyncSession = Depends(get_db)):
    """Список заявок на вывод со статусом PENDING с данными пользователя."""
    items = await get_pending_withdrawals_with_users(db)
    return [
        {
            "id": req.id,
            "user_id": req.user_id,
            "user_telegram_id": user.telegram_id,
            "user_username": user.username,
            "user_name": user.name,
            "currency": req.currency,
            "amount": str(req.amount),
            "address": req.address,
            "status": req.status,
            "created_at": req.created_at.isoformat(),
        }
        for req, user in items
    ]


@router.post("/withdrawals/{withdraw_id}/approve")
async def admin_approve_withdraw(
    withdraw_id: int,
    decided_by_telegram_id: int = Query(..., description="Telegram ID админа"),
    db: AsyncSession = Depends(get_db),
):
    """Подтвердить заявку на вывод (создаётся ledger WITHDRAW COMPLETED)."""
    try:
        req = await approve_withdraw(db, withdraw_id, decided_by_telegram_id)
        return {"status": "ok", "request_id": req.id, "message": "Withdrawal approved"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/withdrawals/{withdraw_id}/reject")
async def admin_reject_withdraw(
    withdraw_id: int,
    decided_by_telegram_id: int = Query(..., description="Telegram ID админа"),
    db: AsyncSession = Depends(get_db),
):
    """Отклонить заявку на вывод."""
    try:
        req = await reject_withdraw(db, withdraw_id, decided_by_telegram_id)
        return {"status": "ok", "request_id": req.id, "message": "Withdrawal rejected"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/dashboard-token")
async def admin_create_dashboard_token(
    telegram_id: int = Query(..., description="Telegram ID админа, для которого создаётся токен"),
    role: str = Query("admin", description="Роль сессии: admin или moderator"),
    db: AsyncSession = Depends(get_db),
):
    """
    Создать одноразовый токен для входа в админ-сайт /database.
    Бот вызывает от имени админа, передаёт его telegram_id. Токен действует 24 часа.
    """
    normalized_role = (role or "admin").strip().lower()
    if normalized_role not in {"admin", "moderator"}:
        raise HTTPException(status_code=400, detail="role must be admin or moderator")
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=24)
    token_str = uuid.uuid4().hex
    record = AdminToken(
        token=token_str,
        expires_at=expires_at,
        is_used=False,
        created_by=telegram_id,
        role=normalized_role,
    )
    db.add(record)
    await db.flush()
    settings = get_settings()
    dashboard_url = settings.app_url.rstrip("/") + "/database"
    return {
        "token": token_str,
        "role": normalized_role,
        "expires_at": expires_at.isoformat(),
        "dashboard_url": dashboard_url,
    }


@router.post("/ledger-adjust")
async def admin_ledger_adjust(
    user_id: int = Query(..., description="ID пользователя"),
    amount_usdt: str = Query(..., description="Сумма корректировки, может быть отрицательной"),
    comment: str | None = Query(None, description="Комментарий к корректировке"),
    decided_by_telegram_id: int = Query(..., description="Telegram ID админа, принявшего решение"),
    db: AsyncSession = Depends(get_db),
):
    """
    Фактическая корректировка баланса через леджер.
    Вызывается ботом от имени админа после нажатия кнопки в Telegram.
    """
    from decimal import Decimal, InvalidOperation  # локальный импорт, чтобы не тянуть наверх

    try:
        amount = Decimal(amount_usdt)
    except (InvalidOperation, ValueError):
        raise HTTPException(status_code=400, detail="Invalid amount_usdt")

    if amount == 0:
        raise HTTPException(status_code=400, detail="Amount must be non-zero")

    async with db.begin():
        user = await db.get(User, user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if amount > 0:
            tx_type = LEDGER_TYPE_DEPOSIT
            stored_amount = amount
        else:
            tx_type = LEDGER_TYPE_WITHDRAW
            stored_amount = -amount

        tx = LedgerTransaction(
            user_id=user.id,
            type=tx_type,
            amount_usdt=stored_amount,
            provider="ADMIN_MANUAL",
            metadata_json={
                "comment": comment,
                "decided_by_telegram_id": decided_by_telegram_id,
            },
        )
        db.add(tx)

        new_balance = await get_balance_usdt(db, user.id)
        user.balance_usdt = new_balance

    return {
        "status": "ok",
        "user_id": user_id,
        "new_balance_usdt": str(new_balance),
    }


@router.post("/deal-force-close")
async def admin_deal_force_close(
    decided_by_telegram_id: int = Query(..., description="Telegram ID админа, принявшего решение"),
    db: AsyncSession = Depends(get_db),
):
    """
    Досрочно закрыть текущую активную сделку.
    Вызывается ботом от имени админа после нажатия кнопки в Telegram.
    Использует общую логику close_active_deal_by_schedule (уведомления + флаги).
    """
    from src.services.deal_service import close_active_deal_by_schedule  # локальный импорт
    from src.services.deal_service import get_active_deal

    active = await get_active_deal(db)
    if not active:
        raise HTTPException(status_code=400, detail="Нет активной сделки для досрочного закрытия.")

    closed = await close_active_deal_by_schedule(db, force=True)
    if not closed:
        raise HTTPException(
            status_code=400,
            detail="Не удалось закрыть сделку (возможно, она уже закрыта).",
        )

    return {
        "status": "ok",
        "deal_id": active.id,
        "deal_number": active.number,
        "decided_by_telegram_id": decided_by_telegram_id,
    }


@router.get("/status-summary")
async def admin_status_summary(db: AsyncSession = Depends(get_db)):
    users_count = int((await db.execute(select(func.count(User.id)))).scalar() or 0)
    pending_withdrawals = int(
        (await db.execute(select(func.count(WithdrawRequest.id)).where(WithdrawRequest.status == "PENDING"))).scalar() or 0
    )
    deposits_count = int((await db.execute(select(func.count(PaymentInvoice.id)))).scalar() or 0)
    active = await get_active_deal(db)
    return {
        "users_count": users_count,
        "pending_withdrawals": pending_withdrawals,
        "deposits_count": deposits_count,
        "active_deal": {
            "id": active.id,
            "number": active.number,
            "start_at": active.start_at.isoformat() if active.start_at else None,
            "end_at": active.end_at.isoformat() if active.end_at else None,
            "status": active.status,
        } if active else None,
    }


@router.post("/deals/open-now")
async def admin_open_deal_now(
    decided_by_telegram_id: int = Query(..., description="Telegram ID админа"),
    db: AsyncSession = Depends(get_db),
):
    active = await get_active_deal(db)
    if active:
        raise HTTPException(status_code=400, detail=f"Уже есть активная сделка #{active.number}")

    # Важно: используем транзакцию, иначе Deal может не быть закоммичен,
    # и бот/сайт временно будут видеть "нет активного сбора".
    await process_pending_payouts(db)
    from zoneinfo import ZoneInfo

    now_utc = dt.datetime.now(dt.timezone.utc)
    now_local = now_utc.astimezone(ZoneInfo("Europe/Chisinau"))
    if now_local.weekday() in (5, 6):
        raise HTTPException(status_code=400, detail="В выходные открытие нового сбора отключено.")
    start_local = now_local
    close_local = collection_end_local_for_start(start_local)
    start_at = start_local.astimezone(dt.timezone.utc)
    end_at = close_local.astimezone(dt.timezone.utc)

    async with db.begin():
        deal = await open_new_deal(db, start_at=start_at, end_at=end_at)
    users_result = await db.execute(select(User.telegram_id).where(User.telegram_id.isnot(None)))
    telegram_ids = [r[0] for r in users_result.all() if r[0]]
    await broadcast_deal_opened(telegram_ids, deal.number, close_at=deal.end_at)
    return {
        "status": "ok",
        "deal_id": deal.id,
        "deal_number": deal.number,
        "decided_by_telegram_id": decided_by_telegram_id,
    }


async def _truncate_tables_safe(db: AsyncSession, table_names: list[str]) -> int:
    total = 0
    for name in table_names:
        total += int((await db.execute(text(f'SELECT COUNT(*) FROM "{name}"'))).scalar() or 0)
    table_names_sql = ", ".join(f'"{name}"' for name in table_names)
    await db.execute(text(f"TRUNCATE TABLE {table_names_sql} RESTART IDENTITY CASCADE"))
    await db.flush()
    return total


@router.post("/maintenance/clear-logs")
async def admin_maintenance_clear_logs(
    confirm: str = Query(..., description='Должен быть "CLEAR_LOGS"'),
    db: AsyncSession = Depends(get_db),
):
    if confirm.strip().upper() != "CLEAR_LOGS":
        raise HTTPException(status_code=400, detail='confirm must be "CLEAR_LOGS"')
    if ADMIN_MAINTENANCE_LOCK.locked():
        raise HTTPException(status_code=409, detail="Maintenance operation already in progress")
    async with ADMIN_MAINTENANCE_LOCK:
        total = await _truncate_tables_safe(db, [AdminLog.__table__.name])
        return {"status": "ok", "cleared_rows": total}


@router.post("/maintenance/clear-broadcasts")
async def admin_maintenance_clear_broadcasts(
    confirm: str = Query(..., description='Должен быть "CLEAR_BROADCASTS"'),
    db: AsyncSession = Depends(get_db),
):
    if confirm.strip().upper() != "CLEAR_BROADCASTS":
        raise HTTPException(status_code=400, detail='confirm must be "CLEAR_BROADCASTS"')
    if ADMIN_MAINTENANCE_LOCK.locked():
        raise HTTPException(status_code=409, detail="Maintenance operation already in progress")
    async with ADMIN_MAINTENANCE_LOCK:
        total = await _truncate_tables_safe(db, [BroadcastDelivery.__table__.name, BroadcastMessage.__table__.name])
        return {"status": "ok", "cleared_rows": total}


@router.post("/maintenance/clear-deals")
async def admin_maintenance_clear_deals(
    confirm: str = Query(..., description='Должен быть "CLEAR_DEALS"'),
    db: AsyncSession = Depends(get_db),
):
    if confirm.strip().upper() != "CLEAR_DEALS":
        raise HTTPException(status_code=400, detail='confirm must be "CLEAR_DEALS"')
    if ADMIN_MAINTENANCE_LOCK.locked():
        raise HTTPException(status_code=409, detail="Maintenance operation already in progress")
    async with ADMIN_MAINTENANCE_LOCK:
        total = await _truncate_tables_safe(
            db,
            [
                ReferralReward.__table__.name,
                DealParticipation.__table__.name,
                DealInvestment.__table__.name,
                Deal.__table__.name,
            ],
        )
        return {"status": "ok", "cleared_rows": total}


@router.post("/maintenance/clear-payments")
async def admin_maintenance_clear_payments(
    confirm: str = Query(..., description='Должен быть "CLEAR_PAYMENTS"'),
    db: AsyncSession = Depends(get_db),
):
    if confirm.strip().upper() != "CLEAR_PAYMENTS":
        raise HTTPException(status_code=400, detail='confirm must be "CLEAR_PAYMENTS"')
    if ADMIN_MAINTENANCE_LOCK.locked():
        raise HTTPException(status_code=409, detail="Maintenance operation already in progress")
    async with ADMIN_MAINTENANCE_LOCK:
        total = await _truncate_tables_safe(
            db,
            [
                PaymentWebhookEvent.__table__.name,
                PaymentInvoice.__table__.name,
                Invoice.__table__.name,
            ],
        )
        return {"status": "ok", "cleared_rows": total}
