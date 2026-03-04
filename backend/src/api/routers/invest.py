"""
Эндпоинт инвестиций: списание USDT с баланса (ledger) в инвестиции.
Баланс считается по ledger_transactions, не по полю users.
"""
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.models.user import User
from src.schemas.invest import InvestRequest, InvestResponse
from src.services.ledger_service import get_balance_usdt
from src.services.deal_service import invest_into_active_deal

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invest"])

MIN_INVEST_USDT = Decimal("50")


@router.post("/api/invest", response_model=InvestResponse)
async def invest(
    body: InvestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Списать виртуальный баланс USDT в инвестиции.
    Минимальная сумма — 50 USDT. Баланс считается по ledger.
    """
    amount = body.amount_usdt.quantize(Decimal("0.01"))
    if amount < MIN_INVEST_USDT:
        raise HTTPException(
            status_code=400,
            detail="Минимальная сумма инвестиций — 50 USDT",
        )

    result = await db.execute(select(User).where(User.telegram_id == body.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    # Проверяем баланс через ledger (до попытки инвестирования).
    current_balance = await get_balance_usdt(db, user.id)
    if current_balance < amount:
        raise HTTPException(
            status_code=400,
            detail="Недостаточно средств. Минимальная сумма инвестиций — 50 USDT.",
        )

    try:
        inv = await invest_into_active_deal(db, user, amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    new_balance = await get_balance_usdt(db, user.id)
    logger.info(
        "Deal investment created: user_id=%s deal_id=%s amount=%s new_balance=%s",
        user.id,
        inv.deal_id,
        amount,
        new_balance,
    )

    return InvestResponse(
        invested_amount_usdt=amount,
        balance_usdt=new_balance,
    )
