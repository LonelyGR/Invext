"""Ledger: расчёт баланса пользователя по журналу операций.

`users.balance_usdt` считается кэшем, а источником правды является сумма записей
в таблице `ledger_transactions`.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.ledger_transaction import LedgerTransaction

logger = logging.getLogger(__name__)

# Типы операций в новом леджере
LEDGER_TYPE_DEPOSIT = "DEPOSIT"
LEDGER_TYPE_WITHDRAW = "WITHDRAW"
LEDGER_TYPE_INVEST = "INVEST"
LEDGER_TYPE_PROFIT = "PROFIT"

# Для обратной совместимости со старыми данными.
LEDGER_TYPE_DEPOSIT_BLOCKCHAIN = "DEPOSIT_BLOCKCHAIN"


async def get_balance_usdt(db: AsyncSession, user_id: int) -> Decimal:
    """
    Баланс USDT пользователя = сумма amount_usdt по всем ledger-записям.
    DEPOSIT/PROFIT увеличивают, WITHDRAW и INVEST уменьшают.
    Старый тип DEPOSIT_BLOCKCHAIN также учитывается как пополнение.
    """
    credit_types = (
        LEDGER_TYPE_DEPOSIT,
        LEDGER_TYPE_PROFIT,
        LEDGER_TYPE_DEPOSIT_BLOCKCHAIN,
    )
    debit_types = (LEDGER_TYPE_WITHDRAW, LEDGER_TYPE_INVEST)

    # Сумма зачислений
    credit = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            and_(
                LedgerTransaction.user_id == user_id,
                LedgerTransaction.type.in_(credit_types),
            )
        )
    )
    # Сумма списаний
    debit = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            and_(
                LedgerTransaction.user_id == user_id,
                LedgerTransaction.type.in_(debit_types),
            )
        )
    )
    credits = credit.scalar() or Decimal("0")
    debits = debit.scalar() or Decimal("0")
    return credits - debits
