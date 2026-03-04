"""
Пополнение баланса через инвойсы Crypto Pay (CryptoBot).
"""
from decimal import Decimal, InvalidOperation

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.api_client.client import api
from src.config.settings import MIN_DEPOSIT, MAX_DEPOSIT
from src.keyboards.menus import main_menu_kb

router = Router(name="deposit")


class DepositStates(StatesGroup):
    entering_amount = State()


def _invoice_kb(pay_url: str, invoice_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=pay_url)],
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_invoice_{invoice_id}")],
        ]
    )


@router.message(F.text == "💳 Пополнить")
async def deposit_start(message: Message, state: FSMContext):
    """Начать пополнение: спросить сумму для инвойса Crypto Pay."""
    await state.clear()
    await state.set_state(DepositStates.entering_amount)
    await message.answer(
        "Введите сумму пополнения в USDT.\n"
        f"Минимум: {MIN_DEPOSIT}, максимум: {MAX_DEPOSIT}",
        reply_markup=main_menu_kb(),
    )


@router.message(DepositStates.entering_amount, F.text)
async def deposit_amount_entered(message: Message, state: FSMContext):
    try:
        amount = Decimal(message.text.replace(",", ".").strip())
    except InvalidOperation:
        await message.answer("Введите число, например: 100 или 50.5")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0.")
        return
    if amount < Decimal(str(MIN_DEPOSIT)) or amount > Decimal(str(MAX_DEPOSIT)):
        await message.answer(f"Сумма должна быть от {MIN_DEPOSIT} до {MAX_DEPOSIT}.")
        return

    telegram_id = message.from_user.id

    try:
        invoice = await api.create_crypto_invoice(telegram_id, amount, asset="USDT")
    except Exception as e:
        err = str(e)
        if hasattr(e, "response") and getattr(e, "response", None) is not None:
            try:
                body = e.response.json()
                if isinstance(body, dict) and "detail" in body:
                    err = body["detail"] if isinstance(body["detail"], str) else str(body["detail"])
            except Exception:
                pass
        await message.answer(f"Ошибка при создании инвойса: {err}", reply_markup=main_menu_kb())
        await state.clear()
        return

    invoice_id = invoice.get("invoice_id")
    pay_url = invoice.get("bot_invoice_url") or invoice.get("pay_url")

    if not invoice_id or not pay_url:
        await message.answer("Не удалось получить ссылку на оплату от Crypto Pay.", reply_markup=main_menu_kb())
        await state.clear()
        return

    await message.answer(
        "💳 <b>Пополнение USDT через Crypto Pay</b>\n\n"
        f"Сумма: <b>{amount}</b> USDT\n\n"
        "1) Нажмите «Оплатить» и завершите оплату в CryptoBot.\n"
        "2) Затем нажмите «Проверить оплату».\n",
        parse_mode="HTML",
        reply_markup=_invoice_kb(pay_url, int(invoice_id)),
    )
    await state.clear()


@router.callback_query(F.data.startswith("check_invoice_"))
async def check_invoice_status(callback: CallbackQuery):
    """Ручная проверка статуса инвойса (без вебхука)."""
    try:
        invoice_id = int(callback.data.replace("check_invoice_", ""))
    except ValueError:
        await callback.answer("Некорректный инвойс.", show_alert=True)
        return

    try:
        invoice = await api.sync_crypto_invoice(invoice_id)
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
    if status == "paid":
        await callback.message.edit_text(
            "✅ Оплата получена, баланс будет обновлён.\n"
            "Проверьте раздел «Профиль», чтобы увидеть новый баланс.",
            reply_markup=main_menu_kb(),
        )
        await callback.answer()
    else:
        await callback.answer("Инвойс ещё не оплачен или не подтверждён.", show_alert=True)
