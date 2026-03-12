"""
Прочие обработчики: глобальное игнорирование всех нетекстовых сообщений.

Цель:
- Любые voice/photo/video/document/sticker/audio и т.п. не должны ломать FSM/хендлеры.
- Бот не отвечает на такие сообщения и не пытается их обрабатывать.
"""
from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

router = Router(name="misc")


@router.message(~F.text)
async def ignore_non_text_messages(message: Message, state: FSMContext) -> None:
    """
    Глобальный обработчик для всех нетекстовых сообщений во всех состояниях.

    Ничего не делает и ничего не отправляет пользователю.
    Оставлен пустым намеренно, чтобы не ломать существующую логику.
    """
    # Просто игнорируем любые нетекстовые сообщения.
    return

