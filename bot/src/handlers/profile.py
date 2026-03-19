"""
Профиль: личные данные, редактирование имени/email/страны, переход в Кошельки.
"""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.deep_linking import create_start_link

from src.api_client.client import api
from src.keyboards.menus import profile_kb, profile_reply_kb
from src.texts import make_profile_text

router = Router(name="profile")


class ProfileEditStates(StatesGroup):
    waiting_value = State()


@router.message(F.text == "👤 Профиль")
async def profile(message: Message):
    telegram_id = message.from_user.id
    try:
        me = await api.get_me(telegram_id)
        balances = await api.get_balances(telegram_id)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return
    if not me:
        await message.answer("Пользователь не найден. Отправьте /start.")
        return

    ref_code = me.get("ref_code", "—")
    try:
        ref_link = await create_start_link(message.bot, ref_code)
    except Exception:
        ref_link = f"https://t.me/{(await message.bot.get_me()).username}?start={ref_code}"

    usdt = balances.get("USDT", 0)
    text = make_profile_text(me, usdt, ref_link=ref_link)
    await message.answer(text, reply_markup=profile_reply_kb())


@router.message(F.text == "✏️ Редактировать имя")
async def profile_edit_name_start(message: Message, state: FSMContext):
    await state.set_state(ProfileEditStates.waiting_value)
    await state.update_data(edit_field="name")
    await message.answer("Введите новое имя:")


@router.message(F.text == "✏️ Редактировать email")
async def profile_edit_email_start(message: Message, state: FSMContext):
    await state.set_state(ProfileEditStates.waiting_value)
    await state.update_data(edit_field="email")
    await message.answer("Введите новый email:")


@router.message(F.text == "✏️ Редактировать страну")
async def profile_edit_country_start(message: Message, state: FSMContext):
    await state.set_state(ProfileEditStates.waiting_value)
    await state.update_data(edit_field="country")
    await message.answer("Введите страну:")


@router.message(ProfileEditStates.waiting_value, F.text)
async def profile_edit_value(message: Message, state: FSMContext):
    data = await state.get_data()
    field = data.get("edit_field")
    if not field:
        await state.clear()
        return
    value = (message.text or "").strip()[:255]
    telegram_id = message.from_user.id
    try:
        kwargs = {field: value if value else None}
        await api.update_me(telegram_id, **kwargs)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        await state.clear()
        return
    await state.clear()
    try:
        me = await api.get_me(telegram_id)
        balances = await api.get_balances(telegram_id)
    except Exception:
        me = {}
        balances = {"USDT": 0, "USDC": 0}
    if me:
        ref_code = me.get("ref_code", "—")
        try:
            ref_link = await create_start_link(message.bot, ref_code)
        except Exception:
            ref_link = f"https://t.me/{(await message.bot.get_me()).username}?start={ref_code}"

        text = make_profile_text(
            me,
            balances.get("USDT", 0),
            ref_link=ref_link,
        )
        await message.answer("Данные обновлены.\n\n" + text, reply_markup=profile_reply_kb())
    else:
        await message.answer("Данные обновлены.", reply_markup=profile_reply_kb())
