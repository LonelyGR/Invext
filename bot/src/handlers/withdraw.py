"""
Вывести: выбор валюты → FSM сумма → FSM адрес → POST /withdrawals/request.
"""
from decimal import Decimal, InvalidOperation
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.api_client.client import api
from src.config.settings import ALLOWED_CURRENCIES
from src.keyboards.menus import (
    main_menu_kb,
    my_withdrawals_reply_kb,
    withdraw_entry_kb,
    withdraw_mid_flow_kb,
)
from src.utils.locks import with_double_click_protection, release_double_click_lock
from src.texts import (
    make_my_withdrawals_list_text,
    make_withdraw_choose_currency_text,
    make_withdraw_enter_amount_text,
    make_withdraw_enter_address_text,
    make_withdraw_success_text,
)
import logging

router = Router(name="withdraw")
logger = logging.getLogger(__name__)


async def _has_pending_withdrawals(telegram_id: int) -> bool:
    try:
        items = await api.get_my_withdrawals(telegram_id)
    except Exception:
        return False
    return any(str(x.get("status")) == "PENDING" for x in (items or []))


class WithdrawStates(StatesGroup):
    choosing_currency = State()
    entering_amount = State()
    entering_address = State()


@router.message(F.text == "📤 Вывести")
async def withdraw_start(message: Message, state: FSMContext):
    try:
        settings = await api.get_system_settings()
        if settings.get("allow_withdrawals") is False:
            await message.answer("На данный момент вывод недоступен по техническим причинам. Пожалуйста, ожидайте.")
            return
    except Exception:
        pass
    await state.clear()
    await state.set_state(WithdrawStates.choosing_currency)
    show_my = await _has_pending_withdrawals(message.from_user.id)
    await message.answer(
        make_withdraw_choose_currency_text(),
        reply_markup=withdraw_entry_kb(show_my_active=show_my),
    )


@router.callback_query(
    F.data.in_({f"withdraw_{c}" for c in ALLOWED_CURRENCIES}),
    WithdrawStates.choosing_currency,
)
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
        # Бизнес-правило: минимум 50.
        try:
            min_wd_val = Decimal(str(settings.get("min_withdraw_usdt", min_wd)).replace(",", "."))
        except Exception:
            min_wd_val = Decimal(str(min_wd))
        min_wd = str(max(min_wd_val, Decimal("50")))
        max_wd = settings.get("max_withdraw_usdt", max_wd)
    except Exception:
        pass
    show_my = await _has_pending_withdrawals(callback.from_user.id)
    await callback.message.edit_text(
        make_withdraw_enter_amount_text(currency, min_wd, max_wd),
        reply_markup=withdraw_mid_flow_kb(show_my_active=show_my),
    )
    await callback.answer()


@router.callback_query(F.data == "wd_my_requests")
async def withdraw_my_requests(callback: CallbackQuery, state: FSMContext):
    """Список заявок на вывод и отмена (доступ из раздела «Вывести»)."""
    await state.clear()
    telegram_id = callback.from_user.id
    try:
        items = await api.get_my_withdrawals(telegram_id)
    except Exception as e:
        logger.exception("wd_my_requests: %s", e)
        await callback.answer("Не удалось загрузить заявки.", show_alert=True)
        return
    await callback.message.edit_text(
        make_my_withdrawals_list_text(items),
        reply_markup=my_withdrawals_reply_kb(items),
        parse_mode="HTML",
    )
    await callback.answer()


@router.callback_query(F.data == "wd_new_withdraw")
async def withdraw_new_from_list(callback: CallbackQuery, state: FSMContext):
    """С экрана списка — снова создать заявку."""
    try:
        settings = await api.get_system_settings()
        if settings.get("allow_withdrawals") is False:
            await callback.answer(
                "Вывод временно недоступен.",
                show_alert=True,
            )
            return
    except Exception:
        pass
    await state.clear()
    await state.set_state(WithdrawStates.choosing_currency)
    show_my = await _has_pending_withdrawals(callback.from_user.id)
    await callback.message.edit_text(
        make_withdraw_choose_currency_text(),
        reply_markup=withdraw_entry_kb(show_my_active=show_my),
        parse_mode="HTML",
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
    show_my = await _has_pending_withdrawals(message.from_user.id)
    await message.answer(
        make_withdraw_enter_address_text(),
        reply_markup=withdraw_mid_flow_kb(show_my_active=show_my),
    )


@router.message(WithdrawStates.entering_address, F.text)
async def withdraw_address_entered(message: Message, state: FSMContext):
    if not await with_double_click_protection(message, "withdraw"):
        return
    telegram_id = message.from_user.id
    try:
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
            return

        req_id = result.get("id", "—")
        try:
            req_id_int = int(req_id)
        except Exception:
            req_id_int = None
        await message.answer(
            make_withdraw_success_text(
                req_id,
                gross=result.get("amount", amount),
                fee=result.get("fee_amount", "—"),
                net=result.get("net_amount", "—"),
                currency=currency,
            ),
            reply_markup=(
                InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="❌ Отменить вывод", callback_data=f"withdraw_cancel_{req_id_int}")],
                        [InlineKeyboardButton(text="📋 Мои заявки на вывод", callback_data="wd_my_requests")],
                        [InlineKeyboardButton(text="◀️ В меню", callback_data="back_to_menu")],
                    ]
                )
                if req_id_int is not None
                else main_menu_kb()
            ),
        )
        await state.clear()
        await state.set_data({})
        logger.info("user %s created withdraw request id=%s amount=%s %s", telegram_id, req_id, amount, currency)
    finally:
        await release_double_click_lock(telegram_id, "withdraw")


@router.callback_query(F.data.startswith("withdraw_cancel_"))
async def withdraw_cancel(callback: CallbackQuery, state: FSMContext):
    telegram_id = callback.from_user.id
    try:
        withdraw_id = int(callback.data.replace("withdraw_cancel_", ""))
    except Exception:
        await callback.answer("Некорректная заявка", show_alert=True)
        return
    try:
        await api.cancel_withdraw_request(telegram_id, withdraw_id)
    except Exception as e:
        err = str(e)
        if hasattr(e, "response") and getattr(e, "response", None) is not None:
            try:
                body = e.response.json()
                if isinstance(body, dict) and "detail" in body:
                    err = body["detail"] if isinstance(body["detail"], str) else str(body["detail"])
            except Exception:
                pass
        await callback.answer(f"Не удалось отменить: {err}", show_alert=True)
        return
    await state.clear()
    try:
        items = await api.get_my_withdrawals(telegram_id)
        await callback.message.edit_text(
            make_my_withdrawals_list_text(items),
            reply_markup=my_withdrawals_reply_kb(items),
            parse_mode="HTML",
        )
    except Exception:
        await callback.message.edit_text("✅ Заявка на вывод отменена.")
    await callback.answer()
