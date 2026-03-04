"""
Кнопка «Назад» — возврат в главное меню (инлайн и нижняя клавиатура).
"""
from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext

from src.keyboards.menus import main_menu_kb

router = Router(name="back")


@router.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text("Главное меню. Выберите действие:", reply_markup=None)
    except Exception:
        pass
    await callback.message.answer("Выберите действие:", reply_markup=main_menu_kb())
    await callback.answer()


@router.message(F.text == "◀️ Назад")
async def back_to_menu_message(message: Message, state: FSMContext):
    """Нижняя кнопка «Назад» в профиле — возврат к навигационной клавиатуре."""
    await state.clear()
    await message.answer("Главное меню. Выберите действие:", reply_markup=main_menu_kb())
