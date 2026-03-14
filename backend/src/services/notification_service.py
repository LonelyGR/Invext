"""
Отправка уведомлений в Telegram. Бот расчётов не делает — только рассылка с бэкенда.
Время форматируется в UTC+1 в человекочитаемом виде. Для ключевых событий поддерживаются
Telegram message effects (только в личных чатах; с бэкенда отправка по chat_id = личный чат).
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import List, Optional

import httpx

from src.core.config import get_settings

logger = logging.getLogger(__name__)

# UTC+1 для отображения времени пользователям
DISPLAY_TZ = dt.timezone(dt.timedelta(hours=1))

# Telegram message effect IDs (работают только в личных чатах)
# https://core.telegram.org/api/effects
EFFECT_CELEBRATION = "5046509860389126442"  # 🎉
EFFECT_FIRE = "5104841245755180586"  # 🔥
EFFECT_MONEY = "5046589136895476101"  # 💰-like / подходящий для финансов

# Дни недели для русского формата
_WEEKDAYS_RU = (
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
)


def format_time_utc1(when: dt.datetime) -> str:
    """
    Форматировать время в UTC+1 в человекочитаемый вид.
    «сегодня в 13:00 (UTC+1)», «завтра в 12:00 (UTC+1)» или «понедельник, 13:00 (UTC+1)».
    """
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    local = when.astimezone(DISPLAY_TZ)
    today = dt.datetime.now(DISPLAY_TZ).date()
    date_part = local.date()
    time_part = local.strftime("%H:%M")
    suffix = " (UTC+1)"

    if date_part == today:
        return f"сегодня в {time_part}{suffix}"
    if date_part == today + dt.timedelta(days=1):
        return f"завтра в {time_part}{suffix}"
    weekday = _WEEKDAYS_RU[date_part.weekday()]
    return f"{weekday}, {time_part}{suffix}"


async def send_telegram_message(
    chat_id: int,
    text: str,
    *,
    message_effect_id: Optional[str] = None,
) -> bool:
    """
    Отправить одно сообщение в Telegram.
    Если передан message_effect_id — эффект будет применён (для личных чатов при отправке
    по user id эффекты поддерживаются). Если не передан — сообщение без эффекта.
    """
    settings = get_settings()
    if not settings.bot_token:
        logger.warning("BOT_TOKEN not configured, skip send_telegram_message")
        return False
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    payload: dict = {"chat_id": chat_id, "text": text}
    if message_effect_id:
        payload["message_effect_id"] = message_effect_id
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json=payload)
            r.raise_for_status()
        return True
    except httpx.HTTPStatusError as e:
        body = ""
        try:
            body = e.response.text
        except Exception:
            body = ""
        logger.warning(
            "Failed to send Telegram message to %s: status=%s body=%s",
            chat_id,
            getattr(e.response, "status_code", None),
            body[:1000],
        )
        return False
    except Exception as e:
        logger.warning("Failed to send Telegram message to %s: %s", chat_id, e)
        return False


async def broadcast_deal_opened(
    telegram_ids: List[int],
    deal_number: int,
    *,
    close_at: Optional[dt.datetime] = None,
) -> None:
    """
    Рассылка об открытии новой сделки (регистрация открыта).
    Шаблон: открыта сделка, раздел «Инвестировать», время закрытия регистрации в UTC+1.
    """
    if not telegram_ids:
        return

    close_time_human = format_time_utc1(close_at) if close_at else "—"

    text = (
        f"🔔 Открыта новая сделка #{deal_number}\n\n"
        "Вы можете инвестировать USDT в разделе:\n"
        "💰 Инвестировать\n\n"
        f"⏳ Регистрация открыта до:\n{close_time_human}\n\n"
        "Для участия используйте нашего Telegram бота."
    )

    sent = 0
    for tid in telegram_ids:
        if await send_telegram_message(tid, text, message_effect_id=EFFECT_CELEBRATION):
            sent += 1

    logger.info(
        "broadcast_deal_opened: deal_number=%s total=%s sent=%s",
        deal_number,
        len(telegram_ids),
        sent,
    )


async def broadcast_deal_closed(
    telegram_ids: List[int],
    deal_number: int,
    profit_percent: float | None,
    participant_telegram_ids: set[int],
    *,
    next_open_at: Optional[dt.datetime] = None,
) -> None:
    """
    Рассылка о закрытии регистрации на сделку.
    Участникам с прибылью — с процентом и эффектом; остальным — время следующего открытия.
    """
    if not telegram_ids:
        return

    next_open_human = format_time_utc1(next_open_at) if next_open_at else "—"

    sent = 0
    for tid in telegram_ids:
        if tid in participant_telegram_ids and profit_percent is not None:
            text = (
                f"🔔 Регистрация на сделку #{deal_number} закрыта.\n\n"
                f"Ваша прибыль {profit_percent}%.\n\n"
                "Следующая сделка откроется:\n"
                f"⏰ {next_open_human}\n\n"
                "Для участия используйте нашего Telegram бота."
            )
            effect_id = EFFECT_FIRE
        else:
            text = (
                f"🔔 Регистрация на сделку #{deal_number} закрыта.\n\n"
                "Следующая сделка откроется:\n"
                f"⏰ {next_open_human}\n\n"
                "Для участия используйте нашего Telegram бота."
            )
            effect_id = None
        if await send_telegram_message(tid, text, message_effect_id=effect_id):
            sent += 1

    logger.info(
        "broadcast_deal_closed: deal_number=%s total=%s participants=%s sent=%s",
        deal_number,
        len(telegram_ids),
        len(participant_telegram_ids),
        sent,
    )


async def notify_deposit_success(telegram_id: int, amount: str) -> bool:
    """
    Уведомить пользователя об успешном зачислении пополнения.
    Вызывается с бэкенда после apply_payment_to_balance (личный чат по telegram_id).
    """
    text = (
        "✅ Пополнение зачислено на баланс.\n\n"
        f"Сумма: {amount} USDT.\n\n"
        "Проверьте раздел «Баланс» в боте."
    )
    return await send_telegram_message(
        telegram_id,
        text,
        message_effect_id=EFFECT_CELEBRATION,
    )
