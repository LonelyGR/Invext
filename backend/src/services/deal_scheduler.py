"""
Планировщик: периодическая проверка сделок с истёкшим end_at и закрытие их.
Открытие сбора — по минутному интервалу и расписанию из админки (deal_schedule_json).
Закрытие и выплаты по payout_at — одна минутная задача (в :00 UTC): сначала закрытие сборов и коммит,
затем отложенные выплаты (отдельная транзакция). Ошибка закрытия не блокирует попытку выплат в ту же минуту.
"""
from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from sqlalchemy import select

from src.models import User
from src.services.deal_service import (
    open_new_deal_by_schedule,
    process_due_deals,
    process_pending_payouts,
    scheduled_collection_window_1300_chisinau,
    send_referral_bonus_reminders_for_active_deal,
)
from src.services.broadcast_service import process_pending_broadcasts
from src.services.notification_service import broadcast_deal_opened
from src.services.settings_service import get_system_settings

logger = logging.getLogger(__name__)


def init_deal_scheduler(scheduler: AsyncIOScheduler, db_factory) -> None:
    """
    Раз в минуту (в :00 UTC): закрыть сборы с истёкшим end_at, затем обработать выплаты с payout_at <= now.
    Два шага в разных сессиях: сбой закрытия не блокирует попытку выплат; сбой выплат не откатывает уже закрытые сделки.
    Дополнительно payouts вызываются перед открытием новой сделки (open_new_deal_by_schedule).
    """

    async def _job_deal_close_and_payouts():
        logger.info("deal_close_and_payouts job started")
        n_closed = 0
        n_paid = 0
        async with db_factory() as db:
            try:
                n_closed = await process_due_deals(db)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.exception("deal_close_and_payouts: process_due_deals failed: %s", e)
        async with db_factory() as db:
            try:
                n_paid = await process_pending_payouts(db)
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.exception("deal_close_and_payouts: process_pending_payouts failed: %s", e)
                return
        logger.info(
            "deal_close_and_payouts finished closed=%s payouts=%s",
            n_closed,
            n_paid,
        )

    async def _job_open_deal_1300():
        logger.info("open_deal_by_schedule job started")
        now_utc = dt.datetime.now(dt.timezone.utc)
        opened_deal = None

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
                opened_deal = deal
                if deal:
                    logger.info(
                        "open_deal_1300: deal opened id=%s number=%s",
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
                return

        if not opened_deal:
            return

        # Важно: уведомления отправляем только после успешного commit открытия сделки.
        try:
            async with db_factory() as db:
                users_result = await db.execute(
                    select(User.telegram_id).where(User.telegram_id.isnot(None))
                )
                telegram_ids = [r[0] for r in users_result.all() if r[0]]
            await broadcast_deal_opened(
                telegram_ids,
                opened_deal.number,
                close_at=opened_deal.end_at,
            )
            logger.info(
                "open_deal_1300: notifications sent deal_number=%s recipients=%s",
                opened_deal.number,
                len(telegram_ids),
            )
        except Exception as e:
            logger.exception(
                "open_deal_1300: notifications failed after commit deal_number=%s: %s",
                opened_deal.number,
                e,
            )

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
        _job_deal_close_and_payouts,
        CronTrigger(minute="*", second="0", timezone="UTC"),
        name="deal_close_and_payouts",
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
