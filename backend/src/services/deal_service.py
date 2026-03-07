"""
Сделки: активная сделка по окну (start_at — end_at), участие через deal_participations,
закрытие, реферальные начисления, уведомления.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Deal, DealParticipation, LedgerTransaction, ReferralReward, User
from src.models.deal import DEAL_STATUS_ACTIVE, DEAL_STATUS_CLOSED
from src.models.referral_reward import STATUS_PAID
from src.services.ledger_service import (
    LEDGER_TYPE_INVEST,
    LEDGER_TYPE_REFERRAL_BONUS,
    get_balance_usdt,
)
from src.services.notification_service import broadcast_deal_closed

logger = logging.getLogger(__name__)

# Проценты реферального бонуса по уровням (1–10)
REFERRAL_LEVEL_PERCENTS: List[float] = [
    7.0, 2.0, 1.0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5,
]
MAX_REFERRAL_LEVELS = 10


async def get_active_deal(db: AsyncSession) -> Optional[Deal]:
    """Сделка с открытым окном сбора: status=active и now между start_at и end_at."""
    now = dt.datetime.now(dt.timezone.utc)
    result = await db.execute(
        select(Deal)
        .where(
            Deal.status == DEAL_STATUS_ACTIVE,
            Deal.start_at.isnot(None),
            Deal.end_at.isnot(None),
            Deal.start_at <= now,
            Deal.end_at > now,
        )
        .order_by(Deal.start_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def participate_in_deal(
    db: AsyncSession,
    user: User,
    amount: Decimal,
) -> DealParticipation:
    """
    Участие пользователя в текущей активной сделке.
    Один пользователь — одно участие в одной сделке (unique deal_id, user_id).
    """
    async with db.begin():
        deal = await db.execute(
            select(Deal)
            .where(
                Deal.status == DEAL_STATUS_ACTIVE,
                Deal.start_at.isnot(None),
                Deal.end_at.isnot(None),
                Deal.start_at <= dt.datetime.now(dt.timezone.utc),
                Deal.end_at > dt.datetime.now(dt.timezone.utc),
            )
            .order_by(Deal.start_at.desc())
            .limit(1)
            .with_for_update()
        )
        deal = deal.scalar_one_or_none()
        if not deal:
            raise ValueError("Нет активной сделки для участия")

        existing = await db.execute(
            select(DealParticipation).where(
                DealParticipation.deal_id == deal.id,
                DealParticipation.user_id == user.id,
            )
        )
        if existing.scalar_one_or_none():
            raise ValueError("Вы уже участвуете в этой сделке")

        current_balance = await get_balance_usdt(db, user.id)
        if current_balance < amount:
            raise ValueError("Недостаточно средств для участия")

        tx = LedgerTransaction(
            user_id=user.id,
            type=LEDGER_TYPE_INVEST,
            amount_usdt=amount,
            metadata_json={"deal_id": deal.id},
        )
        db.add(tx)

        participation = DealParticipation(
            deal_id=deal.id,
            user_id=user.id,
            amount=amount,
        )
        db.add(participation)
        await db.flush()

        user.balance_usdt = current_balance - amount
        await db.flush()

    logger.info(
        "Deal participation created: deal_id=%s user_id=%s amount=%s",
        deal.id, user.id, amount,
    )
    return participation


async def _get_referrer_chain(db: AsyncSession, user_id: int) -> List[User]:
    """Цепочка рефереров до MAX_REFERRAL_LEVELS."""
    chain: List[User] = []
    current_id: Optional[int] = user_id
    for _ in range(MAX_REFERRAL_LEVELS):
        if current_id is None:
            break
        result = await db.execute(select(User).where(User.id == current_id))
        u = result.scalar_one_or_none()
        if not u or u.referrer_id is None:
            break
        current_id = u.referrer_id
        result_ref = await db.execute(select(User).where(User.id == current_id))
        referrer = result_ref.scalar_one_or_none()
        if referrer:
            chain.append(referrer)
    return chain


async def _process_referral_rewards_for_deal(db: AsyncSession, deal: Deal) -> None:
    """
    По всем участникам сделки: обход цепочки рефереров до 10 уровней.
    Если реферер участвовал в этой же сделке — начислить бонус (referral_rewards + ledger).
    """
    participants_result = await db.execute(
        select(DealParticipation).where(DealParticipation.deal_id == deal.id)
    )
    participants = list(participants_result.scalars().all())
    participant_user_ids = {p.user_id for p in participants}
    participation_by_user = {p.user_id: p for p in participants}

    for participation in participants:
        from_user_id = participation.user_id
        referrers = await _get_referrer_chain(db, from_user_id)
        amount = participation.amount

        for level_index, referrer in enumerate(referrers):
            level = level_index + 1
            if referrer.id not in participant_user_ids:
                continue
            if level > len(REFERRAL_LEVEL_PERCENTS):
                break
            pct = REFERRAL_LEVEL_PERCENTS[level_index]
            reward_amount = (amount * Decimal(str(pct)) / Decimal("100")).quantize(Decimal("0.01"))
            if reward_amount <= 0:
                continue

            reward = ReferralReward(
                deal_id=deal.id,
                from_user_id=from_user_id,
                to_user_id=referrer.id,
                level=level,
                amount=reward_amount,
                status=STATUS_PAID,
            )
            db.add(reward)
            await db.flush()

            ledger_tx = LedgerTransaction(
                user_id=referrer.id,
                type=LEDGER_TYPE_REFERRAL_BONUS,
                amount_usdt=reward_amount,
                metadata_json={
                    "deal_id": deal.id,
                    "from_user_id": from_user_id,
                    "level": level,
                    "referral_reward_id": reward.id,
                },
            )
            db.add(ledger_tx)

            referrer_user = await db.get(User, referrer.id, with_for_update=True)
            if referrer_user:
                new_balance = await get_balance_usdt(db, referrer_user.id)
                referrer_user.balance_usdt = new_balance

            logger.info(
                "Referral reward: deal_id=%s from_user=%s to_user=%s level=%s amount=%s",
                deal.id, from_user_id, referrer.id, level, reward_amount,
            )


async def close_deal_flow(db: AsyncSession, deal: Deal) -> None:
    """
    Закрытие сделки: статус closed, реферальные начисления (один раз),
    рассылка уведомлений (один раз), установка флагов.
    """
    now = dt.datetime.now(dt.timezone.utc)

    deal.status = DEAL_STATUS_CLOSED
    deal.updated_at = now
    if deal.closed_at is None:
        deal.closed_at = now
    await db.flush()

    if not deal.referral_processed:
        await _process_referral_rewards_for_deal(db, deal)
        deal.referral_processed = True
        await db.flush()

    if not deal.close_notification_sent:
        participant_user_ids_result = await db.execute(
            select(DealParticipation.user_id).where(DealParticipation.deal_id == deal.id)
        )
        participant_user_ids = {r[0] for r in participant_user_ids_result.all()}

        users_result = await db.execute(
            select(User.telegram_id, User.id).where(User.telegram_id.isnot(None))
        )
        rows = users_result.all()
        telegram_ids = [r[0] for r in rows if r[0]]
        participant_telegram_ids = {
            r[0] for r in rows
            if r[1] in participant_user_ids and r[0]
        }

        profit_pct = float(deal.profit_percent) if deal.profit_percent is not None else None
        await broadcast_deal_closed(
            telegram_ids,
            deal.number,
            profit_pct,
            participant_telegram_ids,
        )
        deal.close_notification_sent = True
        await db.flush()

    logger.info("Deal closed: deal_id=%s number=%s", deal.id, deal.number)


async def process_due_deals(db: AsyncSession) -> int:
    """
    Найти сделки с status=active и end_at <= now, для каждой выполнить close_deal_flow.
    Возвращает количество обработанных сделок.
    """
    now = dt.datetime.now(dt.timezone.utc)
    result = await db.execute(
        select(Deal).where(
            Deal.status == DEAL_STATUS_ACTIVE,
            Deal.end_at.isnot(None),
            Deal.end_at <= now,
        )
    )
    deals = list(result.scalars().all())
    for deal in deals:
        async with db.begin():
            locked = await db.execute(
                select(Deal).where(Deal.id == deal.id).with_for_update()
            )
            d = locked.scalar_one_or_none()
            if not d or d.status != DEAL_STATUS_ACTIVE:
                continue
            await close_deal_flow(db, d)
    return len(deals)


# --- Совместимость со старым API (админка может ещё использовать) ---

async def get_active_deal_legacy(db: AsyncSession) -> Optional[Deal]:
    """Активная сделка: либо новая (active + окно), либо старая (status=open)."""
    deal = await get_active_deal(db)
    if deal:
        return deal
    result = await db.execute(
        select(Deal).where(Deal.status == "open").order_by(Deal.opened_at.desc()).limit(1)
    )
    return result.scalar_one_or_none()


async def open_new_deal(
    db: AsyncSession,
    title: Optional[str] = None,
    start_at: Optional[dt.datetime] = None,
    end_at: Optional[dt.datetime] = None,
    profit_percent: Optional[Decimal] = None,
) -> Deal:
    """Создать новую сделку (draft или active при переданных start_at/end_at)."""
    from src.models.deal import DEAL_STATUS_ACTIVE, DEAL_STATUS_DRAFT

    result = await db.execute(select(func.coalesce(func.max(Deal.number), 0)))
    last_number = result.scalar_one_or_none() or 0
    number = int(last_number) + 1

    now = dt.datetime.now(dt.timezone.utc)
    status = DEAL_STATUS_DRAFT
    if start_at is not None and end_at is not None and start_at <= now < end_at:
        status = DEAL_STATUS_ACTIVE

    deal = Deal(
        number=number,
        title=title or f"Сделка #{number}",
        start_at=start_at,
        end_at=end_at,
        status=status,
        profit_percent=profit_percent or Decimal("0"),
    )
    db.add(deal)
    await db.flush()
    return deal
