"""
Fallback-хендлеры для неизвестных сообщений и callback_query.

Цели:
- Логировать необработанные апдейты.
- Давать пользователю понятное сообщение об ошибке.
"""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.types import Message, CallbackQuery

router = Router(name="fallback")
logger = logging.getLogger(__name__)


@router.message()
async def unknown_message(message: Message):
    logger.warning("unknown update received from user %s: %r", message.from_user.id if message.from_user else None, message)
    await message.answer("Неизвестная команда. Пожалуйста, используйте кнопки меню.")


@router.callback_query()
async def unknown_callback(callback: CallbackQuery):
    logger.warning("unknown callback received from user %s: data=%s", callback.from_user.id, callback.data)
    await callback.answer("Неизвестная команда.", show_alert=True)

