"""
Планировщик: периодическая проверка сделок с истёкшим end_at и закрытие их.
"""
from __future__ import annotations

import datetime as dt
import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from src.services.deal_service import (
    close_active_deal_by_schedule,
    open_new_deal_by_schedule,
    process_due_deals,
    process_pending_payouts,
    scheduled_collection_window_1300_chisinau,
    send_referral_bonus_reminders_for_active_deal,
)

logger = logging.getLogger(__name__)

# Весь календарь сделок завязан на времени Кишинёва.
SCHEDULE_TZ = ZoneInfo("Europe/Chisinau")


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

    async def _job_close_deal_1200():
        logger.info("close_deal_1200 job started")
        async with db_factory() as db:
            logger.debug("close_deal_1200: session created")
            try:
                closed = await close_active_deal_by_schedule(db)
                await db.commit()
                logger.info("close_deal_1200 job finished, closed=%s", closed)
            except Exception as e:
                await db.rollback()
                logger.exception("close_deal_1200 job failed: %s", e)

    async def _job_referral_reminder_1100():
        logger.info("referral_reminder_1100 job started")
        async with db_factory() as db:
            logger.debug("referral_reminder_1100: session created")
            try:
                sent = await send_referral_bonus_reminders_for_active_deal(db)
                await db.commit()
                logger.info("referral_reminder_1100 job finished, sent=%s", sent)
            except Exception as e:
                await db.rollback()
                logger.exception("referral_reminder_1100 job failed: %s", e)

    async def _job_open_deal_1300():
        logger.info("open_deal_1300 job started")
        # Окно сбора — единая функция в deal_service (пятница → понедельник 12:00;
        # суббота/воскресенье: новые сделки по cron не открываем).
        now_utc = dt.datetime.now(dt.timezone.utc)
        window = scheduled_collection_window_1300_chisinau(now_utc)
        if window is None:
            logger.info("open_deal_1300: skipped (weekend — no scheduled collection open)")
            return
        start_at, end_at = window

        async with db_factory() as db:
            logger.debug("open_deal_1300: session created")
            try:
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

    # Ежедневные задачи по времени Кишинёва:
    scheduler.add_job(
        _job_referral_reminder_1100,
        CronTrigger(hour=11, minute=0, timezone=SCHEDULE_TZ),
        name="referral_reminder_1100_chisinau",
    )
    scheduler.add_job(
        _job_close_deal_1200,
        CronTrigger(hour=12, minute=0, timezone=SCHEDULE_TZ),
        name="close_deal_1200_chisinau",
    )
    scheduler.add_job(
        _job_open_deal_1300,
        CronTrigger(hour=13, minute=0, timezone=SCHEDULE_TZ),
        name="open_deal_1300_chisinau",
    )
