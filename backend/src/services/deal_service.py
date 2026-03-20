"""
Сделки: активная сделка по окну (start_at — end_at), участие через deal_participations,
закрытие, реферальные начисления, уведомления.
"""
from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Deal, DealParticipation, LedgerTransaction, ReferralReward, User
from src.models.deal import DEAL_STATUS_ACTIVE, DEAL_STATUS_CLOSED
from src.models.deal_participation import (
    PARTICIPATION_STATUS_ACTIVE,
    PARTICIPATION_STATUS_COMPLETED,
    PARTICIPATION_STATUS_IN_PROGRESS,
)
from src.models.referral_reward import STATUS_PAID, STATUS_MISSED
from src.services.ledger_service import (
    LEDGER_TYPE_INVEST,
    LEDGER_TYPE_INVEST_RETURN,
    LEDGER_TYPE_PROFIT,
    LEDGER_TYPE_REFERRAL_BONUS,
    get_balance_usdt,
)
from src.services.referral_service import (
    apply_referral_rewards_for_investment,
    get_potential_referral_bonuses_for_deal,
)
from src.services.settings_service import get_system_settings
from src.services.notification_service import (
    broadcast_deal_closed,
    broadcast_deal_opened,
    notify_payout_complete,
    send_referral_bonus_reminder,
)

logger = logging.getLogger(__name__)
PAYOUT_TZ = ZoneInfo("Europe/Chisinau")

# Проценты реферального бонуса по уровням (1–10)
REFERRAL_LEVEL_PERCENTS: List[float] = [
    7.0, 2.0, 1.0, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5,
]
MAX_REFERRAL_LEVELS = 10


def calculate_payout_at_for_investment(now_utc: Optional[dt.datetime] = None) -> dt.datetime:
    """
    Фиксированный график выплаты (Europe/Chisinau):
    - инвестиция до 12:00 -> T+1;
    - инвестиция с 13:00 и позже -> T+2;
    - пятница с 13:00, суббота, воскресенье -> ближайший вторник;
    - время выплаты всегда 15:00.
    Возвращает datetime в UTC для хранения в БД.
    """
    now_utc = now_utc or dt.datetime.now(dt.timezone.utc)
    local_now = now_utc.astimezone(PAYOUT_TZ)
    local_date = local_now.date()
    weekday = local_now.weekday()  # Mon=0 ... Sun=6
    hour = local_now.hour

    if weekday == 5:  # Saturday
        days_to_tuesday = 3
        payout_date = local_date + dt.timedelta(days=days_to_tuesday)
    elif weekday == 6:  # Sunday
        days_to_tuesday = 2
        payout_date = local_date + dt.timedelta(days=days_to_tuesday)
    elif weekday == 4 and hour >= 13:  # Friday after 13:00
        days_to_tuesday = 4
        payout_date = local_date + dt.timedelta(days=days_to_tuesday)
    else:
        days_to_add = 1 if hour < 12 else 2
        payout_date = local_date + dt.timedelta(days=days_to_add)
        # Если расчет попал на выходные — переносим на ближайший вторник.
        if payout_date.weekday() == 5:  # Saturday
            payout_date = payout_date + dt.timedelta(days=3)
        elif payout_date.weekday() == 6:  # Sunday
            payout_date = payout_date + dt.timedelta(days=2)

    payout_local = dt.datetime.combine(
        payout_date,
        dt.time(hour=15, minute=0, second=0, tzinfo=PAYOUT_TZ),
    )
    return payout_local.astimezone(dt.timezone.utc)


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
    Фактическая сумма участия передаётся из API /api/invest (ботом) и
    уже проверена на минималку/баланс.
    """

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
        status=PARTICIPATION_STATUS_ACTIVE,
        payout_at=calculate_payout_at_for_investment(),
    )
    db.add(participation)
    await db.flush()

    user_locked.balance_usdt = current_balance - amount
    await db.flush()

    # Инвестиционная реферальная линия (10 уровней по 0.5% с инвестиции),
    # учитывающая участие реферера в этой же сделке.
    await apply_referral_rewards_for_investment(db, investor=user_locked, deal=deal, investment_amount=amount)

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
    Закрытие сделки:
    1. Статус сделки → closed.
    2. Рассчитываем profit_amount для каждого участия, статус → in_progress_payout.
       Прибыль НЕ зачисляется на баланс (зачисление при открытии следующей сделки).
    3. Реферальная обработка (флаг).
    4. Уведомление: «средства в работе».
    """
    now = dt.datetime.now(dt.timezone.utc)

    deal.status = DEAL_STATUS_CLOSED
    deal.updated_at = now
    if deal.closed_at is None:
        deal.closed_at = now
    await db.flush()

    profit_percent = deal.profit_percent or deal.percent

    parts_result = await db.execute(
        select(DealParticipation).where(
            DealParticipation.deal_id == deal.id,
            DealParticipation.status == PARTICIPATION_STATUS_ACTIVE,
        )
    )
    participations = list(parts_result.scalars().all())

    for p in participations:
        if profit_percent is not None:
            profit = (
                p.amount * Decimal(str(profit_percent)) / Decimal("100")
            ).quantize(Decimal("0.000001"))
            p.profit_amount = profit
        else:
            p.profit_amount = Decimal("0")
        p.status = PARTICIPATION_STATUS_IN_PROGRESS

    if participations:
        await db.flush()

    if not deal.referral_processed:
        deal.referral_processed = True
        await db.flush()

    if not deal.close_notification_sent:
        participant_user_ids_result = await db.execute(
            select(DealParticipation.user_id).where(DealParticipation.deal_id == deal.id)
        )
        participant_user_ids = {r[0] for r in participant_user_ids_result.all()}

        users_result = await db.execute(
            select(User.id, User.telegram_id).where(User.telegram_id.isnot(None))
        )
        rows = users_result.all()
        user_id_by_tid = {r[1]: r[0] for r in rows if r[1]}
        telegram_ids = list(user_id_by_tid.keys())

        participant_telegram_ids = {
            tid for tid, uid in user_id_by_tid.items() if uid in participant_user_ids
        }

        referral_profit_by_telegram: dict[int, float] = {}
        referral_missed_by_telegram: dict[int, float] = {}

        lt_result = await db.execute(
            select(
                LedgerTransaction.user_id,
                LedgerTransaction.amount_usdt,
                LedgerTransaction.metadata_json,
            ).where(LedgerTransaction.type == LEDGER_TYPE_REFERRAL_BONUS)
        )
        for uid, amount, meta in lt_result.all():
            if not meta or meta.get("source") != "investment":
                continue
            if int(meta.get("deal_id", 0)) != deal.id:
                continue
            for tid, user_id in user_id_by_tid.items():
                if user_id == uid:
                    referral_profit_by_telegram[tid] = referral_profit_by_telegram.get(tid, 0.0) + float(amount)

        rr_result = await db.execute(
            select(ReferralReward.to_user_id, ReferralReward.amount).where(
                ReferralReward.deal_id == deal.id,
                ReferralReward.status == STATUS_MISSED,
            )
        )
        for to_uid, amount in rr_result.all():
            for tid, user_id in user_id_by_tid.items():
                if user_id == to_uid:
                    referral_missed_by_telegram[tid] = referral_missed_by_telegram.get(tid, 0.0) + float(amount)

        profit_pct = float(deal.profit_percent) if deal.profit_percent is not None else None
        next_open_at = (deal.end_at + dt.timedelta(hours=1)) if deal.end_at else None
        await broadcast_deal_closed(
            telegram_ids,
            deal.number,
            profit_pct,
            participant_telegram_ids=participant_telegram_ids,
            referral_profit_by_telegram=referral_profit_by_telegram,
            referral_missed_by_telegram=referral_missed_by_telegram,
            next_open_at=next_open_at,
        )
        deal.close_notification_sent = True
        await db.flush()

    logger.info("Deal closed: deal_id=%s number=%s", deal.id, deal.number)


async def process_pending_payouts(db: AsyncSession) -> int:
    """
    Обработка всех инвестиций в статусе in_progress_payout:
    — зачисляем тело + прибыль на баланс (PROFIT ledger entry)
    — статус → completed, payout_at = now
    — отправляем персональное уведомление каждому пользователю.
    Вызывается перед открытием новой сделки.
    Возвращает кол-во обработанных записей.
    """
    # Не выплачиваем сразу после закрытия: «средства в работе», payout — не раньше чем через 1 час.
    now = dt.datetime.now(dt.timezone.utc)
    eligible_before = now - dt.timedelta(hours=1)

    # Важно для идемпотентности при нескольких воркерах:
    # лочим строки и пропускаем уже залоченные (чтобы не выплатить дважды).
    parts_result = await db.execute(
        select(DealParticipation)
        .join(Deal, DealParticipation.deal_id == Deal.id)
        .where(
            DealParticipation.status == PARTICIPATION_STATUS_IN_PROGRESS,
            Deal.closed_at.isnot(None),
            Deal.closed_at <= eligible_before,
        )
        .order_by(DealParticipation.deal_id)
        .with_for_update(skip_locked=True)
    )
    participations = list(parts_result.scalars().all())
    if not participations:
        return 0
    processed = 0

    deal_cache: dict[int, Deal] = {}
    affected_user_ids: set[int] = set()

    for p in participations:
        try:
            profit = p.profit_amount or Decimal("0")

            if p.deal_id not in deal_cache:
                deal_obj = await db.get(Deal, p.deal_id)
                if deal_obj:
                    deal_cache[p.deal_id] = deal_obj

            deal = deal_cache.get(p.deal_id)
            meta_base = {
                "deal_id": p.deal_id,
                "deal_number": deal.number if deal else None,
                "participation_id": p.id,
            }

            tx_return = LedgerTransaction(
                user_id=p.user_id,
                type=LEDGER_TYPE_INVEST_RETURN,
                amount_usdt=p.amount,
                metadata_json={**meta_base, "base_amount": str(p.amount)},
            )
            db.add(tx_return)

            if profit > 0:
                tx_profit = LedgerTransaction(
                    user_id=p.user_id,
                    type=LEDGER_TYPE_PROFIT,
                    amount_usdt=profit,
                    metadata_json={**meta_base, "profit_amount": str(profit)},
                )
                db.add(tx_profit)

            p.status = PARTICIPATION_STATUS_COMPLETED
            p.payout_at = now
            affected_user_ids.add(p.user_id)
            processed += 1
        except Exception:
            logger.exception("process_pending_payouts: failed to process participation %s", p.id)

    await db.flush()

    for uid in affected_user_ids:
        user_obj = await db.get(User, uid)
        if user_obj:
            new_balance = await get_balance_usdt(db, uid)
            user_obj.balance_usdt = new_balance

    await db.flush()

    # Отправляем персональные уведомления о выплате.
    user_tids: dict[int, int] = {}
    if affected_user_ids:
        users_result = await db.execute(
            select(User.id, User.telegram_id).where(
                User.id.in_(affected_user_ids),
                User.telegram_id.isnot(None),
            )
        )
        user_tids = {r[0]: r[1] for r in users_result.all() if r[1]}

    for p in participations:
        tid = user_tids.get(p.user_id)
        if not tid or p.status != PARTICIPATION_STATUS_COMPLETED:
            continue
        try:
            deal = deal_cache.get(p.deal_id)
            deal_num = deal.number if deal else 0
            profit = p.profit_amount or Decimal("0")
            total = (p.amount + profit).quantize(Decimal("0.000001"))
            await notify_payout_complete(
                telegram_id=tid,
                deal_number=deal_num,
                amount=p.amount,
                profit=profit,
                total=total,
            )
        except Exception:
            logger.exception("notify_payout_complete failed for user_id=%s participation=%s", p.user_id, p.id)

    logger.info("process_pending_payouts: processed=%s users=%s", processed, len(affected_user_ids))
    return processed


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


async def send_referral_bonus_reminders_for_active_deal(db: AsyncSession) -> int:
    """
    Найти текущую активную сделку и разослать напоминания пользователям,
    у которых уже накопилась потенциальная реферальная прибыль по этой сделке,
    но которые ещё не участвуют.
    Возвращает количество отправленных напоминаний.
    """
    deal = await get_active_deal(db)
    if not deal:
        return 0

    # Считаем потенциальные бонусы по этой сделке.
    bonuses_by_user = await get_potential_referral_bonuses_for_deal(db, deal)
    if not bonuses_by_user:
        return 0

    # Маппинг user_id -> telegram_id
    user_ids = list(bonuses_by_user.keys())
    users_result = await db.execute(
        select(User.id, User.telegram_id).where(
            User.id.in_(user_ids),
            User.telegram_id.isnot(None),
        )
    )
    rows = users_result.all()
    sent = 0
    for uid, tid in rows:
        if not tid:
            continue
        bonus = bonuses_by_user.get(uid)
        if not bonus or bonus <= 0:
            continue
        ok = await send_referral_bonus_reminder(
            telegram_id=tid,
            deal_number=deal.number,
            bonus_amount=float(bonus),
            close_at=deal.end_at,
        )
        if ok:
            sent += 1

    logger.info(
        "send_referral_bonus_reminders_for_active_deal: deal_id=%s number=%s sent=%s",
        deal.id,
        deal.number,
        sent,
    )
    return sent

async def close_active_deal_by_schedule(db: AsyncSession, *, force: bool = False) -> bool:
    """
    Закрыть текущую активную сделку (если есть) и разослать уведомления.
    Используется планировщиком (12:00 Europe/Chisinau).
    Идемпотентно: если активной сделки нет — False.
    Если force=False, закрывает только сделку, у которой end_at <= now.
    Если force=True, закрывает активную сделку досрочно (для админки).
    Транзакция управляется вызывающим кодом (scheduler); не вызывать db.begin() здесь.
    """
    now = dt.datetime.now(dt.timezone.utc)
    filters = [Deal.status == DEAL_STATUS_ACTIVE]
    if not force:
        filters.append(Deal.end_at <= now)

    deal_result = await db.execute(
        select(Deal)
        .where(*filters)
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
    Открыть новую сделку по расписанию (13:00 Europe/Chisinau) и разослать уведомление.
    Перед открытием обрабатываются все отложенные выплаты (in_progress_payout).
    Защита от дублей: если уже есть active сделка, перекрывающая now — не создаём новую.
    """
    now = dt.datetime.now(dt.timezone.utc)

    # Сначала обрабатываем отложенные выплаты предыдущих сделок.
    # Ошибка в payouts не должна блокировать открытие новой сделки.
    try:
        paid = await process_pending_payouts(db)
        if paid:
            logger.info("open_new_deal_by_schedule: processed %s pending payouts before opening", paid)
    except Exception:
        logger.exception("open_new_deal_by_schedule: process_pending_payouts failed, continuing with deal open")

    active = await get_active_deal(db)
    if active:
        return None

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
        profit_percent=profit_percent if profit_percent is not None else Decimal("3"),
    )
    db.add(deal)
    await db.flush()
    return deal
