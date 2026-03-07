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
    Рассылка о завершении сделки: всем пользователям разный текст.
    Участникам — с строкой про прибыль (profit_percent из админки).
    """
    if not telegram_ids:
        return
    base_text = f"Сделка #{deal_number} завершена."
    for tid in telegram_ids:
        if tid in participant_telegram_ids and profit_percent is not None:
            text = f"{base_text}\nВаша прибыль: {profit_percent}%"
        else:
            text = base_text
        await send_telegram_message(tid, text)
