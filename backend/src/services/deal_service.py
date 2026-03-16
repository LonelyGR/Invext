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
from src.services.settings_service import get_system_settings
from src.services.notification_service import broadcast_deal_closed
from src.services.notification_service import broadcast_deal_opened

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
    Сумма участия берётся из SystemSettings.deal_amount_usdt.
    """
    sys_settings = await get_system_settings(db)
    # Сумма участия определяется настройками системы, а не произвольным вводом.
    amount = sys_settings.deal_amount_usdt

    deal_result = await db.execute(
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
    deal = deal_result.scalar_one_or_none()
    if not deal:
        raise ValueError("Нет активной сделки для участия")

    # Лочим пользователя, чтобы защититься от гонок при списании баланса.
    user_locked_result = await db.execute(
        select(User).where(User.id == user.id).with_for_update()
    )
    user_locked = user_locked_result.scalar_one_or_none()
    if not user_locked:
        raise ValueError("User not found")

    existing = await db.execute(
        select(DealParticipation).where(
            DealParticipation.deal_id == deal.id,
            DealParticipation.user_id == user.id,
        )
    )
    if existing.scalar_one_or_none():
        raise ValueError("Вы уже участвуете в этой сделке")

    current_balance = await get_balance_usdt(db, user_locked.id)
    if current_balance < amount:
        raise ValueError("Недостаточно средств для участия")

    tx = LedgerTransaction(
        user_id=user_locked.id,
        type=LEDGER_TYPE_INVEST,
        amount_usdt=amount,
        metadata_json={"deal_id": deal.id},
    )
    db.add(tx)

    participation = DealParticipation(
        deal_id=deal.id,
        user_id=user_locked.id,
        amount=amount,
    )
    db.add(participation)
    await db.flush()

    user_locked.balance_usdt = current_balance - amount
    await db.flush()

    logger.info(
        "Deal participation created: deal_id=%s user_id=%s amount=%s",
        deal.id, user_locked.id, amount,
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
        # Реферальные бонусы теперь начисляются только с депозитов, а не с участия в сделках.
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
        # Следующая сделка открывается в 13:00 (UTC+1), текущая закрывается в 12:00
        next_open_at = (deal.end_at + dt.timedelta(hours=1)) if deal.end_at else None
        await broadcast_deal_closed(
            telegram_ids,
            deal.number,
            profit_pct,
            participant_telegram_ids,
            next_open_at=next_open_at,
        )
        deal.close_notification_sent = True
        await db.flush()

    logger.info("Deal closed: deal_id=%s number=%s", deal.id, deal.number)


async def process_due_deals(db: AsyncSession) -> int:
    """
    Найти сделки с status=active и end_at <= now, для каждой выполнить close_deal_flow.
    Возвращает количество обработанных сделок.
    Транзакция управляется вызывающим кодом (scheduler); не вызывать db.begin() здесь,
    т.к. первый db.execute() уже запускает autobegin.
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
        locked = await db.execute(
            select(Deal).where(Deal.id == deal.id).with_for_update()
        )
        d = locked.scalar_one_or_none()
        if not d or d.status != DEAL_STATUS_ACTIVE:
            continue
        await close_deal_flow(db, d)
    return len(deals)


async def close_active_deal_by_schedule(db: AsyncSession) -> bool:
    """
    Закрыть текущую активную сделку (если есть) и разослать уведомления.
    Используется планировщиком (12:00 UTC+1).
    Идемпотентно: если активной сделки нет — False.
    Транзакция управляется вызывающим кодом (scheduler); не вызывать db.begin() здесь.
    """
    deal_result = await db.execute(
        select(Deal)
        .where(Deal.status == DEAL_STATUS_ACTIVE)
        .order_by(Deal.start_at.desc())
        .limit(1)
        .with_for_update()
    )
    deal = deal_result.scalar_one_or_none()
    if not deal:
        return False
    await close_deal_flow(db, deal)
    return True


async def open_new_deal_by_schedule(
    db: AsyncSession,
    *,
    start_at: dt.datetime,
    end_at: dt.datetime,
) -> Optional[Deal]:
    """
    Открыть новую сделку по расписанию (13:00 UTC+1) и разослать уведомление.
    Защита от дублей: если уже есть active сделка, перекрывающая now — не создаём новую.
    Транзакция управляется вызывающим кодом (scheduler). Не вызывать db.begin() здесь:
    get_active_deal(db) уже выполняет запрос и запускает autobegin на сессии.
    """
    now = dt.datetime.now(dt.timezone.utc)

    # Если уже есть активная сделка, то ничего не делаем.
    active = await get_active_deal(db)
    if active:
        return None

    # Повторная проверка под локом (на случай гонки между воркерами).
    active_locked = await db.execute(
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
        .with_for_update()
    )
    if active_locked.scalar_one_or_none():
        return None

    deal = await open_new_deal(db, start_at=start_at, end_at=end_at)

    # Рассылка всем пользователям (после успешного создания сделки)
    users_result = await db.execute(
        select(User.telegram_id).where(User.telegram_id.isnot(None))
    )
    telegram_ids = [r[0] for r in users_result.all() if r[0]]
    await broadcast_deal_opened(
        telegram_ids,
        deal.number,
        close_at=deal.end_at,
    )

    logger.info("Deal opened by schedule: deal_id=%s number=%s", deal.id, deal.number)
    return deal


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
