"""
Эндпоинты: заявки на пополнение.
"""
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.schemas.deposit import DepositRequestIn, DepositRequestResponse, DepositRequestWithUserResponse
from src.services.deposit_service import (
    create_deposit_request,
    get_my_deposits,
)

router = APIRouter(prefix="/v1/deposits", tags=["deposits"])


@router.post("/request", response_model=DepositRequestResponse)
async def create_deposit(
    body: DepositRequestIn,
    db: AsyncSession = Depends(get_db),
):
    """Создать заявку на пополнение (PENDING)."""
    try:
        req = await create_deposit_request(
            db, body.telegram_id, body.currency, body.amount
        )
        return req
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/my")
async def my_deposits(
    telegram_id: int = Query(..., description="Telegram ID пользователя"),
    db: AsyncSession = Depends(get_db),
):
    """Список заявок на пополнение текущего пользователя."""
    items = await get_my_deposits(db, telegram_id)
    return [DepositRequestResponse.model_validate(r) for r in items]
