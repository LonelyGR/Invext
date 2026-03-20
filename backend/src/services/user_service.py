"""
Сервис пользователей: создание/обновление по Telegram, привязка реферера.
"""
import uuid
from decimal import Decimal
from typing import Optional, Tuple

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.models.wallet_transaction import WalletTransaction
from src.models.withdraw_request import WithdrawRequest
from src.models.ledger_transaction import LedgerTransaction
from src.models.payment_invoice import PaymentInvoice
from src.services.ledger_service import (
    LEDGER_TYPE_DEPOSIT,
    LEDGER_TYPE_WITHDRAW,
    LEDGER_TYPE_INVEST,
    LEDGER_TYPE_PROFIT,
    LEDGER_TYPE_REFERRAL_BONUS,
    get_balance_usdt,
)


def _generate_ref_code() -> str:
    return uuid.uuid4().hex[:8].upper()


async def get_or_create_user(
    db: AsyncSession,
    telegram_id: int,
    username: Optional[str] = None,
    name: Optional[str] = None,
    ref_code_from_start: Optional[str] = None,
) -> Tuple[User, bool]:
    """
    Найти пользователя по telegram_id или создать нового.
    Если передан ref_code_from_start и у пользователя ещё нет referrer_id — привязать реферера.
    Возвращает (user, created).
    """
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if user:
        # Обновляем данные из Telegram
        user.username = username or user.username
        user.name = name or user.name
        # Привязка реферера только если ещё не привязан и передан код
        if user.referrer_id is None and ref_code_from_start:
            ref_result = await db.execute(
                select(User).where(User.ref_code == ref_code_from_start.upper().strip())
            )
            referrer = ref_result.scalar_one_or_none()
            if referrer and referrer.id != user.id:
                user.referrer_id = referrer.id
        return user, False

    referrer_id = None
    if ref_code_from_start:
        ref_result = await db.execute(
            select(User).where(User.ref_code == ref_code_from_start.upper().strip())
        )
        referrer = ref_result.scalar_one_or_none()
        if referrer:
            referrer_id = referrer.id

    user = User(
        telegram_id=telegram_id,
        username=username,
        name=name,
        ref_code=_generate_ref_code(),
        referrer_id=referrer_id,
    )
    db.add(user)
    await db.flush()
    return user, True


async def update_user_profile(
    db: AsyncSession,
    telegram_id: int,
    *,
    name: Optional[str] = None,
    email: Optional[str] = None,
    country: Optional[str] = None,
) -> Optional[User]:
    """Обновить имя, email или страну пользователя по telegram_id."""
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        return None
    if name is not None:
        user.name = name.strip() if name else None
    if email is not None:
        user.email = email.strip() if email else None
    if country is not None:
        user.country = country.strip() if country else None
    await db.flush()
    return user


async def get_user_with_stats(db: AsyncSession, telegram_id: int) -> Optional[dict]:
    """
    Получить пользователя и агрегированную статистику для /me:
    количество рефералов, оборот команды (депозиты рефералов), свои депозиты/выводы.
    """
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        return None

    # Количество рефералов по уровням (1..10)
    max_referral_levels = 10
    level_counts: dict[int, int] = {}
    current_level_parent_ids = [user.id]
    level1_ids: list[int] = []
    for level in range(1, max_referral_levels + 1):
        if not current_level_parent_ids:
            level_counts[level] = 0
            continue
        level_ids_result = await db.execute(
            select(User.id).where(User.referrer_id.in_(current_level_parent_ids))
        )
        level_ids = [r[0] for r in level_ids_result.all()]
        level_counts[level] = len(level_ids)
        if level == 1:
            level1_ids = level_ids
        current_level_parent_ids = level_ids
    referrals_count = level_counts.get(1, 0)

    # Оборот команды: сумма депозитов рефералов (USDT по ledger, USDC по wallet_transactions).
    # Подзапрос: user_id рефералов
    ref_ids_result = await db.execute(
        select(User.id).where(User.referrer_id == user.id)
    )
    ref_ids = [r[0] for r in ref_ids_result.all()]
    team_usdt = Decimal("0")
    team_usdc = Decimal("0")
    if ref_ids:
        # USDT: депозиты через ledger (Crypto Pay и пр.)
        r_usdt = await db.execute(
            select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
                and_(
                    LedgerTransaction.user_id.in_(ref_ids),
                    LedgerTransaction.type == LEDGER_TYPE_DEPOSIT,
                )
            )
        )
        team_usdt = r_usdt.scalar() or Decimal("0")

        # USDC: legacy по wallet_transactions
        r_usdc = await db.execute(
            select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
                and_(
                    WalletTransaction.user_id.in_(ref_ids),
                    WalletTransaction.currency == "USDC",
                    WalletTransaction.type == "DEPOSIT",
                    WalletTransaction.status == "COMPLETED",
                )
            )
        )
        team_usdc = r_usdc.scalar() or Decimal("0")

    # Свои депозиты/выводы:
    # USDT — по ledger, USDC — по wallet_transactions.
    my_d_usdt_res = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            and_(
                LedgerTransaction.user_id == user.id,
                LedgerTransaction.type == LEDGER_TYPE_DEPOSIT,
            )
        )
    )
    my_w_usdt_res = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            and_(
                LedgerTransaction.user_id == user.id,
                LedgerTransaction.type == LEDGER_TYPE_WITHDRAW,
            )
        )
    )

    my_d_usdc_res = await db.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
            and_(
                WalletTransaction.user_id == user.id,
                WalletTransaction.currency == "USDC",
                WalletTransaction.type == "DEPOSIT",
                WalletTransaction.status == "COMPLETED",
            )
        )
    )
    my_w_usdc_res = await db.execute(
        select(func.coalesce(func.sum(WalletTransaction.amount), 0)).where(
            and_(
                WalletTransaction.user_id == user.id,
                WalletTransaction.currency == "USDT",
                WalletTransaction.type == "WITHDRAW",
                WalletTransaction.status == "COMPLETED",
            )
        )
    )

    # Дополнительная статистика для раздела «Статистика»:
    # - текущий баланс USDT (по ledger),
    # - суммарный объём инвестиций (INVEST),
    # - суммарная прибыль по сделкам (PROFIT),
    # - суммарный доход по реферальным бонусам (REFERRAL_BONUS).
    balance_usdt = await get_balance_usdt(db, user.id)

    invested_total_res = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            and_(
                LedgerTransaction.user_id == user.id,
                LedgerTransaction.type == LEDGER_TYPE_INVEST,
            )
        )
    )
    invested_total = invested_total_res.scalar() or Decimal("0")

    profit_total_res = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            and_(
                LedgerTransaction.user_id == user.id,
                LedgerTransaction.type == LEDGER_TYPE_PROFIT,
            )
        )
    )
    profit_total = profit_total_res.scalar() or Decimal("0")

    referral_income_res = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            and_(
                LedgerTransaction.user_id == user.id,
                LedgerTransaction.type == LEDGER_TYPE_REFERRAL_BONUS,
            )
        )
    )
    referral_income = referral_income_res.scalar() or Decimal("0")

    deposits_count_res = await db.execute(
        select(func.count(PaymentInvoice.id)).where(PaymentInvoice.user_id == user.id)
    )
    deposits_count = deposits_count_res.scalar() or 0

    withdrawals_count_res = await db.execute(
        select(func.count(WithdrawRequest.id)).where(WithdrawRequest.user_id == user.id)
    )
    withdrawals_count = withdrawals_count_res.scalar() or 0

    result_payload = {
        "user": user,
        "referrals_count": referrals_count,
        "team_deposits_usdt": team_usdt,
        "team_deposits_usdc": team_usdc,
        "my_deposits_total_usdt": my_d_usdt_res.scalar() or Decimal("0"),
        "my_deposits_total_usdc": my_d_usdc_res.scalar() or Decimal("0"),
        "my_withdrawals_total_usdt": my_w_usdt_res.scalar() or Decimal("0"),
        "my_withdrawals_total_usdc": my_w_usdc_res.scalar() or Decimal("0"),
        "balance_usdt": balance_usdt,
        "invested_total_usdt": invested_total,
        "profit_total_usdt": profit_total,
        "referral_income_usdt": referral_income,
        "deposits_count": deposits_count,
        "withdrawals_count": withdrawals_count,
    }
    for level in range(1, max_referral_levels + 1):
        result_payload[f"referrals_level_{level}"] = level_counts.get(level, 0)
    return result_payload
