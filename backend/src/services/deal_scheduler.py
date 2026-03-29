"""
Планировщик: периодическая проверка сделок с истёкшим end_at и закрытие их.
Открытие сбора — по минутному интервалу и расписанию из админки (deal_schedule_json).
Закрытие по календарю — через process_due_deals (end_at), без отдельного cron на 12:00.
"""
from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.services.deal_service import (
    open_new_deal_by_schedule,
    process_due_deals,
    process_pending_payouts,
    scheduled_collection_window_1300_chisinau,
    send_referral_bonus_reminders_for_active_deal,
)
from src.services.broadcast_service import process_pending_broadcasts
from src.services.settings_service import get_system_settings

logger = logging.getLogger(__name__)


def init_deal_scheduler(scheduler: AsyncIOScheduler, db_factory) -> None:
    """
    Раз в минуту проверять сделки с end_at <= now и выполнять закрытие
    (статус closed, реферальные начисления, уведомления).
    """

    async def _job_process_due_deals():
        logger.info("process_due_deals job started")
        async with db_factory() as db:
            logger.debug("process_due_deals: session created")
            try:
                count = await process_due_deals(db)
                await db.commit()
                logger.info("process_due_deals job finished, processed=%s", count)
            except Exception as e:
                await db.rollback()
                logger.exception("process_due_deals job failed: %s", e)

    async def _job_open_deal_1300():
        logger.info("open_deal_by_schedule job started")
        now_utc = dt.datetime.now(dt.timezone.utc)

        async with db_factory() as db:
            logger.debug("open_deal_1300: session created")
            try:
                settings = await get_system_settings(db)
                window = scheduled_collection_window_1300_chisinau(
                    now_utc,
                    schedule_raw=getattr(settings, "deal_schedule_json", None),
                )
                if window is None:
                    return
                start_at, end_at = window
                logger.debug("open_deal_1300: before open_new_deal_by_schedule")
                deal = await open_new_deal_by_schedule(db, start_at=start_at, end_at=end_at)
                if deal:
                    logger.info(
                        "open_deal_1300: deal opened id=%s number=%s, notifications sent",
                        deal.id,
                        deal.number,
                    )
                await db.commit()
                logger.info(
                    "open_deal_1300 job finished, created=%s",
                    bool(deal),
                )
            except Exception as e:
                await db.rollback()
                logger.exception("open_deal_1300 job failed: %s", e)

    async def _job_process_pending_payouts():
        """
        Страховочный джоб отложенных выплат:
        - нужен на случай, если контейнер/планировщик был недоступен в момент открытия новой сделки
        - выплата не раньше чем через 1 час после закрытия сделки (фильтр внутри process_pending_payouts)
        """
        logger.info("process_pending_payouts job started")
        async with db_factory() as db:
            try:
                count = await process_pending_payouts(db)
                await db.commit()
                logger.info("process_pending_payouts job finished, processed=%s", count)
            except Exception as e:
                await db.rollback()
                logger.exception("process_pending_payouts job failed: %s", e)

    async def _job_process_broadcasts():
        logger.info("process_broadcasts job started")
        async with db_factory() as db:
            try:
                count = await process_pending_broadcasts(db)
                await db.commit()
                logger.info("process_broadcasts job finished, processed=%s", count)
            except Exception as e:
                await db.rollback()
                logger.exception("process_broadcasts job failed: %s", e)

    async def _job_referral_preclose_reminder():
        """Реф. напоминание только в окне ~1 ч до end_at и не в субботу (логика внутри)."""
        async with db_factory() as db:
            try:
                n = await send_referral_bonus_reminders_for_active_deal(db)
                await db.commit()
                if n:
                    logger.info("referral_preclose_reminder job sent=%s", n)
            except Exception as e:
                await db.rollback()
                logger.exception("referral_preclose_reminder job failed: %s", e)

    scheduler.add_job(
        _job_process_due_deals,
        IntervalTrigger(minutes=1),
        name="process_due_deals",
    )
    # Страховка: регулярно обрабатывать отложенные выплаты.
    scheduler.add_job(
        _job_process_pending_payouts,
        IntervalTrigger(minutes=10),
        name="process_pending_payouts",
    )
    scheduler.add_job(
        _job_process_broadcasts,
        IntervalTrigger(seconds=20),
        name="process_broadcasts",
    )

    scheduler.add_job(
        _job_open_deal_1300,
        IntervalTrigger(minutes=1),
        name="open_deal_by_schedule",
    )
    scheduler.add_job(
        _job_referral_preclose_reminder,
        IntervalTrigger(minutes=5),
        name="referral_preclose_reminder",
    )
