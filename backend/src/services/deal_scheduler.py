"""
Планировщик: периодическая проверка сделок с истёкшим end_at и закрытие их.
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.services.deal_service import process_due_deals

logger = logging.getLogger(__name__)


def init_deal_scheduler(scheduler: AsyncIOScheduler, db_factory) -> None:
    """
    Раз в минуту проверять сделки с end_at <= now и выполнять закрытие
    (статус closed, реферальные начисления, уведомления).
    """

    async def _job_process_due_deals():
        async with db_factory() as db:
            try:
                count = await process_due_deals(db)
                await db.commit()
                if count:
                    logger.info("Processed %s due deal(s)", count)
            except Exception as e:
                await db.rollback()
                logger.exception("Error processing due deals: %s", e)

    scheduler.add_job(
        _job_process_due_deals,
        IntervalTrigger(minutes=1),
        name="process_due_deals",
    )
