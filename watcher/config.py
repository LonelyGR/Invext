"""
Конфигурация blockchain watcher из переменных окружения.
RPC и контракт — вынесены в env для возможности замены провайдера без смены кода.
"""
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


class WatcherSettings(BaseSettings):
    """Настройки watcher: RPC, сеть, контракт USDT, подтверждения."""

    database_url: str = Field(..., alias="DATABASE_URL")
    rpc_url: str = Field(..., alias="RPC_URL")
    chain_id: int = Field(..., alias="CHAIN_ID")
    usdt_contract_address: str = Field(..., alias="USDT_CONTRACT_ADDRESS")
    confirmations: int = Field(default=12, alias="DEPOSIT_CONFIRMATIONS")
    poll_interval_seconds: int = Field(default=15, alias="WATCHER_POLL_INTERVAL_SECONDS")
    # Макс. блоков за один eth_getLogs — чтобы не упираться в лимит RPC (limit exceeded). Публичный BSC часто принимает только 1.
    block_chunk_size: int = Field(default=1, alias="WATCHER_BLOCK_CHUNK_SIZE")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = {"env_file": ".env", "extra": "ignore"}

    @property
    def usdt_contract_address_normalized(self) -> str:
        s = (self.usdt_contract_address or "").strip().lower()
        return s if s.startswith("0x") else "0x" + s


@lru_cache
def get_watcher_settings() -> WatcherSettings:
    return WatcherSettings()
