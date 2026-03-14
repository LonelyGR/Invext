"""
Отправка сообщений с Telegram message effects в личных чатах.
Эффекты работают только в private-чатах; в группах/каналах отправка без эффекта.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from aiogram import Bot
from aiogram.types import Message

logger = logging.getLogger(__name__)

# Effect IDs для ключевых событий (личные чаты)
EFFECT_CELEBRATION = "5046509860389126442"  # 🎉
EFFECT_FIRE = "5104841245755180586"  # 🔥


async def send_effect_message(
    bot: Bot,
    chat_id: int,
    text: str,
    effect_id: Optional[str] = None,
    **kwargs: Any,
) -> Message:
    """
    Отправить сообщение; в личном чате применить effect_id, иначе — обычное сообщение.
    Если effect_id не задан — сообщение без эффекта.
    """
    use_effect = False
    if effect_id:
        try:
            chat = await bot.get_chat(chat_id)
            if chat.type == "private":
                use_effect = True
        except Exception as e:
            logger.debug("Could not get chat %s for effect check: %s", chat_id, e)

    if use_effect:
        return await bot.send_message(
            chat_id=chat_id,
            text=text,
            message_effect_id=effect_id,
            **kwargs,
        )
    return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
