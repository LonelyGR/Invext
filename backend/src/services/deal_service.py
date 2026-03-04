from __future__ import annotations

import datetime as dt
import logging
from decimal import Decimal
from typing import Iterable, Optional

import httpx
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
import pytz
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.models import Deal, DealInvestment, LedgerTransaction, User
from src.services.ledger_service import (
    LEDGER_TYPE_DEPOSIT,
    LEDGER_TYPE_INVEST,
    LEDGER_TYPE_PROFIT,
    get_balance_usdt,
)


TZ_UTC1 = pytz.FixedOffset(60)  # UTC+1
logger = logging.getLogger(__name__)


async def get_active_deal(db: AsyncSession) -> Optional[Deal]:
    result = await db.execute(
        select(Deal)
        .where(Deal.status == "open")
        .order_by(Deal.opened_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def open_new_deal(db: AsyncSession, percent: Decimal = Decimal("3.0")) -> Deal:
    """Создать новую сделку со статусом open."""
    result = await db.execute(select(func.coalesce(func.max(Deal.number), 0)))
    last_number = result.scalar() or 0
    deal = Deal(
        number=int(last_number) + 1,
        percent=percent,
        status="open",
    )
    db.add(deal)
    await db.flush()
    return deal


async def close_current_open_deal(db: AsyncSession) -> Optional[Deal]:
    """Закрыть текущую открытую сделку (status: open -> closed)."""
    result = await db.execute(
        select(Deal)
        .where(Deal.status == "open")
        .order_by(Deal.opened_at.desc())
        .limit(1)
        .with_for_update()
    )
    deal = result.scalar_one_or_none()
    if not deal:
        return None
    if deal.status != "open":
        return deal
    now = dt.datetime.now(dt.timezone.utc)
    deal.status = "closed"
    deal.closed_at = now
    await db.flush()
    return deal


async def invest_into_active_deal(
    db: AsyncSession,
    user: User,
    amount: Decimal,
) -> DealInvestment:
    """Создать инвестицию пользователя в текущую открытую сделку."""
    async with db.begin():
        # Лочим активную сделку.
        result = await db.execute(
            select(Deal)
            .where(Deal.status == "open")
            .order_by(Deal.opened_at.desc())
            .limit(1)
            .with_for_update()
        )
        deal = result.scalar_one_or_none()
        if not deal:
            raise ValueError("Нет активной сделки для инвестирования")

        # Проверяем баланс по ledger.
        current_balance = await get_balance_usdt(db, user.id)
        if current_balance < amount:
            raise ValueError("Недостаточно средств для инвестирования")

        # Списываем через ledger.
        tx = LedgerTransaction(
            user_id=user.id,
            type=LEDGER_TYPE_INVEST,
            amount_usdt=amount,
        )
        db.add(tx)

        inv = DealInvestment(
            deal_id=deal.id,
            user_id=user.id,
            amount=amount,
            status="active",
        )
        db.add(inv)

        # Обновляем кэш баланса.
        new_balance = current_balance - amount
        user.balance_usdt = new_balance

        await db.flush()

    return inv


async def accrue_profits_for_due_deals(db: AsyncSession) -> None:
    """
    Начислить прибыль по всем сделкам, для которых прошло >=24 часа после закрытия,
    но ещё не проставлен статус finished.
    """
    now = dt.datetime.now(dt.timezone.utc)
    day_ago = now - dt.timedelta(hours=24)

    # Выбираем сделки, которые закрыты, но ещё не завершены и уже "созрели".
    deals_result = await db.execute(
        select(Deal)
        .where(
            Deal.status == "closed",
            Deal.closed_at <= day_ago,
            Deal.finished_at.is_(None),
        )
    )
    deals: Iterable[Deal] = deals_result.scalars().all()

    for deal in deals:
        async with db.begin():
            # Лочим сделку.
            d_result = await db.execute(
                select(Deal).where(Deal.id == deal.id).with_for_update()
            )
            d = d_result.scalar_one_or_none()
            if not d or d.status != "closed":
                continue

            inv_result = await db.execute(
                select(DealInvestment)
                .where(
                    DealInvestment.deal_id == d.id,
                    DealInvestment.status == "active",
                )
                .with_for_update()
            )
            investments: Iterable[DealInvestment] = inv_result.scalars().all()

            for inv in investments:
                user = await db.get(User, inv.user_id, with_for_update=True)
                if not user:
                    continue

                profit = (inv.amount * (d.percent / Decimal("100"))).quantize(
                    Decimal("0.01")
                )

                # Возвращаем тело инвестиции.
                tx_body = LedgerTransaction(
                    user_id=inv.user_id,
                    type=LEDGER_TYPE_DEPOSIT,
                    amount_usdt=inv.amount,
                )
                db.add(tx_body)

                # Начисляем прибыль.
                tx_profit = LedgerTransaction(
                    user_id=inv.user_id,
                    type=LEDGER_TYPE_PROFIT,
                    amount_usdt=profit,
                )
                db.add(tx_profit)

                inv.profit_amount = profit
                inv.status = "paid"

                # Обновляем кэш баланса пользователя.
                new_balance = await get_balance_usdt(db, inv.user_id)
                user.balance_usdt = new_balance

            d.status = "finished"
            d.finished_at = now


async def _broadcast_new_deal_to_all_users(db: AsyncSession, deal: Deal) -> None:
    """
    Отправить сообщение о новой сделке всем пользователям в Telegram.
    Выполняется внутри джоба планировщика после создания сделки.
    """
    settings = get_settings()
    bot_token = settings.bot_token
    if not bot_token:
        logger.warning("BOT_TOKEN not configured, skip new deal broadcast")
        return

    result = await db.execute(select(User.telegram_id).where(User.telegram_id.is_not(None)))
    telegram_ids = [row[0] for row in result.fetchall() if row[0]]

    if not telegram_ids:
        logger.info("No users to notify about new deal")
        return

    text = (
        f"Открыта новая сделка #{deal.number} на {deal.percent}%.\n\n"
        "Вы можете инвестировать USDT в разделе «💰 Инвестировать» бота."
    )

    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    async with httpx.AsyncClient(timeout=10.0) as client:
        for tid in telegram_ids:
            try:
                await client.post(api_url, json={"chat_id": tid, "text": text})
            except Exception as e:  # noqa: BLE001
                logger.warning("Failed to send new deal message to %s: %s", tid, e)


def init_deal_scheduler(scheduler: AsyncIOScheduler, db_factory) -> None:
    """
    Настроить APScheduler:
    - 12:00 (UTC+1) — закрыть открытую сделку.
    - 13:00 (UTC+1) — открыть новую сделку.
    - каждые 5 минут — проверять сделки для начисления прибыли.

    db_factory — асинхронная фабрика получения AsyncSession (обычно sessionmaker).
    """

    async def _job_close_deal():
        async with db_factory() as db:  # type: ignore[attr-defined]
            async with db.begin():
                await close_current_open_deal(db)

    async def _job_open_deal():
        async with db_factory() as db:  # type: ignore[attr-defined]
            # Создаём сделку в транзакции, затем рассылаем уведомления.
            async with db.begin():
                deal = await open_new_deal(db)
            await _broadcast_new_deal_to_all_users(db, deal)

    async def _job_accrue():
        async with db_factory() as db:  # type: ignore[attr-defined]
            async with db.begin():
                await accrue_profits_for_due_deals(db)

    scheduler.add_job(
        _job_close_deal,
        CronTrigger(hour=12, minute=0, timezone=TZ_UTC1),
        name="close_current_deal",
    )
    scheduler.add_job(
        _job_open_deal,
        CronTrigger(hour=13, minute=0, timezone=TZ_UTC1),
        name="open_new_deal",
    )
    scheduler.add_job(
        _job_accrue,
        IntervalTrigger(minutes=5),
        name="accrue_profits_for_due_deals",
    )

