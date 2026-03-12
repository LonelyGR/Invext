"""
Партнеры: Партнёрская программа (ссылка + уровни), Моя команда, Реферальные бонусы.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.deep_linking import create_start_link

from src.api_client.client import api
from src.keyboards.menus import partners_main_kb, partners_team_kb, partners_bonuses_kb

router = Router(name="partners")

# Уровни реферальной программы: 3 уровня по 3% с депозита
REFERRAL_LEVELS = [
    (3.00, "1 уровень"),
    (3.00, "2 уровень"),
    (3.00, "3 уровень"),
]


def _get_partners_main_text(me: dict, link: str) -> str:
    """Текст главного экрана «Партнёрская программа» с уровнями рефералов."""
    ref_code = me.get("ref_code", "—")
    level1 = me.get("referrals_level_1", 0) or me.get("referrals_count", 0)
    level2 = me.get("referrals_level_2", 0)
    level3 = me.get("referrals_level_3", 0)
    counts = [level1, level2, level3]
    lines = [
        "<b>👥 Партнёрская программа</b>\n",
        f"Ваша реферальная ссылка:\n{link}\n",
        "<b>Уровни рефералов:</b>",
    ]
    for i, (pct, label) in enumerate(REFERRAL_LEVELS):
        count = counts[i] if i < len(counts) else 0
        lines.append(f"  • {label}: {count} чел. — {pct:.0f}% с депозита")
    return "\n".join(lines)


@router.message(F.text == "👥 Рефералы")
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

    text = _get_partners_main_text(me, link)
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
    text = _get_partners_main_text(me, link)
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

    text = (
        "🔗 <b>Ваша реферальная ссылка</b>\n\n"
        f"{link}\n\n"
        "Перешлите это сообщение другу — он откроет бота по вашей ссылке."
    )
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

    level1 = me.get("referrals_level_1", 0) or me.get("referrals_count", 0)
    level2 = me.get("referrals_level_2", 0)
    level3 = me.get("referrals_level_3", 0)
    team_usdt = me.get("team_deposits_usdt", "0") or "0"
    try:
        team_float = float(team_usdt)
    except (TypeError, ValueError):
        team_float = 0

    lines = [
        "<b>📊 Моя команда</b>\n",
        f"◆ 1 уровень: {level1} участников",
        f"◆ 2 уровень: {level2} участников",
        f"◆ 3 уровень: {level3} участников",
        f"\n💎 Оборот команды (депозиты): {team_float:.2f} USDT",
    ]
    text = "\n".join(lines)

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

    level1 = me.get("referrals_level_1", 0) or me.get("referrals_count", 0)
    level2 = me.get("referrals_level_2", 0)
    level3 = me.get("referrals_level_3", 0)
    team_usdt = me.get("team_deposits_usdt", "0") or "0"
    try:
        team_float = float(team_usdt)
    except (TypeError, ValueError):
        team_float = 0.0

    text = (
        "🎁 <b>Реферальные бонусы</b>\n\n"
        f"1 уровень: {level1} чел. — 3% с депозита\n"
        f"2 уровень: {level2} чел. — 3% с депозита\n"
        f"3 уровень: {level3} чел. — 3% с депозита\n\n"
        f"💎 Оборот команды (депозиты): {team_float:.2f} USDT\n\n"
        "Бонус начисляется только с подтверждённого пополнения баланса реферала, "
        "не с инвестиций и не с прибыли по сделкам."
    )
    try:
        await callback.message.edit_text(text, reply_markup=partners_bonuses_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=partners_bonuses_kb())
    await callback.answer()
