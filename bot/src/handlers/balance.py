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
        await message.answer(
            f"Ошибка: {e}",
            reply_markup=main_menu_kb(telegram_id in ADMIN_TELEGRAM_IDS),
        )
        return

    usdt = balances.get("USDT", 0)
    text = make_balance_text(usdt)
    show_bonus = False
    try:
        bonus_status = await api.get_welcome_bonus_status(telegram_id)
        show_bonus = bool(bonus_status.get("available"))
    except Exception:
        show_bonus = False

    await message.answer(
        text,
        reply_markup=main_menu_kb(telegram_id in ADMIN_TELEGRAM_IDS, show_welcome_bonus=show_bonus),
    )


@router.message(F.text == "🎁 Бонус 100")
async def welcome_bonus_claim(message: Message):
    telegram_id = message.from_user.id
    try:
        result = await api.claim_welcome_bonus(telegram_id)
    except Exception as e:
        await message.answer(f"Не удалось начислить бонус: {e}")
        return

    if not result.get("success"):
        detail = result.get("detail") or "Бонус недоступен."
        await message.answer(detail)
        return

    amount = result.get("amount") or 0
    await message.answer(f"✅ Приветственный бонус {amount} USDT начислен на ваш баланс.")

