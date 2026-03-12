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
from src.services.deal_service import participate_in_deal
from src.services.settings_service import get_system_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invest"])

@router.post("/api/invest", response_model=InvestResponse)
async def invest(
    body: InvestRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Списать виртуальный баланс USDT в инвестиции.
    Минимальная сумма — берется из SystemSettings. Баланс считается по ledger.
    """
    sys_settings = await get_system_settings(db)
    amount = body.amount_usdt.quantize(Decimal("0.01"))
    if amount < sys_settings.min_invest_usdt:
        raise HTTPException(
            status_code=400,
            detail=f"Минимальная сумма инвестиций — {sys_settings.min_invest_usdt} USDT",
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
            detail=f"Недостаточно средств. Минимальная сумма инвестиций — {sys_settings.min_invest_usdt} USDT.",
        )

    try:
        participation = await participate_in_deal(db, user, amount)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    new_balance = await get_balance_usdt(db, user.id)
    logger.info(
        "Deal participation created: user_id=%s deal_id=%s amount=%s new_balance=%s",
        user.id,
        participation.deal_id,
        amount,
        new_balance,
    )

    return InvestResponse(
        invested_amount_usdt=amount,
        balance_usdt=new_balance,
    )

