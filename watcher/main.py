"""
Blockchain Watcher: опрос RPC на события Transfer контракта USDT,
фильтрация по нашим депозитным адресам, ожидание N подтверждений и зачисление через ledger.
Запуск отдельно от backend; использует общую БД и модели (PYTHONPATH=backend).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Подключение коду backend (Docker: PYTHONPATH=/app/backend; локально: backend рядом с watcher)
_backend = Path(__file__).resolve().parent.parent / "backend"
if _backend.exists() and str(_backend) not in sys.path:
    sys.path.append(str(_backend))

from web3 import Web3
from web3.types import FilterParams

from src.db.session import async_session_maker
from src.models.watcher_cursor import WatcherCursor
from event_processor import (
    get_or_init_cursor,
    update_cursor,
    process_transfer_log,
    TRANSFER_TOPIC,
)
from config import get_watcher_settings

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def get_transfer_logs(w3: Web3, usdt_contract: str, from_block: int, to_block: int) -> list | None:
    """Получить логи Transfer контракта USDT за диапазон блоков. При ошибке RPC возвращает None (не продвигаем курсор)."""
    if from_block > to_block:
        return []
    filter_params: FilterParams = {
        "address": Web3.to_checksum_address(usdt_contract),
        "fromBlock": from_block,
        "toBlock": to_block,
        "topics": [TRANSFER_TOPIC],
    }
    try:
        logs = w3.eth.get_logs(filter_params)
        return list(logs)
    except Exception as e:
        logger.warning("get_logs failed from_block=%s to_block=%s: %s", from_block, to_block, e)
        return None


async def run_cycle(w3: Web3, settings) -> None:
    """Один цикл: прочитать курсор, запрашивать блоки чанками (чтобы не превышать лимит RPC), обработать логи, обновить курсор."""
    async with async_session_maker() as db:
        try:
            current_block = w3.eth.block_number
            safe_block = current_block - settings.confirmations
            if safe_block < 0:
                safe_block = 0

            last = await get_or_init_cursor(db, settings.chain_id, safe_block)
            from_block = last + 1
            to_block = safe_block

            if from_block > to_block:
                return

            chunk_size = max(1, getattr(settings, "block_chunk_size", 1))
            usdt_norm = settings.usdt_contract_address_normalized
            total_events = 0
            cursor = from_block

            while cursor <= to_block:
                chunk_end = min(cursor + chunk_size - 1, to_block)
                logs = get_transfer_logs(w3, usdt_norm, cursor, chunk_end)
                if logs is None:
                    # Ошибка RPC (limit exceeded и т.д.) — не продвигаем курсор, повторим в следующем цикле
                    break
                for log in logs:
                    try:
                        await process_transfer_log(
                            db,
                            log,
                            settings.chain_id,
                            usdt_norm,
                            settings.confirmations,
                            current_block,
                        )
                        total_events += 1
                    except Exception as e:
                        logger.exception("Process log failed: %s", e)
                await update_cursor(db, settings.chain_id, chunk_end)
                cursor = chunk_end + 1
                if cursor <= to_block:
                    await asyncio.sleep(0.5)

            await db.commit()
            if total_events:
                logger.info("Processed block range %s-%s, events=%s", from_block, to_block, total_events)
        except Exception as e:
            await db.rollback()
            logger.exception("Watcher cycle failed: %s", e)
            raise


async def main_loop() -> None:
    settings = get_watcher_settings()
    w3 = Web3(Web3.HTTPProvider(settings.rpc_url))
    if not w3.is_connected():
        raise RuntimeError("Cannot connect to RPC: %s", settings.rpc_url)
    logger.info("Watcher started: chain_id=%s, confirmations=%s", settings.chain_id, settings.confirmations)

    while True:
        try:
            await run_cycle(w3, settings)
        except Exception as e:
            logger.exception("Cycle error: %s", e)
        await asyncio.sleep(settings.poll_interval_seconds)


if __name__ == "__main__":
    asyncio.run(main_loop())
