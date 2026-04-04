"""
ссылка на наш чат
"""
from decimal import Decimal, InvalidOperation

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.api_client.client import api
from src.keyboards.menus import main_menu_kb

import logging

router = Router(name="chat")
logger = logging.getLogger(__name__)




def _chat_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💬 Наш Чат", url="https://t.me/invextclub")],
        ]
    )


@router.message(F.text == "💬 Наш Чат")
async def chat(message: Message):
    await message.answer("Чат Invext - общение, поддержка и обновления в реальном времени", reply_markup=_chat_kb())

