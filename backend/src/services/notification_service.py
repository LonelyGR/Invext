"""
Отправка уведомлений в Telegram. Бот расчётов не делает — только рассылка с бэкенда.
"""
from __future__ import annotations

import logging
from typing import List

import httpx

from src.core.config import get_settings

logger = logging.getLogger(__name__)


async def send_telegram_message(chat_id: int, text: str) -> bool:
    """Отправить одно сообщение в Telegram. Возвращает True при успехе."""
    settings = get_settings()
    if not settings.bot_token:
        logger.warning("BOT_TOKEN not configured, skip send_telegram_message")
        return False
    url = f"https://api.telegram.org/bot{settings.bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(url, json={"chat_id": chat_id, "text": text})
            r.raise_for_status()
        return True
    except Exception as e:
        logger.warning("Failed to send Telegram message to %s: %s", chat_id, e)
        return False


async def broadcast_deal_closed(
    telegram_ids: List[int],
    deal_number: int,
    profit_percent: float | None,
    participant_telegram_ids: set[int],
) -> None:
    """
    Рассылка о закрытии сделки.

    A. Для пользователей, которые НЕ инвестировали в закрываемую сделку:

    🔔 Уважаемые участники, регистрация на сделку #{{deal_number}} закрыта.

    Пожалуйста, ожидайте информацию в чате для участия в следующей сделке, которая откроется в 13:30 (UTC+1).

    ❗️Для участия в следующей сделке, пожалуйста, используйте нашего Telegram бота.

    B. Для пользователей, которые инвестировали в закрываемую сделку:

    🔔 Уважаемые участники, регистрация на сделку #{{deal_number}} закрыта.

    Ваша прибыль {{profit_percent}}%.

    Пожалуйста, ожидайте информацию в чате для участия в следующей сделке, которая откроется в 13:30 (UTC+1).

    ❗️Для участия в следующей сделке, пожалуйста, используйте нашего Telegram бота.
    """
    if not telegram_ids:
        return

    sent = 0
    for tid in telegram_ids:
        if tid in participant_telegram_ids and profit_percent is not None:
            text = (
                f"🔔 Уважаемые участники, регистрация на сделку #{deal_number} закрыта.\n\n"
                f"Ваша прибыль {profit_percent}%.\n\n"
                "Пожалуйста, ожидайте информацию в чате для участия в следующей сделке, "
                "которая откроется в 13:30 (UTC+1).\n\n"
                "❗️Для участия в следующей сделке, пожалуйста, используйте нашего Telegram бота."
            )
        else:
            text = (
                f"🔔 Уважаемые участники, регистрация на сделку #{deal_number} закрыта.\n\n"
                "Пожалуйста, ожидайте информацию в чате для участия в следующей сделке, "
                "которая откроется в 13:30 (UTC+1).\n\n"
                "❗️Для участия в следующей сделке, пожалуйста, используйте нашего Telegram бота."
            )
        if await send_telegram_message(tid, text):
            sent += 1

    logger.info(
        "broadcast_deal_closed: deal_number=%s total=%s participants=%s sent=%s",
        deal_number,
        len(telegram_ids),
        len(participant_telegram_ids),
        sent,
    )
