"""
Эндпоинты: заявки на вывод.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.schemas.withdraw import WithdrawRequestIn, WithdrawRequestResponse
from src.services.withdraw_service import create_withdraw_request, get_my_withdrawals

router = APIRouter(prefix="/v1/withdrawals", tags=["withdrawals"])


@router.post("/request", response_model=WithdrawRequestResponse)
async def create_withdraw(
    body: WithdrawRequestIn,
    db: AsyncSession = Depends(get_db),
):
    """Создать заявку на вывод (PENDING). Проверяется баланс."""
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
