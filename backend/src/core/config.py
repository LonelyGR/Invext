"""
Конфигурация приложения из переменных окружения.
"""
from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Настройки из .env."""

    project_name: str = Field(default="Invext", alias="PROJECT_NAME")
    database_url: str = Field(..., alias="DATABASE_URL")
    backend_host: str = Field(default="0.0.0.0", alias="BACKEND_HOST")
    backend_port: int = Field(default=8000, alias="BACKEND_PORT")

    # Старый ключ для админ-API (бот)
    admin_api_key: str = Field(..., alias="ADMIN_API_KEY")
    # Список telegram_id админов через запятую
    admin_telegram_ids_str: str = Field(default="", alias="ADMIN_TELEGRAM_IDS")
    min_deposit: float = Field(default=1.0, alias="MIN_DEPOSIT")
    max_deposit: float = Field(default=100_000.0, alias="MAX_DEPOSIT")
    min_withdraw: float = Field(default=1.0, alias="MIN_WITHDRAW")
    max_withdraw: float = Field(default=100_000.0, alias="MAX_WITHDRAW")

    # --- Bot integration (for notifications from backend) ---
    bot_token: str = Field(..., alias="BOT_TOKEN")

    # --- Crypto Pay (invoice-based deposits) ---
    crypto_pay_token: str = Field(..., alias="CRYPTO_PAY_TOKEN")
    app_url: str = Field(..., alias="APP_URL")

    # --- Admin dashboard /database ---
    admin_jwt_secret: str = Field(..., alias="ADMIN_JWT_SECRET")
    admin_allowed_ips: str = Field(
        default="",
        alias="ADMIN_ALLOWED_IPS",
        description="Список IP через запятую, которым разрешён доступ к /database/api. Если пусто — без ограничения.",
    )

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def admin_telegram_ids(self) -> List[int]:
        """Список telegram_id админов."""
        if not self.admin_telegram_ids_str.strip():
            return []
        return [int(x.strip()) for x in self.admin_telegram_ids_str.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
