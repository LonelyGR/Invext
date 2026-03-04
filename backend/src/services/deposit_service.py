"""
Сервис заявок на пополнение: создание, список, админ approve/reject.
При approve — создаётся запись в ledger (DEPOSIT COMPLETED).
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.models.user import User
from src.models.deposit_request import DepositRequest
from src.models.wallet_transaction import WalletTransaction


def _validate_amount(amount: Decimal, min_val: float, max_val: float) -> None:
    if amount < Decimal(str(min_val)) or amount > Decimal(str(max_val)):
        raise ValueError(f"Сумма должна быть от {min_val} до {max_val}")


async def create_deposit_request(
    db: AsyncSession,
    telegram_id: int,
    currency: str,
    amount: Decimal,
) -> DepositRequest:
    """Создать заявку на пополнение (PENDING). Валидация лимитов."""
    settings = get_settings()
    _validate_amount(amount, settings.min_deposit, settings.max_deposit)

    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    req = DepositRequest(
        user_id=user.id,
        currency=currency,
        amount=amount,
        status="PENDING",
    )
    db.add(req)
    await db.flush()
    return req


async def get_my_deposits(db: AsyncSession, telegram_id: int) -> list:
    """Список заявок на пополнение текущего пользователя."""
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        return []
    r = await db.execute(
        select(DepositRequest).where(DepositRequest.user_id == user.id).order_by(DepositRequest.created_at.desc())
    )
    return list(r.scalars().all())


async def get_pending_deposits_with_users(db: AsyncSession) -> list:
    """Список заявок PENDING с данными пользователя для админки."""
    r = await db.execute(
        select(DepositRequest, User)
        .join(User, DepositRequest.user_id == User.id)
        .where(DepositRequest.status == "PENDING")
        .order_by(DepositRequest.created_at.asc())
    )
    return [(req, user) for req, user in r.all()]


async def approve_deposit(
    db: AsyncSession,
    deposit_id: int,
    decided_by_telegram_id: int,
) -> DepositRequest:
    """
    Подтвердить заявку: статус APPROVED, создать ledger-транзакцию DEPOSIT COMPLETED.
    """
    result = await db.execute(
        select(DepositRequest).where(DepositRequest.id == deposit_id)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise ValueError("Deposit request not found")
    if req.status != "PENDING":
        raise ValueError(f"Request already {req.status}")

    req.status = "APPROVED"
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = decided_by_telegram_id

    tx = WalletTransaction(
        user_id=req.user_id,
        currency=req.currency,
        type="DEPOSIT",
        amount=req.amount,
        status="COMPLETED",
        related_deposit_request_id=req.id,
    )
    db.add(tx)
    await db.flush()
    return req


async def reject_deposit(
    db: AsyncSession,
    deposit_id: int,
    decided_by_telegram_id: int,
) -> DepositRequest:
    """Отклонить заявку: только смена статуса на REJECTED."""
    result = await db.execute(
        select(DepositRequest).where(DepositRequest.id == deposit_id)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise ValueError("Deposit request not found")
    if req.status != "PENDING":
        raise ValueError(f"Request already {req.status}")

    req.status = "REJECTED"
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = decided_by_telegram_id
    return req
