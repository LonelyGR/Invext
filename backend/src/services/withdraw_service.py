"""
Сервис заявок на вывод: создание (с проверкой баланса), список, админ approve/reject.
При approve — создаётся запись в ledger WITHDRAW COMPLETED (баланс списывается).

Сумма заявки (amount) — полное списание с баланса. Комиссия 10% от этой суммы;
на внешний кошелёк отправляется 90% (net), 10% остаётся платформе.
"""
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.models.withdraw_request import WithdrawRequest
from src.models.wallet_transaction import WalletTransaction
from src.services.wallet_service import get_balances
from src.services.settings_service import get_system_settings

# Доля комиссии от суммы списания (gross).
WITHDRAW_FEE_RATE = Decimal("0.10")


def withdraw_fee_and_net(gross: Decimal) -> tuple[Decimal, Decimal]:
    """
    gross — сумма списания с баланса (как в заявке).
    Возвращает (fee, net): комиссия 10% от gross, к выплате на адрес — net = gross − fee.
    """
    g = gross.quantize(Decimal("0.01"))
    fee = (g * WITHDRAW_FEE_RATE).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    net = g - fee
    return fee, net


def _format_withdraw_limit(n: float) -> str:
    i = int(n)
    if abs(n - i) < 1e-9:
        return str(i)
    s = str(n).rstrip("0").rstrip(".")
    return s


def _validate_amount(amount: Decimal, min_val: float, max_val: float) -> None:
    if amount < Decimal(str(min_val)) or amount > Decimal(str(max_val)):
        raise ValueError(
            f"Сумма вывода от {_format_withdraw_limit(min_val)}$ до {_format_withdraw_limit(max_val)}$"
        )


async def create_withdraw_request(
    db: AsyncSession,
    telegram_id: int,
    currency: str,
    amount: Decimal,
    address: str,
) -> WithdrawRequest:
    """Создать заявку на вывод (PENDING). Проверка баланса и лимитов.

    amount — сумма полного списания с баланса (до вычета комиссии на стороне сети:
    комиссия 10% от этой суммы, пользователю на адрес уходит 90%).

    Защита от дублей: при повторной отправке тех же данных (user, currency, amount, address)
    и статусе PENDING возвращает уже существующую заявку.
    """
    settings = await get_system_settings(db)
    # Бизнес-правило: минимальная сумма вывода 50 USDT (даже если настройки меньше).
    effective_min = max(Decimal(str(settings.min_withdraw_usdt)), Decimal("50"))
    _validate_amount(amount, float(effective_min), float(settings.max_withdraw_usdt))

    _, net = withdraw_fee_and_net(amount)
    if net <= 0:
        raise ValueError("Сумма к получению после комиссии должна быть больше 0. Увеличьте сумму вывода.")

    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    balances = await get_balances(db, telegram_id)
    available = balances.get(currency, Decimal("0"))
    if available < amount:
        raise ValueError(f"Недостаточно средств. Доступно {currency}: {available}")

    # Идемпотентность: если уже есть PENDING-заявка с теми же параметрами, возвращаем её.
    existing_q = await db.execute(
        select(WithdrawRequest).where(
            WithdrawRequest.user_id == user.id,
            WithdrawRequest.currency == currency,
            WithdrawRequest.amount == amount,
            WithdrawRequest.address == address.strip(),
            WithdrawRequest.status == "PENDING",
        )
    )
    existing_req = existing_q.scalar_one_or_none()
    if existing_req:
        return existing_req

    req = WithdrawRequest(
        user_id=user.id,
        currency=currency,
        amount=amount,
        address=address.strip(),
        status="PENDING",
    )
    db.add(req)
    await db.flush()
    return req


async def get_my_withdrawals(db: AsyncSession, telegram_id: int) -> list:
    """Список заявок на вывод текущего пользователя."""
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        return []
    r = await db.execute(
        select(WithdrawRequest).where(WithdrawRequest.user_id == user.id).order_by(WithdrawRequest.created_at.desc())
    )
    return list(r.scalars().all())


async def get_pending_withdrawals_with_users(db: AsyncSession) -> list:
    """Список заявок PENDING с данными пользователя для админки."""
    r = await db.execute(
        select(WithdrawRequest, User)
        .join(User, WithdrawRequest.user_id == User.id)
        .where(WithdrawRequest.status == "PENDING")
        .order_by(WithdrawRequest.created_at.asc())
    )
    return [(req, user) for req, user in r.all()]


async def approve_withdraw(
    db: AsyncSession,
    withdraw_id: int,
    decided_by_telegram_id: int,
) -> WithdrawRequest:
    """
    Подтвердить вывод: статус APPROVED, создать ledger-транзакцию WITHDRAW COMPLETED.
    Баланс при создании заявки уже проверялся; повторно не проверяем (админ подтверждает).
    """
    async with db.begin():
        result = await db.execute(
            select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id).with_for_update()
        )
        req = result.scalar_one_or_none()
        if not req:
            raise ValueError("Withdraw request not found")
        if req.status != "PENDING":
            raise ValueError(f"Request already {req.status}")

        # Лочим пользователя и повторно проверяем баланс, чтобы исключить гонки.
        usr_result = await db.execute(
            select(User).where(User.id == req.user_id).with_for_update()
        )
        usr = usr_result.scalar_one_or_none()
        if not usr:
            raise ValueError("User not found")

        balances = await get_balances(db, usr.telegram_id)
        if balances.get(req.currency, Decimal("0")) < req.amount:
            raise ValueError("Недостаточно средств у пользователя")

        req.status = "APPROVED"
        req.decided_at = datetime.now(timezone.utc)
        req.decided_by = decided_by_telegram_id

        tx = WalletTransaction(
            user_id=req.user_id,
            currency=req.currency,
            type="WITHDRAW",
            amount=req.amount,
            status="COMPLETED",
            related_withdraw_request_id=req.id,
        )
        db.add(tx)
        await db.flush()

    return req


async def reject_withdraw(
    db: AsyncSession,
    withdraw_id: int,
    decided_by_telegram_id: int,
) -> WithdrawRequest:
    """Отклонить заявку: только смена статуса на REJECTED."""
    result = await db.execute(
        select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id)
    )
    req = result.scalar_one_or_none()
    if not req:
        raise ValueError("Withdraw request not found")
    if req.status != "PENDING":
        raise ValueError(f"Request already {req.status}")

    req.status = "REJECTED"
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = decided_by_telegram_id
    return req


async def cancel_withdraw_request(db: AsyncSession, telegram_id: int, withdraw_id: int) -> WithdrawRequest:
    """
    Отмена вывода пользователем.

    Важно: в текущей бухгалтерской логике средства списываются только при APPROVE
    (создание WalletTransaction WITHDRAW). Поэтому для статуса PENDING достаточно
    сменить статус на CANCELLED — баланс возвращать не нужно.

    Транзакцию коммитит вызывающий (FastAPI get_db). Без вложенного session.begin():
    иначе после COMMIT SAVEPOINT ORM-объект может «протухнуть», и Pydantic при
    сериализации тронет updated_at вне async-контекста → MissingGreenlet.
    """
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    req_result = await db.execute(
        select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id).with_for_update()
    )
    req = req_result.scalar_one_or_none()
    if not req or req.user_id != user.id:
        raise ValueError("Withdraw request not found")
    if req.status == "CANCELLED":
        return req
    if req.status != "PENDING":
        raise ValueError("Нельзя отменить: заявка уже обработана.")
    req.status = "CANCELLED"
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = telegram_id
    await db.flush()
    await db.refresh(req)
    return req
