"""
Партнеры: Партнёрская программа (ссылка + уровни), Моя команда.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.deep_linking import create_start_link

from src.api_client.client import api
from src.keyboards.menus import partners_main_kb, partners_team_kb
from src.texts import make_partners_main_text, make_partners_team_text

router = Router(name="partners")

# Проценты по уровням для экрана «Партнёры» (как в логике реф. бонусов по сделкам).
REFERRAL_LEVELS: list[tuple[float, str]] = [(0.5, "") for _ in range(10)]


def _format_partners_invite_text(ref_link: str) -> str:
    """Готовый текст приглашения: ссылка внизу."""
    return (
        "🚀 Присоединяйся к Invext по моей реферальной ссылке.\n\n"
        "Участвуй в инвестиционных сделках, получай прибыль и пользуйся удобным ботом с простым стартом.\n\n"
        f"{ref_link}"
    )


async def _build_ref_link(bot, ref_code: str) -> str | None:
    """Генерирует реферальную ссылку. Возвращает None при ошибке."""
    if not ref_code or ref_code == "—":
        return None
    try:
        return await create_start_link(bot, ref_code)
    except Exception:
        try:
            username = (await bot.get_me()).username
            return f"https://t.me/{username}?start={ref_code}"
        except Exception:
            return None


@router.message(F.text == "👥 Партнёры")
async def partners(message: Message):
    telegram_id = message.from_user.id
    try:
        me = await api.get_me(telegram_id)
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return

    if not me:
        await message.answer("Пользователь временно недоступен. Попробуйте ещё раз через пару секунд.")
        return

    ref_code = me.get("ref_code", "")
    link = await _build_ref_link(message.bot, ref_code)

    text = make_partners_main_text(me, link, REFERRAL_LEVELS)
    await message.answer(text, reply_markup=partners_main_kb(share_url=link))


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

    ref_code = me.get("ref_code", "")
    link = await _build_ref_link(callback.bot, ref_code)

    text = make_partners_main_text(me, link, REFERRAL_LEVELS)
    try:
        await callback.message.edit_text(text, reply_markup=partners_main_kb(share_url=link))
    except Exception:
        await callback.message.answer(text, reply_markup=partners_main_kb(share_url=link))
    await callback.answer()


@router.callback_query(F.data == "partners_invite_text")
async def partners_invite_text(callback: CallbackQuery):
    """Отправляет готовый текст приглашения с реферальной ссылкой внизу (без t.me/share/url)."""
    telegram_id = callback.from_user.id
    try:
        me = await api.get_me(telegram_id)
    except Exception:
        await callback.answer("Ошибка загрузки данных", show_alert=True)
        return
    if not me:
        await callback.answer("Пользователь не найден.", show_alert=True)
        return

    ref_code = me.get("ref_code", "")
    link = await _build_ref_link(callback.bot, ref_code)
    if not link:
        await callback.answer("Не удалось получить реферальную ссылку.", show_alert=True)
        return

    await callback.message.answer(_format_partners_invite_text(link))
    await callback.answer()


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
