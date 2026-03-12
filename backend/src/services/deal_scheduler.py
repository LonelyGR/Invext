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
)

logger = logging.getLogger(__name__)

SCHEDULE_TZ = ZoneInfo("Etc/GMT-1")  # UTC+1 (важно: в зоне Etc/GMT-1 знак инвертирован)


def init_deal_scheduler(scheduler: AsyncIOScheduler, db_factory) -> None:
    """
    Раз в минуту проверять сделки с end_at <= now и выполнять закрытие
    (статус closed, реферальные начисления, уведомления).
    """

    async def _job_process_due_deals():
        logger.info("process_due_deals job started")
        async with db_factory() as db:
            try:
                count = await process_due_deals(db)
                await db.commit()
                logger.info("process_due_deals job finished, processed=%s", count)
            except Exception as e:
                await db.rollback()
                logger.exception("Error processing due deals: %s", e)

    async def _job_close_deal_1200():
        logger.info("close_deal_1200 job started")
        async with db_factory() as db:
            try:
                closed = await close_active_deal_by_schedule(db)
                await db.commit()
                logger.info("close_deal_1200 job finished, closed=%s", closed)
            except Exception as e:
                await db.rollback()
                logger.exception("Error in close_deal_1200: %s", e)

    async def _job_open_deal_1300():
        logger.info("open_deal_1300 job started")
        # Окно сделки: с 13:00 (UTC+1) до следующего дня 12:00 (UTC+1).
        now_utc = dt.datetime.now(dt.timezone.utc)
        now_local = now_utc.astimezone(SCHEDULE_TZ)
        start_local = now_local.replace(hour=13, minute=0, second=0, microsecond=0)
        close_local = (start_local + dt.timedelta(days=1)).replace(hour=12, minute=0, second=0, microsecond=0)
        start_at = start_local.astimezone(dt.timezone.utc)
        end_at = close_local.astimezone(dt.timezone.utc)

        async with db_factory() as db:
            try:
                deal = await open_new_deal_by_schedule(db, start_at=start_at, end_at=end_at)
                await db.commit()
                logger.info("open_deal_1300 job finished, created=%s", bool(deal))
            except Exception as e:
                await db.rollback()
                logger.exception("Error in open_deal_1300: %s", e)

    scheduler.add_job(
        _job_process_due_deals,
        IntervalTrigger(minutes=1),
        name="process_due_deals",
    )

    # Ежедневные задачи по расписанию (UTC+1):
    scheduler.add_job(
        _job_close_deal_1200,
        CronTrigger(hour=12, minute=0, timezone=SCHEDULE_TZ),
        name="close_deal_1200_utc_plus_1",
    )
    scheduler.add_job(
        _job_open_deal_1300,
        CronTrigger(hour=13, minute=0, timezone=SCHEDULE_TZ),
        name="open_deal_1300_utc_plus_1",
    )
