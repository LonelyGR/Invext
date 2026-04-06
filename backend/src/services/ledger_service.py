"""Ledger: расчёт баланса пользователя по журналу операций.

`users.balance_usdt` считается кэшем, а источником правды является сумма записей
в таблице `ledger_transactions`.
"""
from __future__ import annotations

import logging
from decimal import Decimal
from typing import Optional

from sqlalchemy import select, func, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.ledger_transaction import LedgerTransaction

logger = logging.getLogger(__name__)

# Типы операций в новом леджере
LEDGER_TYPE_DEPOSIT = "DEPOSIT"
LEDGER_TYPE_WITHDRAW = "WITHDRAW"
LEDGER_TYPE_WITHDRAW_REFUND = "WITHDRAW_REFUND"  # возврат при отмене/отклонении заявки на вывод
LEDGER_TYPE_INVEST = "INVEST"
LEDGER_TYPE_INVEST_RETURN = "INVEST_RETURN"
LEDGER_TYPE_PROFIT = "PROFIT"
LEDGER_TYPE_REFERRAL_BONUS = "REFERRAL_BONUS"

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
        LEDGER_TYPE_INVEST_RETURN,
        LEDGER_TYPE_PROFIT,
        LEDGER_TYPE_REFERRAL_BONUS,
        LEDGER_TYPE_DEPOSIT_BLOCKCHAIN,
        LEDGER_TYPE_WITHDRAW_REFUND,
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


async def clear_user_ledger_entries(db: AsyncSession, user_id: int) -> int:
    """
    Полностью очистить ledger-записи пользователя (только таблица ledger_transactions).
    Возвращает число удалённых строк.
    """
    result = await db.execute(
        delete(LedgerTransaction).where(LedgerTransaction.user_id == user_id)
    )
    return int(result.rowcount or 0)
