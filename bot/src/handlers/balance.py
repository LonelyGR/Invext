"""
Раздел «Баланс»: показать текущий баланс и пояснить, что на нём также накапливаются реферальные начисления.
"""
from aiogram import Router, F
from aiogram.types import Message

from src.api_client.client import api
from src.keyboards.menus import main_menu_kb

router = Router(name="balance")


@router.message(F.text == "💰 Баланс")
async def balance_main(message: Message):
    telegram_id = message.from_user.id
    try:
        me = await api.get_me(telegram_id)
        balances = await api.get_balances(telegram_id)
    except Exception as e:
        await message.answer(f"Ошибка: {e}", reply_markup=main_menu_kb())
        return

    usdt = balances.get("USDT", 0)
    usdc = balances.get("USDC", 0)
    text = (
        "💰 <b>Ваш баланс</b>\n\n"
        f"USDT: {usdt}\n"
        f"USDC: {usdc}\n\n"
        "Реферальные бонусы начисляются на тот же баланс и доступны для участия в сделках или вывода."
    )
    await message.answer(text, reply_markup=main_menu_kb())

