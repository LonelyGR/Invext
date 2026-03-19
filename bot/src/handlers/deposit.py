"""
Пополнение баланса через NOWPayments (USDT BEP20).
"""
from decimal import Decimal, InvalidOperation

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.api_client.client import api
from src.keyboards.menus import main_menu_kb
from src.utils.effects import send_effect_message, EFFECT_CELEBRATION
from src.utils.locks import with_double_click_protection, release_double_click_lock
from src.texts import (
    make_deposit_start_text,
    make_deposit_history_intro_text,
    make_deposit_invoice_text,
    make_deposit_history_empty_text,
    make_deposit_history_list_text,
    make_deposit_invoice_confirmed_text,
    make_deposit_balance_credited_text,
)
import logging

router = Router(name="deposit")
logger = logging.getLogger(__name__)


class DepositStates(StatesGroup):
    entering_amount = State()


def _invoice_kb(pay_url: str, invoice_id: int) -> InlineKeyboardMarkup:
    """invoice_id — внутренний id (PaymentInvoice.id) для кнопки «Проверить оплату»."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_invoice_{invoice_id}")],
        ]
    )


def _deposit_history_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 История пополнений", callback_data="deposit_history")],
        ]
    )


@router.message(F.text == "📥 Пополнить")
async def deposit_start(message: Message, state: FSMContext):
    """Начать пополнение: спросить сумму для инвойса NOWPayments (USDT BEP20)."""
    await state.clear()
    await state.set_state(DepositStates.entering_amount)
    # Для текстовых подсказок пытаемся получить лимиты с бэкенда,
    # но логика проверки всё равно на стороне бэкенда.
    min_dep = "10"
    max_dep = "100000"
    try:
        settings = await api.get_system_settings()
        min_dep = settings.get("min_deposit_usdt", min_dep)
        max_dep = settings.get("max_deposit_usdt", max_dep)
    except Exception:
        pass
    await message.answer(
        make_deposit_start_text(min_dep),
        reply_markup=main_menu_kb(),
    )
    await message.answer(
        make_deposit_history_intro_text(),
        reply_markup=_deposit_history_kb(),
    )


@router.message(DepositStates.entering_amount, F.text)
async def deposit_amount_entered(message: Message, state: FSMContext):
    if not await with_double_click_protection(message, "deposit"):
        return
    try:
        try:
            amount = Decimal((message.text or "").replace(",", ".").strip())
        except InvalidOperation:
            await message.answer("Введите число, например: 100 или 50.5")
            return
        if amount <= 0:
            await message.answer("Сумма должна быть больше 0.")
            return

        telegram_id = message.from_user.id

        try:
            invoice = await api.create_deposit_invoice(telegram_id, amount)
        except Exception as e:
            err = str(e)
            if hasattr(e, "response") and getattr(e, "response", None) is not None:
                try:
                    body = e.response.json()
                    if isinstance(body, dict) and "detail" in body:
                        err = body["detail"] if isinstance(body["detail"], str) else str(body["detail"])
                except Exception:
                    pass
            logger.error("deposit invoice creation failed for user %s: %s", telegram_id, err)
            await message.answer(f"Ошибка при создании инвойса: {err}", reply_markup=main_menu_kb())
            await state.clear()
            return

        invoice_id = invoice.get("invoice_id")
        pay_url = invoice.get("invoice_url")

        if not invoice_id or not pay_url:
            logger.error("deposit invoice missing url/id for user %s", telegram_id)
            await message.answer("Не удалось получить ссылку на оплату.", reply_markup=main_menu_kb())
            await state.clear()
            return

        await message.answer(
            make_deposit_invoice_text(amount),
            parse_mode="HTML",
            reply_markup=_invoice_kb(pay_url, int(invoice_id)),
        )
        await state.clear()
        logger.info("user %s created deposit invoice_id=%s amount=%s", telegram_id, invoice_id, amount)
    finally:
        await release_double_click_lock(message.from_user.id, "deposit")


@router.callback_query(F.data == "deposit_history")
async def deposit_history(callback: CallbackQuery):
    """Показать историю пополнений пользователя."""
    telegram_id = callback.from_user.id if callback.from_user else 0
    try:
        items = await api.get_my_invoices(telegram_id, limit=15)
    except Exception as e:
        err = str(e)
        if hasattr(e, "response") and getattr(e, "response", None) is not None:
            try:
                body = e.response.json()
                if isinstance(body, dict) and "detail" in body:
                    err = body["detail"] if isinstance(body["detail"], str) else str(body["detail"])
            except Exception:
                pass
        await callback.answer(f"Ошибка: {err}", show_alert=True)
        return

    if not items:
        await callback.message.edit_text(
            make_deposit_history_empty_text(),
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
                ]
            ),
        )
        await callback.answer()
        return

    text = make_deposit_history_list_text(items)
    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
            ]
        ),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("check_invoice_"))
async def check_invoice_status(callback: CallbackQuery):
    """Проверка статуса пополнения (GET deposit by id)."""
    try:
        invoice_id = int(callback.data.replace("check_invoice_", ""))
    except ValueError:
        await callback.answer("Некорректный инвойс.", show_alert=True)
        return

    telegram_id = callback.from_user.id if callback.from_user else 0
    try:
        invoice = await api.get_deposit_invoice(invoice_id, telegram_id)
    except Exception as e:
        err = str(e)
        if hasattr(e, "response") and getattr(e, "response", None) is not None:
            try:
                body = e.response.json()
                if isinstance(body, dict) and "detail" in body:
                    err = body["detail"] if isinstance(body["detail"], str) else str(body["detail"])
            except Exception:
                pass
        await callback.answer(f"Ошибка: {err}", show_alert=True)
        return

    status = (invoice.get("status") or "").lower()
    balance_credited = invoice.get("balance_credited", False)
    if status == "finished" or balance_credited:
        await callback.message.edit_text(
            make_deposit_invoice_confirmed_text(),
            reply_markup=main_menu_kb(),
        )
        await send_effect_message(
            callback.bot,
            callback.message.chat.id,
            make_deposit_balance_credited_text(),
            effect_id=EFFECT_CELEBRATION,
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
    else:
        await callback.answer("Инвойс ещё не оплачен или не подтверждён в сети.", show_alert=True)
