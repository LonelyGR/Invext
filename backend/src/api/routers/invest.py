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
from src.models import Deal, DealParticipation, LedgerTransaction
from src.models.deal import DEAL_STATUS_CLOSED
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
    PendingPayoutInfo,
)
from src.services.ledger_service import LEDGER_TYPE_INVEST, get_balance_usdt
from src.services.deal_service import (
    calculate_payout_at_for_deal_start,
    get_active_deal,
    get_active_deal_legacy,
    participate_in_deal,
)
from src.services.settings_service import get_system_settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invest"])


def _q_amt(a: Decimal) -> Decimal:
    return a.quantize(Decimal("0.000001"))


async def _invest_ledger_proof_pairs(
    db: AsyncSession, internal_user_id: int
) -> tuple[int, set[tuple[int, Decimal]]]:
    """
    Количество записей INVEST и множество пар (deal_id из metadata, сумма),
    подтверждающих реальное участие. Участие в сделке создаётся только вместе с INVEST
    с тем же deal_id и суммой (см. participate_in_deal).
    """
    r = await db.execute(
        select(LedgerTransaction.metadata_json, LedgerTransaction.amount_usdt).where(
            LedgerTransaction.user_id == internal_user_id,
            LedgerTransaction.type == LEDGER_TYPE_INVEST,
        )
    )
    proof_pairs: set[tuple[int, Decimal]] = set()
    n_invest = 0
    for meta, amt in r.all():
        n_invest += 1
        if not meta or not isinstance(meta, dict):
            continue
        raw = meta.get("deal_id")
        if raw is None:
            continue
        try:
            did = int(raw)
        except (TypeError, ValueError):
            continue
        proof_pairs.add((did, _q_amt(amt)))
    return n_invest, proof_pairs


async def _pending_payout_for_user(db: AsyncSession, internal_user_id: int) -> PendingPayoutInfo:
    """
    Ожидание выплаты: участие in_progress_payout по последнему закрытому сбору пользователя.
    Время выплаты пересчитывается из deal_schedule_json (админка), как в participate_in_deal.
    """
    rows_result = await db.execute(
        select(DealParticipation, Deal)
        .join(Deal, Deal.id == DealParticipation.deal_id)
        .where(
            DealParticipation.user_id == internal_user_id,
            DealParticipation.status == PARTICIPATION_STATUS_IN_PROGRESS,
            Deal.status == DEAL_STATUS_CLOSED,
        )
        .order_by(Deal.closed_at.desc().nulls_last(), Deal.id.desc())
    )
    candidates = list(rows_result.all())
    if not candidates:
        return PendingPayoutInfo(pending=False)

    n_invest, proof_pairs = await _invest_ledger_proof_pairs(db, internal_user_id)
    if n_invest == 0:
        return PendingPayoutInfo(pending=False)

    use_proof = bool(proof_pairs)
    chosen: tuple[DealParticipation, Deal] | None = None
    for p, deal in candidates:
        if use_proof:
            key = (p.deal_id, _q_amt(p.amount))
            if key not in proof_pairs:
                continue
        chosen = (p, deal)
        break

    if not chosen:
        return PendingPayoutInfo(pending=False)

    p, deal = chosen
    settings = await get_system_settings(db)
    payout_at = calculate_payout_at_for_deal_start(
        deal.start_at,
        getattr(settings, "deal_schedule_json", None),
    )
    return PendingPayoutInfo(
        pending=True,
        deal_number=deal.number,
        payout_at=payout_at,
        amount_usdt=p.amount,
    )


@router.get("/api/deals/pending-payout-info", response_model=PendingPayoutInfo)
async def pending_payout_info(
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Для бота: блок «Ожидает выплаты» — последний закрытый сбор пользователя и выплата по расписанию админки."""
    result = await db.execute(select(User).where(User.telegram_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return PendingPayoutInfo(pending=False)
    return await _pending_payout_for_user(db, user.id)


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
        "risk_level": getattr(deal, "risk_level", None),
        "risk_note": getattr(deal, "risk_note", None),
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
    if not getattr(sys_settings, "allow_investments", True):
        raise HTTPException(
            status_code=400,
            detail="Участие в сделках временно недоступно по техническим причинам. Попробуйте позже.",
        )
    amount = body.amount_usdt.quantize(Decimal("0.01"))
    # Бизнес-правило: сумма участия фиксированная (SystemSettings.deal_amount_usdt), отклоняем любые другие суммы.
    fixed_amount = Decimal(str(getattr(sys_settings, "deal_amount_usdt", Decimal("50")))).quantize(Decimal("0.01"))
    if amount != fixed_amount:
        raise HTTPException(
            status_code=400,
            detail=f"Сумма участия в сделке фиксированная — {fixed_amount} USDT.",
        )
    if amount < sys_settings.min_invest_usdt:
        raise HTTPException(
            status_code=400,
            detail=f"Минимальная сумма инвестиций — {sys_settings.min_invest_usdt} USDT",
        )

    result = await db.execute(select(User).where(User.telegram_id == body.user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if getattr(user, "is_blocked", False):
        raise HTTPException(
            status_code=403,
            detail="Аккаунт временно заблокирован администратором.",
        )

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

    Показываем участие только если есть запись INVEST с тем же deal_id в metadata и той же
    суммой (пара deal_id+amount). Так отсекаются «лишние» строки в deal_participations без
    реального списания (в т.ч. когда сделку «пропустили», а в БД остался мусор).
    Если ни у одного INVEST нет deal_id в metadata (очень старые данные) — доверяем
    deal_participations как раньше.
    """
    result = await db.execute(select(User).where(User.telegram_id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return MyDealsResponse(active_deals=[], completed_deals=[])

    rows_result = await db.execute(
        select(DealParticipation, Deal.number)
        .join(Deal, Deal.id == DealParticipation.deal_id)
        .where(DealParticipation.user_id == user.id)
        .order_by(DealParticipation.created_at.desc())
    )
    rows = rows_result.all()

    n_invest, proof_pairs = await _invest_ledger_proof_pairs(db, user.id)
    if n_invest == 0 and rows:
        logger.warning(
            "get_my_deals: user internal_id=%s telegram_id=%s has %s deal_participations but no INVEST ledger; hiding all",
            user.id,
            user_id,
            len(rows),
        )
        return MyDealsResponse(active_deals=[], completed_deals=[])

    use_ledger_proof = bool(proof_pairs)
    if not use_ledger_proof and n_invest > 0:
        logger.debug(
            "get_my_deals: user_id=%s has INVEST rows but none with deal_id in metadata; using deal_participations as-is",
            user.id,
        )

    active_statuses = {PARTICIPATION_STATUS_ACTIVE, PARTICIPATION_STATUS_IN_PROGRESS}
    active_deals: list[DealParticipationItem] = []
    completed_deals: list[DealParticipationItem] = []

    for p, deal_number in rows:
        if use_ledger_proof:
            key = (p.deal_id, _q_amt(p.amount))
            if key not in proof_pairs:
                logger.warning(
                    "get_my_deals: skipping participation id=%s user_id=%s deal_id=%s amount=%s "
                    "(no matching INVEST ledger row for this deal_id+amount)",
                    p.id,
                    user.id,
                    p.deal_id,
                    p.amount,
                )
                continue
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

