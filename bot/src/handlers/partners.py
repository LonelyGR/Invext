"""
Партнеры: Партнёрская программа (ссылка + уровни), Моя команда, Реферальные бонусы.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.deep_linking import create_start_link

from src.api_client.client import api
from src.keyboards.menus import partners_main_kb, partners_team_kb, partners_bonuses_kb

router = Router(name="partners")

# Уровни реферальной программы: (процент, описание)
REFERRAL_LEVELS = [
    (7.00, "1 уровень"),
    (2.00, "2 уровень"),
    (1.00, "3 уровень"),
    (0.50, "4 уровень"),
    (0.50, "5 уровень"),
]


def _get_partners_main_text(me: dict, link: str) -> str:
    """Текст главного экрана «Партнёрская программа»."""
    ref_code = me.get("ref_code", "—")
    level1_count = me.get("referrals_count", 0)
    lines = ["<b>Партнёрская программа</b>\n", f"Ваша реферальная ссылка:\n{link}\n", "Ваша команда:"]
    for i, (pct, _) in enumerate(REFERRAL_LEVELS):
        count = level1_count if i == 0 else 0
        lines.append(f"👥👥 : {count} 💰 {pct:.2f}%")
    return "\n".join(lines)


@router.message(F.text == "👥 Партнеры")
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

    level1 = me.get("referrals_count", 0)
    team_usdt = me.get("team_deposits_usdt", "0") or "0"
    try:
        team_float = float(team_usdt)
    except (TypeError, ValueError):
        team_float = 0

    lines = ["<b>Моя Команда</b>\n"]
    for i in range(5):
        count = level1 if i == 0 else 0
        lines.append(f"◆ {i + 1} уровень: {count} участников")
    lines.append(f"\n💎 Общий оборот команды: {team_float:.2f} USDT")
    lines.append("📅 Последняя активность: нет данных")
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

    referrals = me.get("referrals_count", 0)
    team_usdt = me.get("team_deposits_usdt", "0") or "0"
    try:
        team_float = float(team_usdt)
    except (TypeError, ValueError):
        team_float = 0.0

    text = (
        "🎁 <b>Реферальные бонусы</b>\n\n"
        f"👥 Ваши прямые рефералы: {referrals}\n"
        f"💎 Оборот команды (депозиты): {team_float:.2f} USDT\n\n"
        "Реферальные вознаграждения начисляются за участие вашей команды в сделках.\n"
        "Детальная статистика и история начислений появятся здесь после активации сделок."
    )
    try:
        await callback.message.edit_text(text, reply_markup=partners_bonuses_kb())
    except Exception:
        await callback.message.answer(text, reply_markup=partners_bonuses_kb())
    await callback.answer()
