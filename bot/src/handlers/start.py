"""
/start [ref_code] — создание/обновление пользователя, приветствие о проекте и меню.
"""
import asyncio

from aiogram import Router
from aiogram.types import Message
from aiogram.filters import CommandStart, CommandObject
from aiogram.utils.deep_linking import decode_payload

from src.api_client.client import api
from src.keyboards.menus import main_menu_kb
from src.config.settings import ADMIN_TELEGRAM_IDS
from src.texts import (
    make_welcome_about_text,
    make_start_registration_error_text,
)

router = Router(name="start")


async def _send_welcome_flow(message: Message, telegram_id: int):
    """Одно сообщение — о проекте и нижнее меню (без дублирующего блока профиля)."""
    show_bonus = False
    settings: dict = {}
    try:
        bonus_status, settings_data = await asyncio.gather(
            api.get_welcome_bonus_status(telegram_id),
            api.get_system_settings(),
        )
        show_bonus = bool(bonus_status.get("available"))
        settings = settings_data or {}
    except Exception:
        show_bonus = False
        settings = {}

    await message.answer(
        make_welcome_about_text(settings),
        reply_markup=main_menu_kb(telegram_id in ADMIN_TELEGRAM_IDS, show_welcome_bonus=show_bonus),
    )


@router.message(CommandStart(deep_link=True))
async def cmd_start_with_ref(message: Message, command: CommandObject):
    """/start ref_code — привязка реферера и приветствие."""
    ref_code_raw = (command.args or "").strip()
    # Aiogram deep links are commonly base64-encoded by create_start_link();
    # decode defensively and fallback to raw args if decoding fails.
    try:
        ref_code = decode_payload(ref_code_raw)
    except Exception:
        ref_code = ref_code_raw
    telegram_id = message.from_user.id
    username = message.from_user.username
    name = message.from_user.full_name or message.from_user.username

    try:
        await api.telegram_auth(
            telegram_id=telegram_id,
            username=username,
            name=name,
            ref_code_from_start=ref_code,
        )
    except Exception as e:
        await message.answer(make_start_registration_error_text(e))
        return

    await _send_welcome_flow(message, telegram_id)


@router.message(CommandStart())
async def cmd_start(message: Message):
    """/start без реферального кода — приветствие."""
    telegram_id = message.from_user.id
    username = message.from_user.username
    name = message.from_user.full_name or message.from_user.username

    try:
        await api.telegram_auth(
            telegram_id=telegram_id,
            username=username,
            name=name,
            ref_code_from_start=None,
        )
    except Exception as e:
        await message.answer(make_start_registration_error_text(e))
        return

    await _send_welcome_flow(message, telegram_id)
