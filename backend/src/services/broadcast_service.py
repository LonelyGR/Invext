from __future__ import annotations

import asyncio
import datetime as dt
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User, LedgerTransaction, PaymentInvoice, DealParticipation, DealInvestment
from src.models.broadcast_delivery import (
    BroadcastDelivery,
    DELIVERY_STATUS_FAILED,
    DELIVERY_STATUS_PENDING,
    DELIVERY_STATUS_SENT,
)
from src.models.broadcast_message import (
    BROADCAST_STATUS_ERROR,
    BROADCAST_STATUS_IN_PROGRESS,
    BROADCAST_STATUS_SENT,
    BroadcastMessage,
)
from src.services.notification_service import send_telegram_message, send_telegram_photo

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
BATCH_SIZE = 40


async def enqueue_broadcast(
    db: AsyncSession,
    *,
    text_html: str,
    image_path: str | None,
    scheduled_at: dt.datetime | None = None,
    audience_segment: str = "all",
) -> BroadcastMessage:
    now = dt.datetime.now(dt.timezone.utc)
    start_at = scheduled_at or now
    broadcast = BroadcastMessage(
        text_html=text_html,
        image_path=image_path,
        status=BROADCAST_STATUS_IN_PROGRESS,
        audience_segment=audience_segment,
        scheduled_at=scheduled_at,
        started_at=None if scheduled_at else now,
    )
    db.add(broadcast)
    await db.flush()

    base_query = select(User.id, User.telegram_id).where(User.telegram_id.isnot(None))
    seg = (audience_segment or "all").strip().lower()
    if seg == "with_balance":
        base_query = base_query.where(User.balance_usdt > 0)
    elif seg == "with_referrals":
        base_query = base_query.where(
            User.id.in_(select(User.referrer_id).where(User.referrer_id.is_not(None)))
        )
    elif seg == "active_24h":
        since = now - dt.timedelta(hours=24)
        active_users = (
            select(LedgerTransaction.user_id.label("uid")).where(LedgerTransaction.created_at >= since)
            .union(select(PaymentInvoice.user_id.label("uid")).where(PaymentInvoice.created_at >= since))
            .union(select(DealParticipation.user_id.label("uid")).where(DealParticipation.created_at >= since))
            .union(select(DealInvestment.user_id.label("uid")).where(DealInvestment.created_at >= since))
            .subquery()
        )
        base_query = base_query.where(User.id.in_(select(active_users.c.uid)))
    users_result = await db.execute(base_query)
    rows = users_result.all()

    for user_id, telegram_id in rows:
        db.add(
            BroadcastDelivery(
                broadcast_id=broadcast.id,
                user_id=user_id,
                telegram_id=telegram_id,
                status=DELIVERY_STATUS_PENDING,
                next_attempt_at=start_at,
            )
        )
    broadcast.total_recipients = len(rows)
    await db.flush()
    return broadcast


async def process_pending_broadcasts(db: AsyncSession) -> int:
    now = dt.datetime.now(dt.timezone.utc)
    result = await db.execute(
        select(BroadcastDelivery, BroadcastMessage)
        .join(BroadcastMessage, BroadcastDelivery.broadcast_id == BroadcastMessage.id)
        .where(
            BroadcastMessage.status == BROADCAST_STATUS_IN_PROGRESS,
            BroadcastDelivery.status == DELIVERY_STATUS_PENDING,
            BroadcastDelivery.next_attempt_at <= now,
        )
        .order_by(BroadcastDelivery.id.asc())
        .limit(BATCH_SIZE)
    )
    rows = result.all()
    if not rows:
        await _finalize_broadcasts(db)
        return 0

    processed = 0
    for delivery, broadcast in rows:
        ok = False
        err_msg = None
        try:
            if broadcast.image_path:
                ok = await send_telegram_photo(
                    chat_id=delivery.telegram_id,
                    photo_path=broadcast.image_path,
                    caption=broadcast.text_html,
                    parse_mode="HTML",
                )
            else:
                ok = await send_telegram_message(
                    chat_id=delivery.telegram_id,
                    text=broadcast.text_html,
                    parse_mode="HTML",
                )
        except Exception as e:
            ok = False
            err_msg = str(e)

        if ok:
            if broadcast.started_at is None:
                broadcast.started_at = now
            delivery.status = DELIVERY_STATUS_SENT
            delivery.sent_at = now
            delivery.last_error = None
        else:
            delivery.attempts += 1
            delivery.last_error = (err_msg or "send failed")[:1000]
            if delivery.attempts >= MAX_ATTEMPTS:
                delivery.status = DELIVERY_STATUS_FAILED
            else:
                # Небольшой backoff: 15s, 30s, 45s...
                delivery.next_attempt_at = now + dt.timedelta(seconds=15 * delivery.attempts)
        processed += 1
        await asyncio.sleep(0.04)

    await db.flush()
    await _refresh_broadcast_counters(db)
    await _finalize_broadcasts(db)
    return processed


async def retry_failed_deliveries(db: AsyncSession, broadcast_id: int) -> int:
    """Повторно поставить FAILED-доставки в очередь отправки."""
    now = dt.datetime.now(dt.timezone.utc)
    result = await db.execute(
        select(BroadcastDelivery).where(
            BroadcastDelivery.broadcast_id == broadcast_id,
            BroadcastDelivery.status == DELIVERY_STATUS_FAILED,
        )
    )
    rows = list(result.scalars().all())
    if not rows:
        return 0

    for d in rows:
        d.status = DELIVERY_STATUS_PENDING
        d.attempts = 0
        d.last_error = None
        d.next_attempt_at = now
        d.sent_at = None

    b = await db.get(BroadcastMessage, broadcast_id)
    if b:
        b.status = BROADCAST_STATUS_IN_PROGRESS
        b.started_at = now
        b.finished_at = None
        # sent_count оставляем как есть, чтобы история была правдивой.
        b.failed_count = 0

    await db.flush()
    return len(rows)


async def _refresh_broadcast_counters(db: AsyncSession) -> None:
    active_result = await db.execute(
        select(BroadcastMessage.id).where(BroadcastMessage.status == BROADCAST_STATUS_IN_PROGRESS)
    )
    for (broadcast_id,) in active_result.all():
        sent = await db.execute(
            select(func.count(BroadcastDelivery.id)).where(
                BroadcastDelivery.broadcast_id == broadcast_id,
                BroadcastDelivery.status == DELIVERY_STATUS_SENT,
            )
        )
        failed = await db.execute(
            select(func.count(BroadcastDelivery.id)).where(
                BroadcastDelivery.broadcast_id == broadcast_id,
                BroadcastDelivery.status == DELIVERY_STATUS_FAILED,
            )
        )
        b = await db.get(BroadcastMessage, broadcast_id)
        if b:
            b.sent_count = int(sent.scalar() or 0)
            b.failed_count = int(failed.scalar() or 0)


async def _finalize_broadcasts(db: AsyncSession) -> None:
    now = dt.datetime.now(dt.timezone.utc)
    active_result = await db.execute(
        select(BroadcastMessage.id).where(BroadcastMessage.status == BROADCAST_STATUS_IN_PROGRESS)
    )
    for (broadcast_id,) in active_result.all():
        pending = await db.execute(
            select(func.count(BroadcastDelivery.id)).where(
                BroadcastDelivery.broadcast_id == broadcast_id,
                BroadcastDelivery.status == DELIVERY_STATUS_PENDING,
            )
        )
        if int(pending.scalar() or 0) > 0:
            continue

        failed = await db.execute(
            select(func.count(BroadcastDelivery.id)).where(
                BroadcastDelivery.broadcast_id == broadcast_id,
                BroadcastDelivery.status == DELIVERY_STATUS_FAILED,
            )
        )
        sent = await db.execute(
            select(func.count(BroadcastDelivery.id)).where(
                BroadcastDelivery.broadcast_id == broadcast_id,
                BroadcastDelivery.status == DELIVERY_STATUS_SENT,
            )
        )
        b = await db.get(BroadcastMessage, broadcast_id)
        if not b:
            continue
        b.failed_count = int(failed.scalar() or 0)
        # Частичные ошибки (например, блокировка бота пользователем) не должны
        # помечать всю кампанию как ERROR, если рассылка реально доставлена другим.
        sent_count = int(sent.scalar() or 0)
        b.status = BROADCAST_STATUS_SENT if sent_count > 0 else BROADCAST_STATUS_ERROR
        b.finished_at = now
