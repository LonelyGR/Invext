"""
Админ-эндпоинты: список pending заявок, approve/reject, выдача токена для админ-сайта.
Защита: X-ADMIN-KEY или Authorization: Bearer <key>.
"""
import uuid
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.core.security import require_admin_key
from src.db.session import get_db
from src.models import AdminToken, User
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

router = APIRouter(prefix="/v1/admin", tags=["admin"], dependencies=[Depends(require_admin_key)])


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
    db: AsyncSession = Depends(get_db),
):
    """
    Создать одноразовый токен для входа в админ-сайт /database.
    Бот вызывает от имени админа, передаёт его telegram_id. Токен действует 24 часа.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=24)
    token_str = uuid.uuid4().hex
    record = AdminToken(
        token=token_str,
        expires_at=expires_at,
        is_used=False,
        created_by=telegram_id,
    )
    db.add(record)
    await db.flush()
    settings = get_settings()
    dashboard_url = settings.app_url.rstrip("/") + "/database"
    return {
        "token": token_str,
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
