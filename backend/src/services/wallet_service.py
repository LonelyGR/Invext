"""
Сервис кошелька: баланс USDT считается по ledger (депозиты с блокчейна минус вывод/инвестиции).
USDC по-прежнему из wallet_transactions для совместимости.
"""
from decimal import Decimal

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.models.wallet_transaction import WalletTransaction
from src.services.ledger_service import get_balance_usdt


async def get_balances(db: AsyncSession, telegram_id: int) -> dict:
    """
    USDT: баланс из ledger_transactions (депозиты с блокчейна минус вывод/инвестиции).
    USDC: сумма DEPOSIT - WITHDRAW по wallet_transactions (legacy).
    """
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"USDT": Decimal("0"), "USDC": Decimal("0")}

    usdt_balance = await get_balance_usdt(db, user.id)

    # USDC: legacy из wallet_transactions
    deposit_sum = await db.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
            and_(
                WalletTransaction.user_id == user.id,
                WalletTransaction.currency == "USDC",
                WalletTransaction.type == "DEPOSIT",
                WalletTransaction.status == "COMPLETED",
            )
        )
    )
    withdraw_sum = await db.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
            and_(
                WalletTransaction.user_id == user.id,
                WalletTransaction.currency == "USDC",
                WalletTransaction.type == "WITHDRAW",
                WalletTransaction.status == "COMPLETED",
            )
        )
    )
    usdc_balance = (deposit_sum.scalar() or Decimal("0")) - (withdraw_sum.scalar() or Decimal("0"))

    return {"USDT": usdt_balance, "USDC": usdc_balance}
