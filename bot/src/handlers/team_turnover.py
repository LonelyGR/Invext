"""
Оборот команды: оборот по линиям, общий оборот, Обновить данные, Подробная статистика.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from src.api_client.client import api
from src.keyboards.menus import turnover_main_kb, turnover_detail_kb
from src.texts import (
    make_team_turnover_main_text,
    make_team_turnover_detail_text,
)

router = Router(name="team_turnover")


async def _send_turnover_main(chat_id: int, bot, edit_message=None):
    """Загрузить данные и отправить/редактировать главный экран оборота."""
    try:
        me = await api.get_me(chat_id)
    except Exception as e:
        if edit_message:
            await edit_message.edit_text(f"Ошибка: {e}")
        else:
            await bot.send_message(chat_id, f"Ошибка: {e}")
        return
    if not me:
        text = "Пользователь не найден. Отправьте /start."
        if edit_message:
            await edit_message.edit_text(text)
        else:
            await bot.send_message(chat_id, text)
        return
    text = make_team_turnover_main_text(me)
    if edit_message:
        try:
            await edit_message.edit_text(text, reply_markup=turnover_main_kb())
        except Exception:
            await edit_message.answer(text, reply_markup=turnover_main_kb())
    else:
        await bot.send_message(chat_id, text, reply_markup=turnover_main_kb())


@router.message(F.text == "📊 Оборот команды")
async def team_turnover(message: Message):
    telegram_id = message.from_user.id
    try:
        me = await api.get_me(telegram_id)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return
    if not me:
        await message.answer("Пользователь не найден. Отправьте /start.")
        return
    text = make_team_turnover_main_text(me)
    await message.answer(text, reply_markup=turnover_main_kb())


@router.callback_query(F.data == "turnover_update")
async def turnover_update(callback: CallbackQuery):
    """Обновить данные — перезагрузить и показать главный экран оборота."""
    await _send_turnover_main(callback.from_user.id, callback.bot, callback.message)
    await callback.answer("Данные обновлены")


@router.callback_query(F.data == "turnover_detail")
async def turnover_detail(callback: CallbackQuery):
    """Подробная статистика команды."""
    telegram_id = callback.from_user.id
    try:
        me = await api.get_me(telegram_id)
    except Exception as e:
        await callback.answer(str(e))
        return
    if not me:
        await callback.answer("Пользователь не найден.")
        return
    text = make_team_turnover_detail_text(me)
    try:
        await callback.message.edit_text(text, reply_markup=turnover_detail_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=turnover_detail_kb())
    await callback.answer()


@router.callback_query(F.data == "turnover_total")
async def turnover_total(callback: CallbackQuery):
    """Общий оборот — вернуться на главный экран оборота."""
    await _send_turnover_main(callback.from_user.id, callback.bot, callback.message)
    await callback.answer()
