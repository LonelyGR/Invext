"""
Точка входа бота: polling, регистрация роутеров и FSM.
"""
import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode

from src.config.settings import BOT_TOKEN
from src.handlers import (
    start,
    profile,
    wallets,
    deposit,
    withdraw,
    partners,
    team_turnover,
    stats,
    invest,
    back,
    admin_handlers,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    stream=sys.stdout,
)
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

    # Роутеры: порядок может иметь значение (более специфичные выше)
    dp.include_router(start.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(profile.router)
    dp.include_router(wallets.router)
    dp.include_router(deposit.router)
    dp.include_router(withdraw.router)
    dp.include_router(partners.router)
    dp.include_router(team_turnover.router)
    dp.include_router(stats.router)
    dp.include_router(invest.router)
    dp.include_router(back.router)

    logger.info("Bot starting...")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
