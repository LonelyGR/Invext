"""
Партнеры: Партнёрская программа (ссылка + уровни), Моя команда, Реферальные бонусы.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.deep_linking import create_start_link

from src.api_client.client import api
from src.keyboards.menus import partners_main_kb, partners_team_kb, partners_bonuses_kb
from src.texts import (
    make_partners_main_text,
    make_partners_share_link_text,
    make_partners_team_text,
    make_partners_bonuses_text,
)

router = Router(name="partners")

# Уровни реферальной программы:
# - Депозиты: 1 уровень — 3%
# - Инвестиции: 1–3 уровни — по 0.5% при участии в сделке
REFERRAL_LEVELS = [
    (3.00, "1 уровень (депозиты)"),
    (0.5, "2 уровень (инвестиции)"),
    (0.5, "3 уровень (инвестиции)"),
]


@router.message(F.text == "👥 Партнёры")
async def partners(message: Message):
    telegram_id = message.from_user.id
    try:
        me = await api.get_me(telegram_id)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return

    if not me:
        await message.answer("Пользователь не найден. Отправьте /start.")
        return

    ref_code = me.get("ref_code", "—")
    try:
        link = await create_start_link(message.bot, ref_code)
    except Exception:
        link = f"https://t.me/{(await message.bot.get_me()).username}?start={ref_code}"

    text = make_partners_main_text(me, link, REFERRAL_LEVELS)
    await message.answer(text, reply_markup=partners_main_kb())


@router.callback_query(F.data == "partners_back")
async def partners_back(callback: CallbackQuery):
    """Назад из подраздела в главный экран Партнёры."""
    telegram_id = callback.from_user.id
    try:
        me = await api.get_me(telegram_id)
    except Exception:
        await callback.answer("Ошибка загрузки данных")
        return
    if not me:
        await callback.answer("Пользователь не найден.")
        return
    ref_code = me.get("ref_code", "—")
    try:
        link = await create_start_link(callback.bot, ref_code)
    except Exception:
        link = f"https://t.me/{(await callback.bot.get_me()).username}?start={ref_code}"
    text = make_partners_main_text(me, link, REFERRAL_LEVELS)
    try:
        await callback.message.edit_text(text, reply_markup=partners_main_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=partners_main_kb())
    await callback.answer()


@router.callback_query(F.data == "partners_share_link")
async def partners_share_link(callback: CallbackQuery):
    """Отправить отдельным сообщением реферальную ссылку — удобно переслать в один клик."""
    telegram_id = callback.from_user.id
    try:
        me = await api.get_me(telegram_id)
    except Exception:
        await callback.answer("Ошибка загрузки данных")
        return
    if not me:
        await callback.answer("Пользователь не найден.")
        return

    ref_code = me.get("ref_code", "—")
    try:
        link = await create_start_link(callback.bot, ref_code)
    except Exception:
        link = f"https://t.me/{(await callback.bot.get_me()).username}?start={ref_code}"

    text = make_partners_share_link_text(link)
    await callback.message.answer(text)
    await callback.answer("Ссылку можно переслать дальше")


@router.callback_query(F.data == "partners_team")
async def partners_team(callback: CallbackQuery):
    """Экран «Моя команда»: уровни, оборот, последняя активность."""
    telegram_id = callback.from_user.id
    try:
        me = await api.get_me(telegram_id)
    except Exception as e:
        await callback.answer(str(e))
        return
    if not me:
        await callback.answer("Пользователь не найден.")
        return

    text = make_partners_team_text(me)

    try:
        await callback.message.edit_text(text, reply_markup=partners_team_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=partners_team_kb())
    await callback.answer()


@router.callback_query(F.data == "partners_bonuses")
async def partners_bonuses(callback: CallbackQuery):
    """Экран «Реферальные бонусы»."""
    telegram_id = callback.from_user.id
    try:
        me = await api.get_me(telegram_id)
    except Exception as e:
        await callback.answer(str(e))
        return
    if not me:
        await callback.answer("Пользователь не найден.")
        return

    text = make_partners_bonuses_text(me)
    try:
        await callback.message.edit_text(text, reply_markup=partners_bonuses_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=partners_bonuses_kb())
    await callback.answer()
