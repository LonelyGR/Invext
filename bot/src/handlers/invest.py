"""
Раздел «Сделка»: отображение открытой сделки, кнопка «Участвовать», ввод суммы.
Инвестиции — списание виртуального баланса (USDT) через /api/invest.
"""
from decimal import Decimal, InvalidOperation

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.api_client.client import api
from src.keyboards.menus import back_kb
from src.utils.effects import send_effect_message, EFFECT_CELEBRATION
from src.utils.locks import with_double_click_protection, release_double_click_lock
import logging

router = Router(name="invest")
logger = logging.getLogger(__name__)


class InvestStates(StatesGroup):
    entering_amount = State()


def _invest_deal_kb(with_participate: bool) -> InlineKeyboardMarkup:
    """Клавиатура раздела Сделка: при открытой сделке — Участвовать + Назад, иначе только Назад."""
    rows = []
    if with_participate:
        rows.append([InlineKeyboardButton(text="✅ Участвовать", callback_data="invest_participate")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
        active = await api.get_active_deal()
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return

    usdt = float(balances.get("USDT", 0) or 0)
    available_usdt = f"{usdt:.2f}"

    if active.get("active") and active.get("deal_number"):
        deal_number = active["deal_number"]
        text = (
            f"<b>Сделка #{deal_number}</b> открыта.\n\n"
            "💰 <b>Доступно для инвестиций (виртуальный баланс USDT):</b>\n"
            f"USDT: {available_usdt}\n\n"
            "Нажмите <b>«Участвовать»</b>, чтобы вложить средства в текущую сделку.\n"
            "Минимальная сумма настраивается администратором."
        )
        await message.answer(text, reply_markup=_invest_deal_kb(with_participate=True))
    else:
        text = (
            "Сейчас нет открытой сделки.\n\n"
            "Ожидайте уведомление в боте о новой сделке, затем зайдите в раздел <b>📈 Сделка</b> и нажмите <b>«Участвовать»</b>."
        )
        await state.clear()
        await message.answer(text, reply_markup=_invest_deal_kb(with_participate=False))


@router.callback_query(F.data == "invest_participate")
async def invest_participate(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал «Участвовать» — просим ввести сумму с подсказкой минимума."""
    telegram_id = callback.from_user.id
    try:
        settings = await api.get_system_settings()
        min_invest = settings.get("min_invest_usdt")
    except Exception:
        min_invest = None

    await state.set_state(InvestStates.entering_amount)

    hint = f"Минимальная сумма: {min_invest} USDT" if min_invest is not None else "Введите сумму инвестиций."
    await callback.message.edit_text(
        "Введите сумму, которую хотите инвестировать (только цифрами).\n\n"
        f"{hint}",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]]
        ),
    )
    await callback.answer()


@router.message(InvestStates.entering_amount)
async def invest_amount_entered(message: Message, state: FSMContext):
    telegram_id = message.from_user.id
    if not await with_double_click_protection(message, "invest"):
        return
    try:
        raw = (message.text or "").replace(",", ".").strip()

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
    finally:
        await release_double_click_lock(telegram_id, "invest")
