"""
Кошельки: список сохранённых, добавление (название → валюта → адрес), удаление.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.api_client.client import api
from src.config.settings import ALLOWED_CURRENCIES
from src.keyboards.menus import wallets_list_kb, wallet_coin_kb, back_kb
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from src.texts import (
    make_wallets_list_text,
    make_wallets_load_error_text,
    make_wallet_add_enter_name_text,
    make_wallet_name_empty_text,
    make_wallet_choose_currency_text,
    make_wallet_invalid_currency_text,
    make_wallet_currency_set_text,
    make_wallet_cancelled_text,
    make_wallet_invalid_address_text,
    make_wallet_save_error_text,
    make_wallet_added_text,
    make_wallet_deleted_text,
)

router = Router(name="wallets")


class AddWalletStates(StatesGroup):
    entering_name = State()
    choosing_currency = State()
    entering_address = State()


async def _send_wallets_list(target, telegram_id: int, text_prefix: str = "", can_edit: bool = False):
    """Отправить или отредактировать сообщение со списком кошельков.
    can_edit: True только если target — сообщение бота (callback.message), иначе всегда answer().
    """
    try:
        wallets = await api.get_wallets(telegram_id)
    except Exception as e:
        await target.answer(make_wallets_load_error_text(e))
        return
    text = make_wallets_list_text(wallets, text_prefix=text_prefix)
    kb = wallets_list_kb()
    if wallets:
        rows = []
        for w in wallets:
            rows.append([InlineKeyboardButton(text=f"🗑 {w['name']}", callback_data=f"wallets_del_{w['id']}")])
        rows.append([InlineKeyboardButton(text="➕ Добавить кошелёк", callback_data="wallets_add")])
        rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
        kb = InlineKeyboardMarkup(inline_keyboard=rows)
    if can_edit:
        try:
            await target.edit_text(text, reply_markup=kb)
        except Exception:
            await target.answer(text, reply_markup=kb)
    else:
        await target.answer(text, reply_markup=kb)


@router.message(F.text == "⚙️ Кошелёк")
async def wallets_main(message: Message):
    await _send_wallets_list(message, message.from_user.id, can_edit=False)


@router.callback_query(F.data == "profile_wallets")
async def wallets_from_profile(callback: CallbackQuery):
    await _send_wallets_list(callback.message, callback.from_user.id, can_edit=True)
    await callback.answer()


@router.callback_query(F.data == "wallets_add")
async def wallets_add_start(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await state.set_state(AddWalletStates.entering_name)
    await callback.message.answer(make_wallet_add_enter_name_text())
    await callback.answer()


@router.message(AddWalletStates.entering_name, F.text)
async def wallet_name_entered(message: Message, state: FSMContext):
    name = (message.text or "").strip()[:255]
    if not name:
        await message.answer(make_wallet_name_empty_text())
        return
    await state.update_data(wallet_name=name)
    await state.set_state(AddWalletStates.choosing_currency)
    await message.answer(
        make_wallet_choose_currency_text(),
        reply_markup=wallet_coin_kb(),
    )


@router.callback_query(AddWalletStates.choosing_currency, F.data.startswith("wallet_coin_"))
async def wallet_currency_chosen(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.replace("wallet_coin_", "")
    if currency not in ALLOWED_CURRENCIES:
        await callback.answer(make_wallet_invalid_currency_text())
        return
    await state.update_data(wallet_currency=currency)
    await state.set_state(AddWalletStates.entering_address)
    await callback.message.edit_text(make_wallet_currency_set_text(currency))
    await callback.answer()


@router.callback_query(F.data == "wallets_cancel")
async def wallet_add_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await _send_wallets_list(callback.message, callback.from_user.id, can_edit=True)
    await callback.answer(make_wallet_cancelled_text())


@router.message(AddWalletStates.entering_address, F.text)
async def wallet_address_entered(message: Message, state: FSMContext):
    address = (message.text or "").strip()
    if not address or len(address) > 512:
        await message.answer(make_wallet_invalid_address_text())
        return
    data = await state.get_data()
    name = data.get("wallet_name", "")
    currency = data.get("wallet_currency", "USDT")
    telegram_id = message.from_user.id
    try:
        await api.create_wallet(telegram_id, name=name, currency=currency, address=address)
    except Exception as e:
        await message.answer(make_wallet_save_error_text(e))
        await state.clear()
        return
    await state.clear()
    await message.answer(make_wallet_added_text(name, currency))
    await _send_wallets_list(message, telegram_id, can_edit=False)


@router.callback_query(F.data.startswith("wallets_del_"))
async def wallet_delete(callback: CallbackQuery):
    wallet_id = int(callback.data.replace("wallets_del_", ""))
    telegram_id = callback.from_user.id
    try:
        await api.delete_wallet(telegram_id, wallet_id)
    except Exception as e:
        await callback.answer(str(e))
        return
    await _send_wallets_list(callback.message, telegram_id, can_edit=True)
    await callback.answer(make_wallet_deleted_text())
