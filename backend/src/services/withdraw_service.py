"""
Сервис заявок на вывод: при создании заявки сумма сразу списывается с баланса (hold).
При подтверждении — только смена статуса; при отклонении или отмене — возврат на баланс.
"""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.models.withdraw_request import WithdrawRequest
from src.models.wallet_transaction import WalletTransaction
from src.models.ledger_transaction import LedgerTransaction
from src.services.wallet_service import get_balances
from src.services.settings_service import get_system_settings
from src.services.ledger_service import (
    LEDGER_TYPE_WITHDRAW,
    LEDGER_TYPE_WITHDRAW_REFUND,
    get_balance_usdt,
    sync_user_balance,
)


def withdraw_fee_and_net(gross: Decimal) -> tuple[Decimal, Decimal]:
    """Обратная совместимость API: комиссии нет, к выплате = сумма заявки."""
    g = gross.quantize(Decimal("0.01"))
    return Decimal("0"), g


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


async def _find_usdt_ledger_hold(
    db: AsyncSession, user_id: int, withdraw_id: int
) -> LedgerTransaction | None:
    r = await db.execute(
        select(LedgerTransaction).where(
            LedgerTransaction.user_id == user_id,
            LedgerTransaction.type == LEDGER_TYPE_WITHDRAW,
            LedgerTransaction.metadata_json.contains({"withdraw_request_id": withdraw_id}),
        ).limit(1)
    )
    return r.scalar_one_or_none()


async def _find_usdc_withdraw_hold(
    db: AsyncSession, withdraw_id: int
) -> WalletTransaction | None:
    r = await db.execute(
        select(WalletTransaction).where(
            WalletTransaction.related_withdraw_request_id == withdraw_id,
            WalletTransaction.type == "WITHDRAW",
            WalletTransaction.status == "COMPLETED",
        ).limit(1)
    )
    return r.scalar_one_or_none()


async def _refund_usdt_hold(
    db: AsyncSession, user: User, req: WithdrawRequest, *, reason: str
) -> None:
    if await _find_usdt_ledger_hold(db, user.id, req.id):
        db.add(
            LedgerTransaction(
                user_id=user.id,
                type=LEDGER_TYPE_WITHDRAW_REFUND,
                amount_usdt=req.amount,
                metadata_json={"withdraw_request_id": req.id, "reason": reason},
            )
        )
        await sync_user_balance(db, user.id)


async def _refund_usdc_hold(db: AsyncSession, user: User, req: WithdrawRequest) -> None:
    if await _find_usdc_withdraw_hold(db, req.id):
        db.add(
            WalletTransaction(
                user_id=user.id,
                currency="USDC",
                type="DEPOSIT",
                amount=req.amount,
                status="COMPLETED",
            )
        )


async def create_withdraw_request(
    db: AsyncSession,
    telegram_id: int,
    currency: str,
    amount: Decimal,
    address: str,
) -> WithdrawRequest:
    """Создать заявку PENDING и сразу зарезервировать сумму на балансе."""
    settings = await get_system_settings(db)
    effective_min = max(Decimal(str(settings.min_withdraw_usdt)), Decimal("50"))
    _validate_amount(amount, float(effective_min), float(settings.max_withdraw_usdt))

    if amount <= 0:
        raise ValueError("Сумма должна быть больше 0.")

    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    balances = await get_balances(db, telegram_id)
    available = balances.get(currency, Decimal("0"))
    if available < amount:
        raise ValueError(f"Недостаточно средств. Доступно {currency}: {available}")

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

    if currency == "USDT":
        db.add(
            LedgerTransaction(
                user_id=user.id,
                type=LEDGER_TYPE_WITHDRAW,
                amount_usdt=amount,
                metadata_json={"withdraw_request_id": req.id},
            )
        )
        await sync_user_balance(db, user.id)
    elif currency == "USDC":
        db.add(
            WalletTransaction(
                user_id=user.id,
                currency=currency,
                type="WITHDRAW",
                amount=amount,
                status="COMPLETED",
                related_withdraw_request_id=req.id,
            )
        )
    else:
        raise ValueError("Unsupported currency")

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
    decided_by: int,
) -> tuple[WithdrawRequest, bool]:
    """
    Подтвердить вывод: статус APPROVED.
    Если сумма уже зарезервирована при создании заявки — новая проводка не создаётся.
    Старые PENDING без hold: списание выполняется здесь (как раньше).
    Второй элемент кортежа — True, если статус изменился (для логирования).
    """
    result = await db.execute(
        select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id).with_for_update()
    )
    req = result.scalar_one_or_none()
    if not req:
        raise ValueError("Withdraw request not found")
    if req.status == "APPROVED":
        return req, False
    if req.status != "PENDING":
        raise ValueError(f"Request already {req.status}")

    usr_result = await db.execute(select(User).where(User.id == req.user_id).with_for_update())
    usr = usr_result.scalar_one_or_none()
    if not usr:
        raise ValueError("User not found")

    if req.currency == "USDT":
        hold = await _find_usdt_ledger_hold(db, usr.id, req.id)
        if not hold:
            balance = await get_balance_usdt(db, usr.id)
            if balance < req.amount:
                raise ValueError("Недостаточно средств у пользователя")
            db.add(
                LedgerTransaction(
                    user_id=usr.id,
                    type=LEDGER_TYPE_WITHDRAW,
                    amount_usdt=req.amount,
                    metadata_json={"withdraw_request_id": req.id, "legacy_on_approve": True},
                )
            )
        await sync_user_balance(db, usr.id)
    elif req.currency == "USDC":
        if not await _find_usdc_withdraw_hold(db, req.id):
            balances = await get_balances(db, usr.telegram_id)
            if balances.get("USDC", Decimal("0")) < req.amount:
                raise ValueError("Недостаточно средств у пользователя")
            db.add(
                WalletTransaction(
                    user_id=req.user_id,
                    currency=req.currency,
                    type="WITHDRAW",
                    amount=req.amount,
                    status="COMPLETED",
                    related_withdraw_request_id=req.id,
                )
            )
    else:
        raise ValueError("Unsupported currency")

    req.status = "APPROVED"
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = decided_by
    await db.flush()
    return req, True


async def reject_withdraw(
    db: AsyncSession,
    withdraw_id: int,
    decided_by: int,
) -> tuple[WithdrawRequest, bool]:
    """Отклонить заявку: статус REJECTED и возврат зарезервированной суммы (если была)."""
    result = await db.execute(
        select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id).with_for_update()
    )
    req = result.scalar_one_or_none()
    if not req:
        raise ValueError("Withdraw request not found")
    if req.status == "REJECTED":
        return req, False
    if req.status != "PENDING":
        raise ValueError(f"Request already {req.status}")

    user = await db.get(User, req.user_id)
    if not user:
        raise ValueError("User not found")

    if req.currency == "USDT":
        await _refund_usdt_hold(db, user, req, reason="reject")
    elif req.currency == "USDC":
        await _refund_usdc_hold(db, user, req)

    req.status = "REJECTED"
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = decided_by
    await db.flush()
    return req, True


async def cancel_withdraw_request(
    db: AsyncSession, telegram_id: int, withdraw_id: int
) -> WithdrawRequest:
    """
    Отмена вывода пользователем (PENDING → CANCELLED).
    Зарезервированная сумма возвращается на баланс.
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

    if req.currency == "USDT":
        await _refund_usdt_hold(db, user, req, reason="cancel")
    elif req.currency == "USDC":
        await _refund_usdc_hold(db, user, req)

    req.status = "CANCELLED"
    req.decided_at = datetime.now(timezone.utc)
    req.decided_by = telegram_id
    await db.flush()
    await db.refresh(req)
    return req
