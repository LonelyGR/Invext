"""
Сервис кошелька: баланс USDT считается по ledger (депозиты с блокчейна минус вывод/инвестиции).
USDC по-прежнему из wallet_transactions для совместимости.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import select, func, and_, exists
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.models.wallet_transaction import WalletTransaction
from src.models.ledger_transaction import LedgerTransaction
from src.models.system_settings import SystemSettings
from src.services.ledger_service import (
    get_balance_usdt,
    LEDGER_TYPE_DEPOSIT,
    sync_user_balance,
)


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


def _welcome_bonus_amount_from_settings(settings: SystemSettings) -> Decimal:
    raw = getattr(settings, "welcome_bonus_amount_usdt", None)
    if raw is None:
        return Decimal("100")
    return Decimal(str(raw))


async def _user_ledger_is_empty(db: AsyncSession, user_id: int) -> bool:
    """Ни одной строки в ledger_transactions — пользователь ещё не совершал операций по USDT-леджеру."""
    r = await db.execute(
        select(func.count()).select_from(LedgerTransaction).where(LedgerTransaction.user_id == user_id)
    )
    return int(r.scalar() or 0) == 0


async def _user_matches_welcome_bonus_eligibility(
    db: AsyncSession,
    user: User,
    settings: SystemSettings,
) -> bool:
    """
    Два независимых критерия (достаточно одного, если оба включены в настройках):

    - «Пустой ledger» (welcome_bonus_for_zero_balance): нет ни одной записи в ledger —
      не «нулевой баланс после операций», а отсутствие пополнений и любых проводок.

    - «Новые регистрации» (welcome_bonus_for_new_users): аккаунт не старше N дней
      и ledger по-прежнему пуст (новичок без движений по леджеру).
    """
    for_new = bool(getattr(settings, "welcome_bonus_for_new_users", True))
    for_empty_ledger = bool(getattr(settings, "welcome_bonus_for_zero_balance", True))
    if not for_new and not for_empty_ledger:
        return False

    empty = await _user_ledger_is_empty(db, user.id)
    if not empty:
        return False

    ok = False
    if for_empty_ledger:
        ok = True
    if for_new:
        days = int(getattr(settings, "welcome_bonus_new_user_days", 30) or 30)
        days = max(1, min(days, 3650))
        threshold = datetime.now(timezone.utc) - timedelta(days=days)
        created = user.created_at
        if created is not None:
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created >= threshold:
                ok = True
    return ok


async def get_welcome_bonus_status(db: AsyncSession, telegram_id: int) -> dict:
    """
    Проверить, доступен ли приветственный бонус пользователю.
    Условия:
    - глобальная настройка allow_welcome_bonus = True;
    - пользователь существует;
    - выполняется хотя бы один из включённых критериев (см. настройки: пустой ledger / недавняя регистрация при пустом ledger);
    - в леджере нет записей DEPOSIT с provider='WELCOME_BONUS'.
    """
    result = await db.execute(select(SystemSettings).limit(1))
    settings = result.scalar_one_or_none()
    if not settings or not bool(getattr(settings, "allow_welcome_bonus", True)):
        return {"available": False, "amount": None}

    bonus_amount = _welcome_bonus_amount_from_settings(settings)

    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        return {"available": False, "amount": None}

    if not await _user_matches_welcome_bonus_eligibility(db, user, settings):
        return {"available": False, "amount": None}

    bonus_exists_q = await db.execute(
        select(exists().where(
            and_(
                LedgerTransaction.user_id == user.id,
                LedgerTransaction.type == LEDGER_TYPE_DEPOSIT,
                LedgerTransaction.provider == "WELCOME_BONUS",
            )
        ))
    )
    if bool(bonus_exists_q.scalar()):
        return {"available": False, "amount": None}

    return {"available": True, "amount": bonus_amount}


async def apply_welcome_bonus(db: AsyncSession, telegram_id: int) -> dict:
    """
    Начислить приветственный бонус пользователю, если он доступен.
    Возвращает dict с ключами success, amount, new_balance, detail.
    """
    result = await db.execute(select(SystemSettings).limit(1).with_for_update())
    settings = result.scalar_one_or_none()
    if not settings or not bool(getattr(settings, "allow_welcome_bonus", True)):
        return {"success": False, "amount": None, "new_balance": None, "detail": "Бонус сейчас отключён."}

    bonus_amount = _welcome_bonus_amount_from_settings(settings)

    result = await db.execute(select(User).where(User.telegram_id == telegram_id).with_for_update())
    user = result.scalar_one_or_none()
    if not user:
        return {"success": False, "amount": None, "new_balance": None, "detail": "Пользователь не найден."}

    balance = await get_balance_usdt(db, user.id)
    if not await _user_matches_welcome_bonus_eligibility(db, user, settings):
        return {
            "success": False,
            "amount": None,
            "new_balance": balance,
            "detail": "Условия для бонуса не выполнены (нужен пустой ledger и подходящий сценарий в настройках).",
        }

    bonus_exists_q = await db.execute(
        select(exists().where(
            and_(
                LedgerTransaction.user_id == user.id,
                LedgerTransaction.type == LEDGER_TYPE_DEPOSIT,
                LedgerTransaction.provider == "WELCOME_BONUS",
            )
        ))
    )
    if bool(bonus_exists_q.scalar()):
        new_balance = await get_balance_usdt(db, user.id)
        return {
            "success": False,
            "amount": None,
            "new_balance": new_balance,
            "detail": "Бонус уже был начислен ранее.",
        }

    tx = LedgerTransaction(
        user_id=user.id,
        type=LEDGER_TYPE_DEPOSIT,
        amount_usdt=bonus_amount,
        provider="WELCOME_BONUS",
        external_payment_id=None,
        metadata_json={"reason": "welcome_bonus"},
    )
    db.add(tx)

    new_balance = await sync_user_balance(db, user.id)

    return {
        "success": True,
        "amount": bonus_amount,
        "new_balance": new_balance,
        "detail": None,
    }
