"""
Статистика: суммы своих депозитов/выводов и количество заявок.
"""
from aiogram import Router, F
from aiogram.types import Message
import logging

from src.api_client.client import api
from src.keyboards.menus import back_kb
from src.texts import make_stats_text

router = Router(name="stats")
logger = logging.getLogger(__name__)


@router.message(F.text == "📊 Статистика")
async def stats(message: Message):
    telegram_id = message.from_user.id
    try:
        me = await api.get_me(telegram_id)
    except Exception as e:
        logger.error("statistics handler failed for user %s: %s", telegram_id, e)
        await message.answer(f"Ошибка: {e}")
        return

    if not me:
        await message.answer("Пользователь временно недоступен. Попробуйте ещё раз через пару секунд.")
        return

    text = make_stats_text(me)
    await message.answer(text, parse_mode="HTML", reply_markup=back_kb())
