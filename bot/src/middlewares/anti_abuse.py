"""
Anti-abuse / anti-spam middleware for the Telegram bot.

- Rate limit per user for any action (messages + callbacks).
- Simple spam detection by burst of messages.
- Cooldown for financial operations (deposit, withdraw, invest).
"""
from __future__ import annotations

import time
import logging
from typing import Any, Callable, Dict, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject


logger = logging.getLogger(__name__)


class AntiAbuseMiddleware(BaseMiddleware):
    def __init__(
        self,
        *,
        min_action_interval_sec: float = 1.0,
        spam_window_sec: float = 3.0,
        spam_threshold: int = 10,
        spam_block_sec: float = 7.0,
        financial_cooldown_sec: float = 4.0,
    ) -> None:
        super().__init__()
        self.min_action_interval_sec = min_action_interval_sec
        self.spam_window_sec = spam_window_sec
        self.spam_threshold = spam_threshold
        self.spam_block_sec = spam_block_sec
        self.financial_cooldown_sec = financial_cooldown_sec

        # state per user
        self._last_action_ts: Dict[int, float] = {}
        self._spam_state: Dict[int, tuple[float, int]] = {}  # user_id -> (window_start, count)
        self._blocked_until: Dict[int, float] = {}
        self._last_financial_ts: Dict[int, float] = {}

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        user_id = self._get_user_id(event)
        if not user_id:
            return await handler(event, data)

        now = time.monotonic()

        # 1) Если пользователь временно заблокирован за спам — игнорируем всё без ответов.
        blocked_until = self._blocked_until.get(user_id, 0)
        if blocked_until and now < blocked_until:
            return

        # 2) Общий rate-limit: не более 1 действия в min_action_interval_sec.
        last_ts = self._last_action_ts.get(user_id, 0)
        if now - last_ts < self.min_action_interval_sec:
            # Отвечаем пользователю и логируем.
            await self._send_rate_limit_warning(event)
            logger.warning("rate limit triggered user %s", user_id)
            return

        self._last_action_ts[user_id] = now

        # 3) Spam detection по количеству сообщений/действий в коротком окне.
        win_start, count = self._spam_state.get(user_id, (now, 0))
        if now - win_start > self.spam_window_sec:
            # новое окно
            win_start, count = now, 1
        else:
            count += 1
        self._spam_state[user_id] = (win_start, count)

        if count > self.spam_threshold:
            # Временно блокируем пользователя.
            self._blocked_until[user_id] = now + self.spam_block_sec
            logger.warning("spam detected user %s", user_id)
            return

        # 4) Cooldown для финансовых операций.
        if self._is_financial_action(event):
            last_financial = self._last_financial_ts.get(user_id, 0)
            if now - last_financial < self.financial_cooldown_sec:
                await self._send_rate_limit_warning(event)
                logger.warning("financial cooldown triggered user %s", user_id)
                return
            self._last_financial_ts[user_id] = now

        return await handler(event, data)

    @staticmethod
    def _get_user_id(event: TelegramObject) -> int | None:
        if isinstance(event, Message) and event.from_user:
            return event.from_user.id
        if isinstance(event, CallbackQuery) and event.from_user:
            return event.from_user.id
        return None

    @staticmethod
    def _is_financial_action(event: TelegramObject) -> bool:
        # Простая эвристика по текстам/callback_data.
        if isinstance(event, Message) and event.text:
            txt = event.text
            if txt.startswith(("📥 Пополнить", "📤 Вывести", "📈 Сделка")):
                return True
        if isinstance(event, CallbackQuery) and event.data:
            data = event.data
            if data.startswith(("check_invoice_", "deposit_history", "withdraw_", "admin_w_approve_", "admin_w_reject_")):
                return True
        return False

    @staticmethod
    async def _send_rate_limit_warning(event: TelegramObject) -> None:
        msg = "⚠️ Слишком много запросов. Подождите несколько секунд."
        if isinstance(event, Message):
            await event.answer(msg)
        elif isinstance(event, CallbackQuery):
            await event.answer(msg, show_alert=True)

