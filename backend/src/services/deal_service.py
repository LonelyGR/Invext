"""
Сделки: активная сделка по окну (start_at — end_at), участие через deal_participations,
закрытие, реферальные начисления, уведомления.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
from decimal import Decimal
from typing import List, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Deal, DealParticipation, LedgerTransaction, ReferralReward, User
from src.models.deal import DEAL_STATUS_ACTIVE, DEAL_STATUS_CLOSED
from src.models.deal_participation import (
    PARTICIPATION_STATUS_ACTIVE,
    PARTICIPATION_STATUS_COMPLETED,
    PARTICIPATION_STATUS_IN_PROGRESS,
)
from src.models.referral_reward import STATUS_PAID, STATUS_MISSED, STATUS_PENDING
from src.services.ledger_service import (
    LEDGER_TYPE_INVEST,
    LEDGER_TYPE_INVEST_RETURN,
    LEDGER_TYPE_PROFIT,
    LEDGER_TYPE_REFERRAL_BONUS,
    get_balance_usdt,
    sync_user_balance,
)
from src.services.referral_service import (
    apply_referral_rewards_for_investment,
    get_potential_referral_bonuses_for_deal,
)
from src.services.settings_service import get_system_settings
from src.services.notification_service import (
    broadcast_deal_closed,
    notify_payout_complete,
    send_referral_bonus_reminder,
)

logger = logging.getLogger(__name__)
PAYOUT_TZ = ZoneInfo("Europe/Chisinau")

# Сериализация открытия сделки между планировщиком и админ-эндпоинтами (несколько воркеров / гонка).
DEAL_OPEN_ADVISORY_LOCK_KEY = 582_944_001


async def acquire_deal_open_advisory_lock(db: AsyncSession) -> None:
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"),
        {"key": DEAL_OPEN_ADVISORY_LOCK_KEY},
    )
# Единый календарь сделок (окно сбора) — то же, что в планировщике и админке.
SCHEDULE_TZ = PAYOUT_TZ

# Python weekday: пн=0 … вс=6.
WEEKDAY_SATURDAY = 5
WEEKDAY_SUNDAY = 6


def _chisinau_local(utc_dt: dt.datetime) -> dt.datetime:
    if utc_dt.tzinfo is None:
        utc_dt = utc_dt.replace(tzinfo=dt.timezone.utc)
    return utc_dt.astimezone(SCHEDULE_TZ)


def _is_saturday_chisinau(utc_dt: Optional[dt.datetime] = None) -> bool:
    utc_dt = utc_dt or dt.datetime.now(dt.timezone.utc)
    return _chisinau_local(utc_dt).weekday() == WEEKDAY_SATURDAY


def _is_weekend_chisinau(utc_dt: Optional[dt.datetime] = None) -> bool:
    """Суббота или воскресенье по Europe/Chisinau — для запрета открытия нового сбора."""
    utc_dt = utc_dt or dt.datetime.now(dt.timezone.utc)
    wd = _chisinau_local(utc_dt).weekday()
    return wd in (WEEKDAY_SATURDAY, WEEKDAY_SUNDAY)


def _rule_for_weekday(schedule: dict[str, dict], weekday: int) -> dict:
    """Правило дня из JSON админки; если дня нет — выключенный запасной слот (без старого недельного шаблона)."""
    r = schedule.get(str(weekday))
    if isinstance(r, dict) and r:
        return r
    return {
        "enabled": False,
        "open": "13:00",
        "close_day": (weekday + 1) % 7,
        "close_time": "12:00",
        "payout_day": (weekday + 2) % 7,
        "payout_time": "15:00",
    }


def _parse_hhmm(value: str, default_hour: int, default_minute: int) -> tuple[int, int]:
    raw = str(value or "").strip()
    try:
        hh, mm = raw.split(":", 1)
        hour = max(0, min(23, int(hh)))
        minute = max(0, min(59, int(mm)))
        return hour, minute
    except Exception:
        return default_hour, default_minute


def _normalized_schedule(raw: object | None) -> dict[str, dict]:
    """
    Расписание только из deal_schedule_json (админка). Без подмешивания отдельного недельного дефолта.
    Пустой JSON → {} (все дни обрабатываются через _rule_for_weekday как выключенные при отсутствии ключа).
    """
    payload: object | None = raw
    if isinstance(raw, str):
        txt = raw.strip()
        if not txt:
            return {}
        try:
            payload = json.loads(txt)
        except Exception:
            return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, dict] = {}
    for day in range(7):
        key = str(day)
        candidate = payload.get(key)
        if not isinstance(candidate, dict):
            continue
        out[key] = {
            "enabled": bool(candidate.get("enabled", False)),
            "open": str(candidate.get("open") or "13:00"),
            "close_day": int(candidate.get("close_day", (day + 1) % 7)),
            "close_time": str(candidate.get("close_time") or "12:00"),
            "payout_day": int(candidate.get("payout_day", (day + 2) % 7)),
            "payout_time": str(candidate.get("payout_time") or "15:00"),
        }
    return out


def _next_weekday_time_after(start_local: dt.datetime, target_weekday: int, hhmm: str) -> dt.datetime:
    h, m = _parse_hhmm(hhmm, 0, 0)
    days_delta = (int(target_weekday) - start_local.weekday()) % 7
    candidate = (start_local + dt.timedelta(days=days_delta)).replace(
        hour=h, minute=m, second=0, microsecond=0
    )
    if candidate <= start_local:
        candidate = candidate + dt.timedelta(days=7)
    return candidate


def collection_end_local_for_start(start_local: dt.datetime, schedule_raw: object | None = None) -> dt.datetime:
    """
    Момент закрытия сбора по локальному времени начала (Europe/Chisinau) — поля `close_day` / `close_time`
    из `deal_schedule_json` админки (день недели 0=Пн … 6=Вс).
    """
    if start_local.tzinfo is None:
        start_local = start_local.replace(tzinfo=SCHEDULE_TZ)
    else:
        start_local = start_local.astimezone(SCHEDULE_TZ)
    schedule = _normalized_schedule(schedule_raw)
    rule = _rule_for_weekday(schedule, start_local.weekday())
    close_day = int(rule.get("close_day", (start_local.weekday() + 1) % 7))
    close_time = str(rule.get("close_time", "12:00"))
    return _next_weekday_time_after(start_local, close_day, close_time)


def scheduled_collection_window_1300_chisinau(
    now_utc: dt.datetime,
    schedule_raw: object | None = None,
) -> Optional[tuple[dt.datetime, dt.datetime]]:
    """
    Окно автоматического открытия сбора: только если для сегодняшнего дня в админ-расписании `enabled`,
    и локальное время совпадает с полем `open` (по умолчанию 13:00). Конец окна — по `close_*` из JSON.
    В субботу и воскресенье (Europe/Chisinau) не открываем, даже если день включён в JSON.
    Возвращает (start_at UTC, end_at UTC).
    """
    now_local = now_utc.astimezone(SCHEDULE_TZ)
    if now_local.weekday() in (WEEKDAY_SATURDAY, WEEKDAY_SUNDAY):
        return None
    schedule = _normalized_schedule(schedule_raw)
    today_rule = schedule.get(str(now_local.weekday()))
    if not today_rule or not bool(today_rule.get("enabled", True)):
        return None
    open_h, open_m = _parse_hhmm(str(today_rule.get("open", "13:00")), 13, 0)
    if now_local.hour != open_h or now_local.minute != open_m:
        return None
    start_local = now_local.replace(hour=open_h, minute=open_m, second=0, microsecond=0)
    end_local = collection_end_local_for_start(start_local, schedule_raw=schedule_raw)
    return (
        start_local.astimezone(dt.timezone.utc),
        end_local.astimezone(dt.timezone.utc),
    )


def next_scheduled_open_1300_chisinau(
    after_utc: Optional[dt.datetime] = None,
    schedule_raw: object | None = None,
) -> dt.datetime:
    """
    Следующее фиксированное открытие сбора: 13:00 Europe/Chisinau в рабочий день.
    Расчёт идёт по календарному слоту, а не от фактического момента прошлой сделки.
    """
    base_utc = after_utc or dt.datetime.now(dt.timezone.utc)
    if base_utc.tzinfo is None:
        base_utc = base_utc.replace(tzinfo=dt.timezone.utc)
    else:
        base_utc = base_utc.astimezone(dt.timezone.utc)

    local_now = base_utc.astimezone(SCHEDULE_TZ)
    schedule = _normalized_schedule(schedule_raw)
    for delta_days in range(0, 14):
        day_dt = local_now + dt.timedelta(days=delta_days)
        if day_dt.weekday() in (WEEKDAY_SATURDAY, WEEKDAY_SUNDAY):
            continue
        rule = schedule.get(str(day_dt.weekday()))
        if not rule or not bool(rule.get("enabled", True)):
            continue
        h, m = _parse_hhmm(str(rule.get("open", "13:00")), 13, 0)
        candidate = day_dt.replace(hour=h, minute=m, second=0, microsecond=0)
        if candidate > local_now:
            return candidate.astimezone(dt.timezone.utc)
    # Fallback на прежнее время если все дни выключены/битые
    return local_now.replace(hour=13, minute=0, second=0, microsecond=0).astimezone(dt.timezone.utc)


def calculate_payout_at(invest_datetime_utc: Optional[dt.datetime] = None, schedule_raw: object | None = None) -> dt.datetime:
    """
    Ближайший момент выплаты по `payout_day` / `payout_time` из `deal_schedule_json` (админка)
    относительно локального времени инвестиции (Europe/Chisinau). Возвращает UTC.
    """
    invest_datetime_utc = invest_datetime_utc or dt.datetime.now(dt.timezone.utc)
    if invest_datetime_utc.tzinfo is None:
        invest_datetime_utc = invest_datetime_utc.replace(tzinfo=dt.timezone.utc)

    local_dt = invest_datetime_utc.astimezone(PAYOUT_TZ)
    schedule = _normalized_schedule(schedule_raw)
    rule = _rule_for_weekday(schedule, local_dt.weekday())
    payout_day = int(rule.get("payout_day", (local_dt.weekday() + 2) % 7))
    payout_time = str(rule.get("payout_time", "15:00"))
    payout_local = _next_weekday_time_after(local_dt, payout_day, payout_time)
    return payout_local.astimezone(dt.timezone.utc)


def calculate_payout_at_for_deal_start(start_at_utc: Optional[dt.datetime], schedule_raw: object | None = None) -> dt.datetime:
    base_utc = start_at_utc or dt.datetime.now(dt.timezone.utc)
    if base_utc.tzinfo is None:
        base_utc = base_utc.replace(tzinfo=dt.timezone.utc)
    local_start = base_utc.astimezone(PAYOUT_TZ)
    schedule = _normalized_schedule(schedule_raw)
    rule = _rule_for_weekday(schedule, local_start.weekday())
    payout_day = int(rule.get("payout_day", (local_start.weekday() + 2) % 7))
    payout_time = str(rule.get("payout_time", "15:00"))
    payout_local = _next_weekday_time_after(local_start, payout_day, payout_time)
    return payout_local.astimezone(dt.timezone.utc)


def calculate_payout_at_for_investment(now_utc: Optional[dt.datetime] = None, schedule_raw: object | None = None) -> dt.datetime:
    # Совместимость с существующими вызовами.
    return calculate_payout_at(now_utc, schedule_raw=schedule_raw)


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
    deal = result.scalar_one_or_none()
    return deal


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

    now = dt.datetime.now(dt.timezone.utc)

    deal_result = await db.execute(
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

    if deal.min_participation_usdt is not None and amount < deal.min_participation_usdt:
        raise ValueError(f"Минимальная сумма участия в этой сделке — {deal.min_participation_usdt} USDT")
    if deal.max_participation_usdt is not None and amount > deal.max_participation_usdt:
        raise ValueError(f"Максимальная сумма участия в этой сделке — {deal.max_participation_usdt} USDT")
    if deal.max_participants is not None:
        cnt_result = await db.execute(
            select(func.count(DealParticipation.id)).where(DealParticipation.deal_id == deal.id)
        )
        current_cnt = int(cnt_result.scalar() or 0)
        if current_cnt >= int(deal.max_participants):
            raise ValueError("Лимит участников этой сделки уже достигнут")

    current_balance = await get_balance_usdt(db, user_locked.id)
    if current_balance < amount:
        raise ValueError("Недостаточно средств для участия")

    settings = await get_system_settings(db)
    schedule_raw = getattr(settings, "deal_schedule_json", None)

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
        payout_at=calculate_payout_at_for_deal_start(deal.start_at, schedule_raw=schedule_raw),
    )
    db.add(participation)
    await db.flush()

    # Реферальные бонусы с инвестиций начисляются при успешном входе в сделку:
    # 1% от суммы участия только прямому рефереру.
    await apply_referral_rewards_for_investment(
        db,
        investor=user_locked,
        deal=deal,
        deal_amount_usdt=amount,
    )
    await db.flush()

    await sync_user_balance(db, user_locked.id)

    logger.info(
        "Deal participation created: deal_id=%s user_id=%s amount=%s",
        deal.id, user_locked.id, amount,
    )
    return participation


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
        settings = await get_system_settings(db)
        next_open_at = next_scheduled_open_1300_chisinau(
            now,
            schedule_raw=getattr(settings, "deal_schedule_json", None),
        )
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
    — статус → completed; payout_at участия не меняем (зафиксирован при входе в сделку)
    — отправляем персональное уведомление каждому пользователю.
    Вызывается перед открытием новой сделки.
    Возвращает кол-во обработанных записей.
    """
    # Выплата по сохранённому payout_at участия (фиксируется при входе в сделку), не пересчитываем из JSON.
    now = dt.datetime.now(dt.timezone.utc)

    # Важно для идемпотентности при нескольких воркерах:
    # лочим строки и пропускаем уже залоченные (чтобы не выплатить дважды).
    parts_result = await db.execute(
        select(DealParticipation)
        .join(Deal, DealParticipation.deal_id == Deal.id)
        .where(
            DealParticipation.status == PARTICIPATION_STATUS_IN_PROGRESS,
            Deal.closed_at.isnot(None),
            DealParticipation.payout_at.isnot(None),
            DealParticipation.payout_at <= now,
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
    notify_payload_by_participation_id: dict[int, dict] = {}

    for p in participations:
        try:
            if p.deal_id not in deal_cache:
                deal_obj = await db.get(Deal, p.deal_id)
                if deal_obj:
                    deal_cache[p.deal_id] = deal_obj
            deal = deal_cache.get(p.deal_id)

            profit = p.profit_amount or Decimal("0")

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

            referral_income = Decimal("0")
            rewards_result = await db.execute(
                select(ReferralReward).where(
                    ReferralReward.deal_id == p.deal_id,
                    ReferralReward.to_user_id == p.user_id,
                    ReferralReward.status == STATUS_PENDING,
                )
            )
            pending_rewards = list(rewards_result.scalars().all())
            if pending_rewards:
                referral_income = sum((rw.amount or Decimal("0") for rw in pending_rewards), Decimal("0"))
                if referral_income > 0:
                    tx_ref = LedgerTransaction(
                        user_id=p.user_id,
                        type=LEDGER_TYPE_REFERRAL_BONUS,
                        amount_usdt=referral_income,
                        metadata_json={
                            **meta_base,
                            "source": "investment_payout",
                            "pending_rewards_count": len(pending_rewards),
                            "referral_reward_ids": [rw.id for rw in pending_rewards],
                        },
                    )
                    db.add(tx_ref)
                for rw in pending_rewards:
                    rw.status = STATUS_PAID

            p.status = PARTICIPATION_STATUS_COMPLETED
            # payout_at оставляем как зафиксированный момент выплаты (не перезаписываем из deal_schedule_json)
            affected_user_ids.add(p.user_id)
            processed += 1

            total = (p.amount + profit + referral_income).quantize(Decimal("0.000001"))
            profit_percent = deal.profit_percent if deal and deal.profit_percent is not None else None
            # Отложим отправку до момента, когда соберем user_tids после flush.
            notify_payload_by_participation_id[p.id] = {
                "deal_num": deal.number if deal else 0,
                "profit": profit,
                "total": total,
                "profit_percent": profit_percent,
                "referral_income": referral_income,
            }
        except Exception:
            logger.exception("process_pending_payouts: failed to process participation %s", p.id)

    await db.flush()

    for uid in affected_user_ids:
        await sync_user_balance(db, uid)

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
            payload = notify_payload_by_participation_id.get(p.id, {})
            await notify_payout_complete(
                telegram_id=tid,
                deal_number=payload.get("deal_num", 0),
                amount=p.amount,
                profit=payload.get("profit", p.profit_amount or Decimal("0")),
                total=payload.get("total", p.amount + (p.profit_amount or Decimal("0"))),
                profit_percent=payload.get("profit_percent"),
                referral_income=payload.get("referral_income", Decimal("0")),
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
    Закрытие выполняется в любой день недели (в т.ч. выходные), если end_at уже наступил.
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

    Отправка только один раз на сделку и только в окне ~55–65 минут до end_at,
    чтобы текст совпадал с реальным временем до закрытия (не «через час» при закрытии в понедельник).
    В субботу (Europe/Chisinau) не шлём.
    """
    now = dt.datetime.now(dt.timezone.utc)
    if _is_saturday_chisinau(now):
        return 0

    locked = await db.execute(
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
    deal = locked.scalar_one_or_none()
    if not deal or not deal.end_at:
        return 0

    if deal.referral_preclose_reminder_sent:
        return 0

    secs_left = (deal.end_at - now).total_seconds()
    # Окно ~1 час до закрытия (планировщик тикает каждые 5 мин).
    if not (3300 <= secs_left <= 3900):
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

    deal.referral_preclose_reminder_sent = True
    await db.flush()

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
    Открыть новую сделку по расписанию (13:00 Europe/Chisinau).
    Перед открытием обрабатываются все отложенные выплаты (in_progress_payout).
    Защита от дублей: если уже есть active сделка, перекрывающая now — не создаём новую.
    Важно: отправка уведомлений вынесена во внешний слой после успешного commit.
    """
    await acquire_deal_open_advisory_lock(db)

    if _is_weekend_chisinau(start_at):
        logger.info("open_new_deal_by_schedule: skipped — start falls on weekend (Chisinau)")
        return None

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
