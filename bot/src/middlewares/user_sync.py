"""
Глобальная синхронизация пользователя на каждый апдейт.

Убирает скрытую зависимость от /start:
- при любом message/callback делает idempotent telegram_auth;
- обновляет username/name, если они изменились;
- не вмешивается в бизнес-логику хендлеров при ошибке backend.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from src.api_client.client import api

logger = logging.getLogger(__name__)


class UserSyncMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = self._extract_user(event)
        if user is not None:
            try:
                await api.telegram_auth(
                    telegram_id=user.id,
                    username=user.username,
                    name=user.full_name or user.username,
                    ref_code_from_start=None,
                )
            except Exception as e:
                # Не блокируем пользовательский flow из-за временного сбоя синхронизации.
                logger.warning("user sync failed for telegram_id=%s: %s", user.id, e)
        return await handler(event, data)

    @staticmethod
    def _extract_user(event: TelegramObject):
        if isinstance(event, Message):
            return event.from_user
        if isinstance(event, CallbackQuery):
            return event.from_user
        return None
