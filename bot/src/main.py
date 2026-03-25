"""
Точка входа бота: polling, регистрация роутеров и FSM.
"""
import asyncio
import sys
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode

from src.config.settings import BOT_TOKEN
from src.logging_config import setup_bot_logging
from src.middlewares.anti_abuse import AntiAbuseMiddleware
from src.middlewares.user_sync import UserSyncMiddleware
from src.handlers import (
    start,
    profile,
    wallets,
    deposit,
    withdraw,
    partners,
    stats,
    invest,
    back,
    admin_handlers,
    misc,
    balance,
    fallback,
)

setup_bot_logging()
logger = logging.getLogger(__name__)


def _token_looks_placeholder(token: str) -> bool:
    """Проверка, что токен не похож на плейсхолдер из .env.example."""
    if not token or len(token) < 20:
        return True
    # Реальный токен Telegram: "123456789:AAH..." (цифры:буквы/цифры)
    parts = token.split(":")
    if len(parts) != 2 or not parts[0].isdigit() or len(parts[1]) < 20:
        return True
    if "your-" in token.lower() or "example" in token.lower() or token == "your-telegram-bot-token":
        return True
    return False


async def main() -> None:
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN not set. Add BOT_TOKEN to .env (get token from @BotFather).")
        sys.exit(1)
    if _token_looks_placeholder(BOT_TOKEN):
        logger.error(
            "BOT_TOKEN looks like a placeholder. Replace it in .env with a real token from @BotFather."
        )
        sys.exit(1)

    bot = Bot(
        token=BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Глобальная синхронизация профиля пользователя (idempotent), чтобы не зависеть от /start.
    user_sync = UserSyncMiddleware()
    dp.message.middleware(user_sync)
    dp.callback_query.middleware(user_sync)

    # Глобальная защита от спама/частых кликов.
    anti_abuse = AntiAbuseMiddleware()
    dp.message.middleware(anti_abuse)
    dp.callback_query.middleware(anti_abuse)

    # Роутеры: порядок может иметь значение (более специфичные выше)
    dp.include_router(start.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(profile.router)
    dp.include_router(wallets.router)
    dp.include_router(balance.router)
    dp.include_router(deposit.router)
    dp.include_router(withdraw.router)
    dp.include_router(partners.router)
    dp.include_router(stats.router)
    dp.include_router(invest.router)
    dp.include_router(back.router)
    # Глобальный роутер для игнорирования нетекстовых сообщений.
    dp.include_router(misc.router)
    # Fallback-хендлеры для неизвестных апдейтов (должен идти самым последним).
    dp.include_router(fallback.router)

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
