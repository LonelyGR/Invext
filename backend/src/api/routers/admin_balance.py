from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import require_admin_key
from src.db.session import get_db
from src.models.user import User
from src.services.ledger_service import sync_user_balance

router = APIRouter(prefix="/admin", tags=["admin-balance"], dependencies=[Depends(require_admin_key)])


@router.post("/recalculate-balance/{user_id}")
async def recalculate_balance_for_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Пересчитать кэш `users.balance_usdt` по фактическим данным ledger.
    Не создаёт новых ledger-записей.
    """
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    old_balance = user.balance_usdt or Decimal("0")
    new_balance = await sync_user_balance(db, user_id)

    return {
        "user_id": user_id,
        "old_balance_usdt": str(old_balance),
        "new_balance_usdt": str(new_balance),
    }

