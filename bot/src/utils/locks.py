"""
Простые in-memory блокировки для защиты от double-click по финансовым операциям.

Ограничение: работает в рамках одного процесса бота (что достаточно для текущего развёртывания).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Tuple

from aiogram.types import Message, CallbackQuery

# Ключ: (user_id, operation), значение: asyncio.Lock
_locks: Dict[Tuple[int, str], asyncio.Lock] = {}


def _get_lock(user_id: int, operation: str) -> asyncio.Lock:
    key = (user_id, operation)
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


@asynccontextmanager
async def user_operation_lock(user_id: int, operation: str):
    """
    Асинхронный контекст для защиты от повторного нажатия.

    Пример:
        async with user_operation_lock(user_id, "invest"):
            ... безопасная секция ...
    """
    lock = _get_lock(user_id, operation)
    acquired = await lock.acquire()
    if not acquired:
        # Непредвиденный случай, но на всякий случай просто выходим.
        yield False
        return
    try:
        yield True
    finally:
        lock.release()


async def with_double_click_protection(
    source: Message | CallbackQuery,
    operation: str,
):
    """
    Обёртка: пытается взять лок, иначе отправляет пользователю сообщение о том,
    что операция уже обрабатывается. Возвращает True, если можно продолжать.
    """
    user_id = (
        source.from_user.id
        if isinstance(source, (Message, CallbackQuery)) and source.from_user
        else 0
    )
    lock = _get_lock(user_id, operation)
    if lock.locked():
        # Уже выполняется операция для этого пользователя.
        if isinstance(source, Message):
            await source.answer("⏳ Подождите, операция уже обрабатывается.")
        else:
            await source.answer("⏳ Подождите, операция уже обрабатывается.", show_alert=True)
        return False

    await lock.acquire()
    return True


async def release_double_click_lock(user_id: int, operation: str) -> None:
    """Явное освобождение лока (на случай сложных сценариев)."""
    key = (user_id, operation)
    lock = _locks.get(key)
    if lock and lock.locked():
        lock.release()

