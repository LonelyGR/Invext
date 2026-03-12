"""
Статистика: суммы своих депозитов/выводов и количество заявок.
"""
from aiogram import Router, F
from aiogram.types import Message
import logging

from src.api_client.client import api
from src.keyboards.menus import back_kb

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
        await message.answer("Пользователь не найден. Отправьте /start.")
        return

    d_usdt = me.get("my_deposits_total_usdt", "0")
    d_usdc = me.get("my_deposits_total_usdc", "0")
    w_usdt = me.get("my_withdrawals_total_usdt", "0")
    w_usdc = me.get("my_withdrawals_total_usdc", "0")
    deposits_count = me.get("deposits_count", 0)
    withdrawals_count = me.get("withdrawals_count", 0)

    # Пока прибыль и доход с рефералов явно не агрегируются в API,
    # показываем их как 0 для понятного интерфейса.
    profit_total = "0"
    referral_income = "0"
    deals_total = 0
    active_deals = 0

    text = (
        "📊 <b>Статистика пользователя</b>\n\n"
        "<b>Ваши депозиты:</b>\n"
        f"USDT: {d_usdt}, USDC: {d_usdc}\n\n"
        "<b>Ваши выводы:</b>\n"
        f"USDT: {w_usdt}, USDC: {w_usdc}\n\n"
        f"Общая прибыль: {profit_total} USDT\n"
        f"Доход с рефералов: {referral_income} USDT\n\n"
        f"Всего сделок: {deals_total}\n"
        f"Активных сделок: {active_deals}\n\n"
        f"Заявок на пополнение: {deposits_count}\n"
        f"Заявок на вывод: {withdrawals_count}"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=back_kb())
