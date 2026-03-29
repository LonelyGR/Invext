from urllib.parse import quote

from aiogram import Router, F
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery

from src.api_client.client import api

router = Router(name="support")

SUPPORT_TEMPLATES = {
    "support_deposit": (
        "Здравствуйте. У меня возникла проблема с пополнением в Invext.\n\n"
        "Мой ID: {user_id}\n"
        "Username: {username}\n\n"
        "Кратко опишу ситуацию:"
    ),
    "support_withdraw": (
        "Здравствуйте. Нужна помощь по выводу средств в Invext.\n\n"
        "При выводе с баланса удерживается комиссия 10% от суммы заявки; "
        "на кошелёк отправляется 90%.\n\n"
        "Мой ID: {user_id}\n"
        "Username: {username}\n\n"
        "Опишу проблему подробнее:"
    ),
    "support_deals": (
        "Здравствуйте. У меня вопрос по сделке в Invext.\n\n"
        "Мой ID: {user_id}\n"
        "Username: {username}\n\n"
        "Номер сделки, если есть:\n"
        "Что произошло:"
    ),
    "support_other": (
        "Здравствуйте. Нужна помощь по Invext.\n\n"
        "Мой ID: {user_id}\n"
        "Username: {username}\n\n"
        "Суть вопроса:"
    ),
}


def _support_username(raw: str | None) -> str | None:
    value = (raw or "").strip()
    if not value:
        return None
    if value.startswith("@"):
        username = value[1:].strip()
        if username:
            return username
    cleaned = value.replace("https://", "").replace("http://", "").strip("/")
    if cleaned.startswith("t.me/"):
        username = cleaned.split("/", 1)[1].strip()
        if username:
            return username
    if cleaned:
        return cleaned
    return None


def _support_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💰 Пополнение", callback_data="support_deposit")],
            [InlineKeyboardButton(text="💸 Вывод", callback_data="support_withdraw")],
            [InlineKeyboardButton(text="📊 Сделки", callback_data="support_deals")],
            [InlineKeyboardButton(text="⚙️ Другое", callback_data="support_other")],
        ]
    )


@router.message(F.text == "🆘 Саппорт")
async def support_entry(message: Message):
    await message.answer(
        "🆘 Саппорт\n\nВыберите категорию вашего вопроса:",
        reply_markup=_support_menu_kb(),
    )


@router.callback_query(F.data.in_(set(SUPPORT_TEMPLATES.keys())))
async def support_category_selected(callback: CallbackQuery):
    template = SUPPORT_TEMPLATES.get(callback.data or "")
    if not template:
        await callback.answer("Неизвестная категория", show_alert=True)
        return

    try:
        settings = await api.get_system_settings()
        username = _support_username(settings.get("support_contact"))
    except Exception:
        username = None

    if not username:
        await callback.message.edit_text("🆘 Саппорт\n\nСаппорт временно недоступен. Попробуйте позже.")
        await callback.answer()
        return

    tg_username = callback.from_user.username or "нет username"
    text = template.format(user_id=callback.from_user.id, username=f"@{tg_username}" if tg_username != "нет username" else tg_username)
    encoded = quote(text)
    url = f"https://t.me/{username}?text={encoded}"
    kb = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="Открыть чат", url=url)]]
    )
    await callback.message.edit_text(
        "Нажмите кнопку ниже, чтобы написать в поддержку",
        reply_markup=kb,
    )
    await callback.answer()
