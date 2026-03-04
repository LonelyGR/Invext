"""
Оборот команды: оборот по линиям, общий оборот, Обновить данные, Подробная статистика.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from src.api_client.client import api
from src.keyboards.menus import turnover_main_kb, turnover_detail_kb

router = Router(name="team_turnover")


def _format_turnover_main(me: dict) -> str:
    """Текст главного экрана «Оборот команды»."""
    usdt = me.get("team_deposits_usdt", "0") or "0"
    usdc = me.get("team_deposits_usdc", "0") or "0"
    try:
        total = float(usdt) + float(usdc)
    except (TypeError, ValueError):
        total = 0
    return (
        "📊 <b>Оборот команды</b>\n\n"
        "Оборот по линиям:\n"
        f"🔷 Общий оборот команды: {total:.2f} USDT"
    )


def _format_turnover_detail(me: dict) -> str:
    """Текст экрана «Подробная статистика команды» (оборот по уровням)."""
    usdt = me.get("team_deposits_usdt", "0") or "0"
    usdc = me.get("team_deposits_usdc", "0") or "0"
    ref_count = me.get("referrals_count", 0)
    try:
        usdt_f = float(usdt)
        usdc_f = float(usdc)
    except (TypeError, ValueError):
        usdt_f = usdc_f = 0
    return (
        "📈 <b>Подробная статистика команды</b>\n\n"
        "Оборот по линиям (депозиты рефералов):\n"
        f"◆ 1 уровень: {ref_count} уч. — USDT {usdt_f:.2f}, USDC {usdc_f:.2f}\n"
        "◆ 2 уровень: 0 уч. — USDT 0.00, USDC 0.00\n"
        "◆ 3 уровень: 0 уч. — USDT 0.00, USDC 0.00\n"
        "◆ 4 уровень: 0 уч. — USDT 0.00, USDC 0.00\n"
        "◆ 5 уровень: 0 уч. — USDT 0.00, USDC 0.00"
    )


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
    text = _format_turnover_main(me)
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
    text = _format_turnover_main(me)
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
    text = _format_turnover_detail(me)
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
