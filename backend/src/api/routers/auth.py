"""
Эндпоинты: авторизация через Telegram, получение профиля /me.
"""
import logging

from fastapi import APIRouter, Depends, Query, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.schemas.user import TelegramAuthIn, UserUpdateIn
from src.services.user_service import get_or_create_user, get_user_with_stats, update_user_profile

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/telegram", tags=["auth"])


def _serialize_user_me(u, data: dict) -> dict:
    """Сборка ответа /me и /auth: профиль + статистика. created_at может быть None в БД."""
    return {
        "id": u.id,
        "telegram_id": u.telegram_id,
        "username": u.username,
        "name": u.name,
        "email": u.email,
        "country": u.country,
        "ref_code": u.ref_code,
        "referrer_id": u.referrer_id,
        "created_at": u.created_at.isoformat() if u.created_at else None,
        "referrals_count": data["referrals_count"],
        "team_deposits_usdt": str(data["team_deposits_usdt"]),
        "team_deposits_usdc": str(data["team_deposits_usdc"]),
        "my_deposits_total_usdt": str(data["my_deposits_total_usdt"]),
        "my_deposits_total_usdc": str(data["my_deposits_total_usdc"]),
        "my_withdrawals_total_usdt": str(data["my_withdrawals_total_usdt"]),
        "my_withdrawals_total_usdc": str(data["my_withdrawals_total_usdc"]),
        "deposits_count": data["deposits_count"],
        "withdrawals_count": data["withdrawals_count"],
    }


@router.post("/auth")
async def telegram_auth(
    body: TelegramAuthIn,
    db: AsyncSession = Depends(get_db),
):
    """
    Создать или обновить пользователя по данным Telegram.
    ref_code_from_start — реферальный код из /start ref_code, привязывает referrer_id.
    """
    try:
        user, _ = await get_or_create_user(
            db,
            telegram_id=body.telegram_id,
            username=body.username,
            name=body.name,
            ref_code_from_start=body.ref_code_from_start,
        )
        data = await get_user_with_stats(db, user.telegram_id)
        if not data:
            return {"id": user.id, "telegram_id": user.telegram_id, "ref_code": user.ref_code}
        return _serialize_user_me(data["user"], data)
    except Exception as e:
        logger.exception("POST /v1/telegram/auth failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Registration failed: {e!s}",
        )


@router.get("/me")
async def get_me(
    telegram_id: int = Query(..., description="Telegram ID пользователя"),
    db: AsyncSession = Depends(get_db),
):
    """Профиль и статистика пользователя."""
    data = await get_user_with_stats(db, telegram_id)
    if not data:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return _serialize_user_me(data["user"], data)


@router.patch("/me")
async def patch_me(
    body: UserUpdateIn,
    telegram_id: int = Query(..., description="Telegram ID пользователя"),
    db: AsyncSession = Depends(get_db),
):
    """Обновить профиль: имя, email, страна."""
    user = await update_user_profile(
        db,
        telegram_id,
        name=body.name,
        email=body.email,
        country=body.country,
    )
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    data = await get_user_with_stats(db, telegram_id)
    return _serialize_user_me(data["user"], data)
