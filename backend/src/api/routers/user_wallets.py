"""
Сохранённые кошельки пользователя: список, добавление, удаление.
"""
import logging

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.schemas.wallet import UserWalletCreate, UserWalletItem, UserWalletsListResponse
from src.services.user_wallet_service import get_user_wallets, create_user_wallet, delete_user_wallet

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/wallets", tags=["wallets"])


@router.get("", response_model=UserWalletsListResponse)
async def list_wallets(
    telegram_id: int = Query(..., description="Telegram ID пользователя"),
    db: AsyncSession = Depends(get_db),
):
    """Список сохранённых кошельков пользователя."""
    try:
        wallets = await get_user_wallets(db, telegram_id)
    except Exception as e:
        logger.exception("GET /v1/wallets failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ошибка загрузки кошельков: {e!s}. Убедитесь, что выполнена миграция: alembic upgrade head",
        )
    return UserWalletsListResponse(wallets=[UserWalletItem(**w) for w in wallets])


@router.post("", response_model=UserWalletItem)
async def add_wallet(
    body: UserWalletCreate,
    telegram_id: int = Query(..., description="Telegram ID пользователя"),
    db: AsyncSession = Depends(get_db),
):
    """Добавить кошелёк (название, валюта, адрес)."""
    wallet = await create_user_wallet(
        db, telegram_id, name=body.name, currency=body.currency, address=body.address
    )
    if not wallet:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserWalletItem(**wallet)


@router.delete("/{wallet_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_wallet(
    wallet_id: int,
    telegram_id: int = Query(..., description="Telegram ID пользователя"),
    db: AsyncSession = Depends(get_db),
):
    """Удалить кошелёк по id."""
    deleted = await delete_user_wallet(db, telegram_id, wallet_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Wallet not found")
    return None
