"""
Настройка логирования (стандартный logging).
"""
import logging
import sys

from src.core.config import get_settings


def setup_logging() -> None:
    """Настраивает уровень и формат логов."""
    level = logging.INFO
    settings = get_settings()
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    # Снижаем шум от uvicorn/httpx при желании
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
