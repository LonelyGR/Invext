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
        await target.answer(f"Ошибка: {e}")
        return
    if not wallets:
        text = (text_prefix + "💼 <b>Ваши кошельки</b>\n\nУ вас нет сохранённых кошельков.").strip()
    else:
        lines = []
        for w in wallets:
            addr = w["address"]
            addr_show = f"{addr[:24]}..." if len(addr) > 24 else addr
            lines.append(f"• {w['name']} ({w['currency']}): <code>{addr_show}</code>")
        text = (text_prefix + "💼 <b>Ваши кошельки</b>\n\n" + "\n".join(lines)).strip()
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


@router.message(F.text == "⚙️ Кошелек")
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
    await callback.message.answer(
        "Введите название для нового кошелька (например: «Мой основной кошелёк»):"
    )
    await callback.answer()


@router.message(AddWalletStates.entering_name, F.text)
async def wallet_name_entered(message: Message, state: FSMContext):
    name = (message.text or "").strip()[:255]
    if not name:
        await message.answer("Название не может быть пустым. Введите название:")
        return
    await state.update_data(wallet_name=name)
    await state.set_state(AddWalletStates.choosing_currency)
    await message.answer(
        "Пожалуйста, выберите валюту в кнопочном меню:",
        reply_markup=wallet_coin_kb(),
    )


@router.callback_query(AddWalletStates.choosing_currency, F.data.startswith("wallet_coin_"))
async def wallet_currency_chosen(callback: CallbackQuery, state: FSMContext):
    currency = callback.data.replace("wallet_coin_", "")
    if currency not in ALLOWED_CURRENCIES:
        await callback.answer("Неверная валюта")
        return
    await state.update_data(wallet_currency=currency)
    await state.set_state(AddWalletStates.entering_address)
    await callback.message.edit_text(
        f"Тип кошелька успешно установлен на {currency}!\n"
        f"Теперь отправьте адрес вашего кошелька для сети {currency}."
    )
    await callback.answer()


@router.callback_query(F.data == "wallets_cancel")
async def wallet_add_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await _send_wallets_list(callback.message, callback.from_user.id, can_edit=True)
    await callback.answer("Отменено")


@router.message(AddWalletStates.entering_address, F.text)
async def wallet_address_entered(message: Message, state: FSMContext):
    address = (message.text or "").strip()
    if not address or len(address) > 512:
        await message.answer("Адрес не может быть пустым и не более 512 символов.")
        return
    data = await state.get_data()
    name = data.get("wallet_name", "")
    currency = data.get("wallet_currency", "USDT")
    telegram_id = message.from_user.id
    try:
        await api.create_wallet(telegram_id, name=name, currency=currency, address=address)
    except Exception as e:
        await message.answer(f"Ошибка при сохранении: {e}")
        await state.clear()
        return
    await state.clear()
    await message.answer(f"✅ Кошелёк «{name}» ({currency}) добавлен.")
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
    await callback.answer("Кошелёк удалён")
