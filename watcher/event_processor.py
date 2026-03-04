"""
Обработка события Transfer контракта USDT: проверка контракта, сохранение в blockchain_events,
зачисление на баланс через ledger (идемпотентно).
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from web3 import Web3
from web3.types import LogReceipt

from src.models.blockchain_event import BlockchainEvent
from src.models.deposit_address import DepositAddress
from src.models.watcher_cursor import WatcherCursor
from src.services.ledger_service import try_record_blockchain_deposit

logger = logging.getLogger(__name__)

# ERC20 Transfer(address indexed from, address indexed to, uint256 value)
TRANSFER_TOPIC = Web3.keccak(text="Transfer(address,address,uint256)").hex()
USDT_DECIMALS = 6


def parse_transfer_log(log: LogReceipt) -> tuple[str, str, str, int]:
    """
    Извлечь from, to, value из лога Transfer.
    :return: (from_address, to_address, value_raw, log_index)
    """
    topics = log.get("topics") or []
    if len(topics) < 3:
        raise ValueError("Invalid Transfer log: not enough topics")
    from_addr = "0x" + (topics[1].hex()[-40:] if isinstance(topics[1], bytes) else topics[1][-40:])
    to_addr = "0x" + (topics[2].hex()[-40:] if isinstance(topics[2], bytes) else topics[2][-40:])
    data = log.get("data") or b""
    if isinstance(data, str) and data.startswith("0x"):
        data = bytes.fromhex(data[2:])
    if len(data) < 32:
        raise ValueError("Invalid Transfer log: data too short")
    value_raw = int.from_bytes(data[:32], "big")
    log_index = log.get("logIndex", 0)
    if isinstance(log_index, bytes):
        log_index = int.from_bytes(log_index, "big")
    return from_addr, to_addr, str(value_raw), log_index


def wei_to_usdt(value_raw: int) -> Decimal:
    """USDT имеет 6 decimals."""
    return Decimal(value_raw) / (10**USDT_DECIMALS)


async def process_transfer_log(
    db: AsyncSession,
    log: LogReceipt,
    chain_id: int,
    usdt_contract_address: str,
    confirmations: int,
    current_block: int,
) -> bool:
    """
    Обработать один лог Transfer: проверить контракт, найти депозитный адрес, сохранить событие,
    зачислить на ledger. Идемпотентно: при дубликате (chain_id, tx_hash, log_index) не создаёт вторую запись.

    :return: True если событие обработано (создана запись или уже было), False если пропущено (не наш адрес и т.п.)
    """
    addr = log.get("address")
    if addr is None:
        return False
    if hasattr(addr, "hex"):
        contract = ("0x" + addr.hex()).lower()
    else:
        contract = str(addr).lower()
    if not contract.startswith("0x"):
        contract = "0x" + contract
    # usdt_contract_address передаётся уже нормализованным (lowercase, 0x)
    if contract != usdt_contract_address:
        return False

    try:
        from_addr, to_addr, value_raw_str, log_index = parse_transfer_log(log)
    except (ValueError, KeyError) as e:
        logger.warning("Skip invalid Transfer log: %s", e)
        return False

    value_raw = int(value_raw_str)
    if value_raw <= 0:
        return False

    block_number = log.get("blockNumber", 0)
    if isinstance(block_number, bytes):
        block_number = int.from_bytes(block_number, "big")
    if current_block - block_number < confirmations:
        logger.debug("Skip block %s: not enough confirmations", block_number)
        return False

    tx_hash = log.get("transactionHash") or b""
    if isinstance(tx_hash, bytes):
        tx_hash = "0x" + tx_hash.hex()
    else:
        tx_hash = str(tx_hash)

    # Найти пользователя по депозитному адресу (to), сравнение без учёта регистра
    to_normalized = to_addr.lower()
    if not to_normalized.startswith("0x"):
        to_normalized = "0x" + to_normalized
    result = await db.execute(
        select(DepositAddress).where(
            DepositAddress.chain_id == chain_id,
            func.lower(DepositAddress.address) == to_normalized,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        logger.debug("Transfer to unknown address %s", to_addr[:16] + "...")
        return False

    user_id = row.user_id
    value_usdt = wei_to_usdt(value_raw)

    # Проверка дубликата по blockchain_events
    existing = await db.execute(
        select(BlockchainEvent).where(
            BlockchainEvent.chain_id == chain_id,
            BlockchainEvent.tx_hash == tx_hash,
            BlockchainEvent.log_index == log_index,
        )
    )
    if existing.scalar_one_or_none() is not None:
        return True

    # Сохранить сырое событие
    from datetime import datetime, timezone
    event = BlockchainEvent(
        chain_id=chain_id,
        tx_hash=tx_hash,
        log_index=log_index,
        block_number=block_number,
        contract_address=contract,
        from_address=from_addr,
        to_address=to_addr,
        value_raw=value_raw_str,
        value_usdt=value_usdt,
        processed_at=datetime.now(timezone.utc),
    )
    db.add(event)
    await db.flush()

    # Ledger: идемпотентная запись депозита
    await try_record_blockchain_deposit(
        db,
        user_id=user_id,
        chain_id=chain_id,
        tx_hash=tx_hash,
        log_index=log_index,
        amount_usdt=value_usdt,
        blockchain_event_id=event.id,
    )
    logger.info(
        "Deposit credited: user_id=%s amount=%s USDT tx=%s",
        user_id,
        value_usdt,
        tx_hash[:16] + "...",
    )
    return True


async def get_or_init_cursor(db: AsyncSession, chain_id: int, start_block: int) -> int:
    """Вернуть last_block для chain_id; если записи нет — создать с start_block и вернуть start_block - 1."""
    result = await db.execute(select(WatcherCursor).where(WatcherCursor.chain_id == chain_id))
    cursor = result.scalar_one_or_none()
    if cursor is not None:
        return cursor.last_block
    db.add(WatcherCursor(chain_id=chain_id, last_block=start_block - 1))
    await db.flush()
    return start_block - 1


async def update_cursor(db: AsyncSession, chain_id: int, last_block: int) -> None:
    """Обновить курсор после обработки блока."""
    result = await db.execute(select(WatcherCursor).where(WatcherCursor.chain_id == chain_id))
    cursor = result.scalar_one_or_none()
    if cursor is not None:
        cursor.last_block = last_block
    else:
        db.add(WatcherCursor(chain_id=chain_id, last_block=last_block))
    await db.flush()
