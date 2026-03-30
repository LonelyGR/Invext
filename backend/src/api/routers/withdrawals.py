"""
Эндпоинты: заявки на вывод.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.models import User
from src.schemas.withdraw import WithdrawRequestIn, WithdrawRequestResponse
from src.services.settings_service import get_system_settings
from src.services.withdraw_service import create_withdraw_request, get_my_withdrawals, cancel_withdraw_request

router = APIRouter(prefix="/v1/withdrawals", tags=["withdrawals"])


@router.post("/request", response_model=WithdrawRequestResponse)
async def create_withdraw(
    body: WithdrawRequestIn,
    db: AsyncSession = Depends(get_db),
):
    """Создать заявку на вывод (PENDING). Проверяется баланс."""
    sys_settings = await get_system_settings(db)
    if not getattr(sys_settings, "allow_withdrawals", True):
        raise HTTPException(
            status_code=400,
            detail="На данный момент вывод недоступен по техническим причинам. Пожалуйста, ожидайте.",
        )
    result = await db.execute(select(User).where(User.telegram_id == body.telegram_id))
    user = result.scalar_one_or_none()
    if user is not None and getattr(user, "is_blocked", False):
        raise HTTPException(status_code=403, detail="Аккаунт временно заблокирован администратором.")
    try:
        req = await create_withdraw_request(
            db, body.telegram_id, body.currency, body.amount, body.address
        )
        return req
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/my")
async def my_withdrawals(
    telegram_id: int = Query(..., description="Telegram ID пользователя"),
    db: AsyncSession = Depends(get_db),
):
    """Список заявок на вывод текущего пользователя."""
    items = await get_my_withdrawals(db, telegram_id)
    return [WithdrawRequestResponse.model_validate(r) for r in items]


@router.post("/{withdraw_id}/cancel", response_model=WithdrawRequestResponse)
async def cancel_withdrawal(
    withdraw_id: int,
    telegram_id: int = Query(..., description="Telegram ID пользователя"),
    db: AsyncSession = Depends(get_db),
):
    """Отменить свою заявку на вывод (только PENDING)."""
    try:
        req = await cancel_withdraw_request(db, telegram_id, withdraw_id)
        return WithdrawRequestResponse.model_validate(req)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
