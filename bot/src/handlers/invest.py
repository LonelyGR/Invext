"""
Инвестиции — списание виртуального баланса (USDT) через /api/invest.
Минимальная сумма: 50 USDT. Без выбора дат/сделок — сумма вводится вручную.
"""
from decimal import Decimal, InvalidOperation

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message

from src.api_client.client import api
from src.keyboards.menus import back_kb
from src.utils.effects import send_effect_message, EFFECT_CELEBRATION
from src.utils.locks import with_double_click_protection, release_double_click_lock
import logging

router = Router(name="invest")
logger = logging.getLogger(__name__)


class InvestStates(StatesGroup):
    entering_amount = State()


def _format_invest_screen(available_usdt: str) -> str:
    return (
        "<b>Инвестиции</b>\n\n"
        "💰 <b>Доступно для инвестиций (виртуальный баланс USDT):</b>\n"
        f"USDT: {available_usdt}\n\n"
        "Минимальная сумма одной инвестиции настраивается администратором.\n"
        "Отправьте сумму инвестиций цифрами ответом на это сообщение."
    )


@router.message(F.text == "📈 Сделка")
async def invest_section(message: Message, state: FSMContext):
    telegram_id = message.from_user.id
    try:
        balances = await api.get_balances(telegram_id)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return

    usdt = float(balances.get("USDT", 0) or 0)
    available_usdt = f"{usdt:.2f}"

    text = _format_invest_screen(available_usdt)
    await state.set_state(InvestStates.entering_amount)
    await message.answer(text, reply_markup=back_kb())


@router.message(InvestStates.entering_amount)
async def invest_amount_entered(message: Message, state: FSMContext):
    telegram_id = message.from_user.id
    if not await with_double_click_protection(message, "invest"):
        return
    raw = message.text.replace(",", ".").strip()

    try:
        amount = Decimal(raw)
    except (InvalidOperation, AttributeError):
        await message.answer("Введите сумму в формате числа, например: 50 или 75.5")
        return

    if amount <= 0:
        await message.answer("Сумма должна быть больше нуля.")
        return

    try:
        result = await api.invest(telegram_id, amount)
    except Exception as e:
        err = str(e)
        if hasattr(e, "response") and getattr(e, "response", None) is not None:
            try:
                body = e.response.json()
                if isinstance(body, dict) and "detail" in body:
                    err = body["detail"] if isinstance(body["detail"], str) else str(body["detail"])
            except Exception:
                pass

        logger.error("invest failed for user %s: %s", telegram_id, err)
        await message.answer(f"Ошибка инвестирования: {err}")
        await state.clear()
        await release_double_click_lock(telegram_id, "invest")
        return

    new_balance = result.get("balance_usdt")
    invested = result.get("invested_amount_usdt")

    success_text = (
        "✅ Инвестиция создана.\n"
        f"Сумма: {invested} USDT\n\n"
        f"Текущий виртуальный баланс: {new_balance} USDT\n\n"
        "Средства переведены в текущую сделку. Начисление прибыли произойдет\n"
        "после её завершения согласно условиям."
    )
    await send_effect_message(
        message.bot,
        message.chat.id,
        success_text,
        effect_id=EFFECT_CELEBRATION,
    )
    await state.clear()
    logger.info("user %s invested %s USDT into current deal", telegram_id, invested)
    await release_double_click_lock(telegram_id, "invest")
