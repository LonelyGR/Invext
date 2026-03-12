"""
Вывести: выбор валюты → FSM сумма → FSM адрес → POST /withdrawals/request.
"""
from decimal import Decimal, InvalidOperation
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.api_client.client import api
from src.config.settings import ALLOWED_CURRENCIES
from src.keyboards.menus import currency_kb, main_menu_kb
from src.utils.locks import with_double_click_protection, release_double_click_lock
import logging

router = Router(name="withdraw")
logger = logging.getLogger(__name__)


class WithdrawStates(StatesGroup):
    choosing_currency = State()
    entering_amount = State()
    entering_address = State()


@router.message(F.text == "📤 Вывести")
async def withdraw_start(message: Message, state: FSMContext):
    await state.clear()
    await state.set_state(WithdrawStates.choosing_currency)
    await message.answer(
        "Выберите валюту вывода:",
        reply_markup=currency_kb("withdraw_"),
    )


@router.callback_query(F.data.startswith("withdraw_"), WithdrawStates.choosing_currency)
async def withdraw_currency_chosen(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.replace("withdraw_", "")
    if currency not in ALLOWED_CURRENCIES:
        await callback.answer("Неверная валюта")
        return
    await state.update_data(currency=currency)
    await state.set_state(WithdrawStates.entering_amount)
    # Получаем актуальные лимиты для текста (валидация на бэкенде).
    min_wd = "10"
    max_wd = "100000"
    try:
        settings = await api.get_system_settings()
        min_wd = settings.get("min_withdraw_usdt", min_wd)
        max_wd = settings.get("max_withdraw_usdt", max_wd)
    except Exception:
        pass
    await callback.message.edit_text(
        f"Введите сумму вывода ({currency}).\n"
        f"Минимум: {min_wd}, максимум: {max_wd}"
    )
    await callback.answer()


@router.message(WithdrawStates.entering_amount, F.text)
async def withdraw_amount_entered(message: Message, state: FSMContext):
    try:
        amount = Decimal(message.text.replace(",", ".").strip())
    except InvalidOperation:
        await message.answer("Введите число, например: 100 или 50.5")
        return
    if amount <= 0:
        await message.answer("Сумма должна быть больше 0.")
        return

    await state.update_data(amount=message.text.strip())
    await state.set_state(WithdrawStates.entering_address)
    await message.answer("Введите адрес кошелька для вывода (строка):")


@router.message(WithdrawStates.entering_address, F.text)
async def withdraw_address_entered(message: Message, state: FSMContext):
    if not await with_double_click_protection(message, "withdraw"):
        return
    address = (message.text or "").strip()
    if not address or len(address) > 512:
        await message.answer("Адрес не может быть пустым и не более 512 символов.")
        return

    data = await state.get_data()
    currency = data.get("currency", "USDT")
    try:
        amount = Decimal(str(data.get("amount", 0)))
    except (InvalidOperation, TypeError):
        await message.answer("Ошибка: неверная сумма. Начните заново (Вывести).")
        await state.clear()
        return

    telegram_id = message.from_user.id

    try:
        result = await api.create_withdraw_request(
            telegram_id, currency, amount, address
        )
    except Exception as e:
        err = str(e)
        if hasattr(e, "response") and getattr(e, "response", None) is not None:
            try:
                body = e.response.json()
                if isinstance(body, dict) and "detail" in body:
                    err = body["detail"] if isinstance(body["detail"], str) else str(body["detail"])
            except Exception:
                pass
        logger.error("withdraw failed for user %s: %s", telegram_id, err)
        await message.answer(f"Ошибка: {err}")
        await state.clear()
        await release_double_click_lock(telegram_id, "withdraw")
        return

    req_id = result.get("id", "—")
    await message.answer(
        "✅ Ваша заявка на вывод успешно создана и отправлена на рассмотрение.\n"
        "Средства будут выведены в течение 48 часов после проверки заявки.\n"
        f"ID заявки: {req_id}",
        reply_markup=main_menu_kb(),
    )
    await state.clear()
    await state.set_data({})
    await release_double_click_lock(telegram_id, "withdraw")
    logger.info("user %s created withdraw request id=%s amount=%s %s", telegram_id, req_id, amount, currency)
