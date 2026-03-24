"""
Раздел «Баланс»: показать текущий баланс и пояснить, что на нём также накапливаются реферальные начисления.
"""
from aiogram import Router, F
from aiogram.types import Message

from src.api_client.client import api
from src.keyboards.menus import main_menu_kb
from src.texts import make_balance_text
from src.config.settings import ADMIN_TELEGRAM_IDS

router = Router(name="balance")


@router.message(F.text == "💰 Баланс")
async def balance_main(message: Message):
    telegram_id = message.from_user.id
    try:
        balances = await api.get_balances(telegram_id)
    except Exception as e:
        await message.answer(f"Ошибка: {e}", reply_markup=main_menu_kb(telegram_id in ADMIN_TELEGRAM_IDS))
        return

    usdt = balances.get("USDT", 0)
    text = make_balance_text(usdt)
    await message.answer(text, reply_markup=main_menu_kb(telegram_id in ADMIN_TELEGRAM_IDS))

