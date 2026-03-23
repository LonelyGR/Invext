from __future__ import annotations

import asyncio
import datetime as dt
import logging
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import User
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
) -> BroadcastMessage:
    now = dt.datetime.now(dt.timezone.utc)
    broadcast = BroadcastMessage(
        text_html=text_html,
        image_path=image_path,
        status=BROADCAST_STATUS_IN_PROGRESS,
        started_at=now,
    )
    db.add(broadcast)
    await db.flush()

    users_result = await db.execute(select(User.id, User.telegram_id).where(User.telegram_id.isnot(None)))
    rows = users_result.all()

    for user_id, telegram_id in rows:
        db.add(
            BroadcastDelivery(
                broadcast_id=broadcast.id,
                user_id=user_id,
                telegram_id=telegram_id,
                status=DELIVERY_STATUS_PENDING,
                next_attempt_at=now,
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
        b = await db.get(BroadcastMessage, broadcast_id)
        if not b:
            continue
        b.failed_count = int(failed.scalar() or 0)
        b.status = BROADCAST_STATUS_ERROR if b.failed_count > 0 else BROADCAST_STATUS_SENT
        b.finished_at = now
