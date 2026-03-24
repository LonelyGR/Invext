"""
/start [ref_code] — создание/обновление пользователя, описание проекта, личные данные, меню.
"""
from aiogram import Router
from aiogram.types import Message
from aiogram.filters import CommandStart, CommandObject
from aiogram.utils.deep_linking import create_start_link

from src.api_client.client import api
from src.keyboards.menus import main_menu_kb
from src.config.settings import ADMIN_TELEGRAM_IDS
from src.services.fresh_data import get_user_data
from src.texts import (
    WELCOME_ABOUT,
    format_personal_data,
    make_start_load_error_text,
    make_start_registration_error_text,
)

router = Router(name="start")


async def _send_welcome_flow(message: Message, telegram_id: int):
    """Первое сообщение — о проекте, второе — личные данные и меню."""
    await message.answer(WELCOME_ABOUT)

    try:
        me, balances = await get_user_data(telegram_id)
    except Exception as e:
        await message.answer(
            make_start_load_error_text(e),
            reply_markup=main_menu_kb(telegram_id in ADMIN_TELEGRAM_IDS),
        )
        return

    ref_code = me.get("ref_code", "")
    ref_link = None
    if ref_code:
        try:
            ref_link = await create_start_link(message.bot, ref_code)
        except Exception:
            try:
                ref_link = f"https://t.me/{(await message.bot.get_me()).username}?start={ref_code}"
            except Exception:
                ref_link = None

    personal_text = format_personal_data(me, balances, ref_link=ref_link)
    await message.answer(personal_text, reply_markup=main_menu_kb(telegram_id in ADMIN_TELEGRAM_IDS))


@router.message(CommandStart(deep_link=True))
async def cmd_start_with_ref(message: Message, command: CommandObject):
    """/start ref_code — привязка реферера, описание проекта, личные данные."""
    ref_code = command.args
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
    """/start без реферального кода — описание проекта, личные данные."""
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
