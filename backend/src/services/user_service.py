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
from src.models.referral_reward import ReferralReward, STATUS_PAID
from src.services.ledger_service import (
    LEDGER_TYPE_DEPOSIT,
    LEDGER_TYPE_WITHDRAW,
    LEDGER_TYPE_WITHDRAW_REFUND,
    LEDGER_TYPE_INVEST,
    LEDGER_TYPE_PROFIT,
    LEDGER_TYPE_REFERRAL_BONUS,
    get_balance_usdt,
)


def _generate_ref_code() -> str:
    return uuid.uuid4().hex[:8].upper()


async def _would_create_referrer_cycle(
    db: AsyncSession,
    *,
    user_id: int,
    candidate_referrer_id: int,
    max_levels: int = 100,
) -> bool:
    """
    Проверить, создаст ли привязка user -> candidate_referrer цикл.
    Идём вверх по цепочке candidate_referrer.referrer_id и ищем user_id.
    """
    if user_id == candidate_referrer_id:
        return True

    visited: set[int] = set()
    current_id: Optional[int] = candidate_referrer_id
    for _ in range(max_levels):
        if current_id is None:
            return False
        if current_id == user_id:
            return True
        if current_id in visited:
            # В данных уже есть чужой цикл выше по дереву.
            # Для текущей связи user -> candidate_referrer это не означает,
            # что цикл создаётся именно с user_id.
            return False
        visited.add(current_id)

        result = await db.execute(select(User.referrer_id).where(User.id == current_id))
        current_id = result.scalar_one_or_none()
    # Защитный предел от бесконечных/грязных данных:
    # не считаем это прямым доказательством цикла с user_id.
    return False


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
                if await _would_create_referrer_cycle(
                    db,
                    user_id=user.id,
                    candidate_referrer_id=referrer.id,
                ):
                    return user, False
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

    # Только прямой уровень: пользователи с referrer_id == этот user.
    direct_refs_result = await db.execute(select(User.id).where(User.referrer_id == user.id))
    level1_ids = [int(r[0]) for r in direct_refs_result.all()]
    referrals_count = len(level1_ids)

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
    my_w_usdt_refund_res = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            and_(
                LedgerTransaction.user_id == user.id,
                LedgerTransaction.type == LEDGER_TYPE_WITHDRAW_REFUND,
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

    # Заработано с реферальных бонусов (исторически) считаем по ledger как по источнику правды.
    # Кол-во рефералов с выплатой (L1) оставляем по referral_rewards, т.к. это отдельная метрика охвата.
    referral_l1_row = await db.execute(
        select(func.count(func.distinct(ReferralReward.from_user_id))).where(
            and_(
                ReferralReward.to_user_id == user.id,
                ReferralReward.status == STATUS_PAID,
                ReferralReward.level == 1,
            )
        )
    )
    referral_l1_earned_row = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            and_(
                LedgerTransaction.user_id == user.id,
                LedgerTransaction.type == LEDGER_TYPE_REFERRAL_BONUS,
            )
        )
    )
    l1_cnt = referral_l1_row.scalar() or 0
    l1_amt = referral_l1_earned_row.scalar() or Decimal("0")
    referral_level1_count = int(l1_cnt or 0)
    referral_level1_earned = Decimal(str(l1_amt or 0))

    result_payload = {
        "user": user,
        "referrals_count": referrals_count,
        "team_deposits_usdt": team_usdt,
        "team_deposits_usdc": team_usdc,
        "my_deposits_total_usdt": my_d_usdt_res.scalar() or Decimal("0"),
        "my_deposits_total_usdc": my_d_usdc_res.scalar() or Decimal("0"),
        "my_withdrawals_total_usdt": (my_w_usdt_res.scalar() or Decimal("0"))
        - (my_w_usdt_refund_res.scalar() or Decimal("0")),
        "my_withdrawals_total_usdc": my_w_usdc_res.scalar() or Decimal("0"),
        "balance_usdt": balance_usdt,
        "invested_total_usdt": invested_total,
        "profit_total_usdt": profit_total,
        "referral_income_usdt": referral_income,
        "deposits_count": deposits_count,
        "withdrawals_count": withdrawals_count,
    }
    result_payload["referrals_level_1"] = referrals_count
    result_payload["referral_rewarded_level_1_count"] = referral_level1_count
    result_payload["referral_earned_level_1_usdt"] = referral_level1_earned
    return result_payload
