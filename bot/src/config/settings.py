"""
Конфигурация бота из переменных окружения.
"""
import os
from typing import List


def _get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, default).strip()


def get_admin_telegram_ids() -> List[int]:
    s = _get_env("ADMIN_TELEGRAM_IDS")
    if not s:
        return []
    return [int(x.strip()) for x in s.split(",") if x.strip()]


BOT_TOKEN = _get_env("BOT_TOKEN")
BACKEND_BASE_URL = _get_env("BACKEND_BASE_URL", "http://localhost:8000")
ADMIN_API_KEY = _get_env("ADMIN_API_KEY")
ADMIN_TELEGRAM_IDS = get_admin_telegram_ids()

ALLOWED_CURRENCIES = ("USDT", "USDC")
