"""
Партнеры: Партнёрская программа (ссылка + уровни), inline-поделиться ссылкой.
"""
from aiogram import Bot, F, Router
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent, Message

from aiogram.utils.deep_linking import create_start_link

from src.api_client.client import api
from src.keyboards.menus import partners_main_kb
from src.texts import make_partners_main_text

router = Router(name="partners")

# Проценты по уровням для экрана «Партнёры» (как в логике реф. бонусов по сделкам).
REFERRAL_LEVELS: list[tuple[float, str]] = [(0.5, "") for _ in range(10)]

# Запас, если create_start_link / username недоступны (совпадает с публичным ботом).
_FALLBACK_REF_BOT = "invext_bot"


async def _build_ref_link(bot: Bot, ref_code: str) -> str | None:
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


def _invite_message_text(ref_link: str) -> str:
    return (
        "🚀 Присоединяйся к Invext по моей реферальной ссылке.\n\n"
        "Участвуй в инвестиционных сделках, получай прибыль по расписанию и пользуйся удобным ботом с простым стартом.\n\n"
        f"{ref_link}"
    )


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
    await message.answer(text, reply_markup=partners_main_kb(ref_code=ref_code or None))


@router.inline_query()
async def partners_inline(inline_query: InlineQuery, bot: Bot):
    ref_code = (inline_query.query or "").strip()
    if not ref_code:
        await inline_query.answer([], cache_time=0, is_personal=True)
        return

    link = await _build_ref_link(bot, ref_code)
    if not link:
        link = f"https://t.me/{_FALLBACK_REF_BOT}?start={ref_code}"

    message_text = _invite_message_text(link)
    result_id = f"invite_{ref_code}"[:64]
    result = InlineQueryResultArticle(
        id=result_id,
        title="Invext — поделиться ссылкой",
        description="Отправить приглашение с вашей реферальной ссылкой",
        input_message_content=InputTextMessageContent(message_text=message_text),
    )
    await inline_query.answer([result], cache_time=0, is_personal=True)
