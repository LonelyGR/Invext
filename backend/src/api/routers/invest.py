"""
Эндпоинт инвестиций: списание USDT с баланса (ledger) в инвестиции.
Баланс считается по ledger_transactions, не по полю users.
GET /api/deals/active — для бота: есть ли открытая сделка (раздел «Сделка»).
"""
import logging
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.models import Deal, DealParticipation
from src.models.deal_participation import (
    PARTICIPATION_STATUS_ACTIVE,
    PARTICIPATION_STATUS_IN_PROGRESS,
    PARTICIPATION_STATUS_COMPLETED,
)
from src.models.user import User
from src.schemas.invest import (
    InvestRequest,
    InvestResponse,
    MyDealsResponse,
    DealParticipationItem,
)
from src.services.ledger_service import get_balance_usdt
from src.services.deal_service import get_active_deal, get_active_deal_legacy, participate_in_deal
from src.services.settings_service import get_system_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invest"])


@router.get("/api/deals/active")
async def get_active_deal_info(db: AsyncSession = Depends(get_db)):
    """
    Для бота: есть ли сейчас открытая сделка (окно регистрации).
    Возвращает { "active": true, "deal_number": N, "end_at": "ISO" } или { "active": false }.
    """
    deal = await get_active_deal(db) or await get_active_deal_legacy(db)
    if not deal:
        return {"active": False}
    return {
        "active": True,
        "deal_number": deal.number,
        "end_at": deal.end_at.isoformat() if deal.end_at else (deal.closed_at.isoformat() if getattr(deal, "closed_at", None) else None),
    }


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
        payout_at=participation.payout_at,
    )


@router.get("/api/deals/my", response_model=MyDealsResponse)
async def get_my_deals(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Список участий пользователя в сделках, разделённый на:
    - active_deals: active/in_progress_payout
    - completed_deals: completed
    """
    result = await db.execute(select(User).where(User.telegram_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    rows_result = await db.execute(
        select(DealParticipation, Deal.number)
        .join(Deal, Deal.id == DealParticipation.deal_id)
        .where(DealParticipation.user_id == user.id)
        .order_by(DealParticipation.created_at.desc())
    )
    rows = rows_result.all()

    active_statuses = {PARTICIPATION_STATUS_ACTIVE, PARTICIPATION_STATUS_IN_PROGRESS}
    active_deals: list[DealParticipationItem] = []
    completed_deals: list[DealParticipationItem] = []

    for p, deal_number in rows:
        item = DealParticipationItem(
            deal_number=deal_number,
            amount_usdt=p.amount,
            status=p.status,
            payout_at=p.payout_at,
            created_at=p.created_at,
        )
        if p.status in active_statuses:
            active_deals.append(item)
        elif p.status == PARTICIPATION_STATUS_COMPLETED:
            completed_deals.append(item)

    return MyDealsResponse(
        active_deals=active_deals,
        completed_deals=completed_deals,
    )

