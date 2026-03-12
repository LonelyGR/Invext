"""
Реферальные бонусы с депозита: многоуровневая (до 3 уровней) цепочка referrer_id.

Ключевые правила:
- Бонус начисляется только с подтверждённого депозита (DEPOSIT в ledger).
- Инвестиции, участие в сделках и прибыль по сделкам не создают реферальных бонусов.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import LedgerTransaction, User
from src.services.ledger_service import LEDGER_TYPE_REFERRAL_BONUS, get_balance_usdt

# Проценты по уровням: 1, 2, 3 уровень — по 3%
REFERRAL_LEVEL_PERCENTS: List[Decimal] = [
    Decimal("3"),
    Decimal("3"),
    Decimal("3"),
]
MAX_LEVELS = 3


async def _get_referrer_chain(
    db: AsyncSession,
    user_id: int,
    max_levels: int = MAX_LEVELS,
) -> list[User]:
    """
    Цепочка рефереров вверх по полю User.referrer_id, максимум max_levels.
    Защита от самореферала и циклов.
    """
    chain: list[User] = []
    current_id: Optional[int] = user_id
    visited: set[int] = set()

    for _ in range(max_levels):
        if current_id is None or current_id in visited:
            break
        visited.add(current_id)

        res = await db.execute(select(User).where(User.id == current_id))
        u = res.scalar_one_or_none()
        if not u or u.referrer_id is None:
            break

        # Самореферал и очевидные циклы
        if u.referrer_id == u.id:
            break

        current_id = u.referrer_id
        res_ref = await db.execute(select(User).where(User.id == current_id))
        referrer = res_ref.scalar_one_or_none()
        if not referrer:
            break
        chain.append(referrer)

    return chain


async def apply_referral_rewards_for_deposit(
    db: AsyncSession,
    from_user: User,
    deposit_amount: Decimal,
    source_invoice_id: int,
    external_payment_id: str,
) -> None:
    """
    Начислить реферальные бонусы за депозит from_user на сумму deposit_amount.

    - Только для депозитов (вызывается из payment_service.apply_payment_to_balance).
    - До 3 уровней, каждому уровню 3% от суммы депозита.
    - История начислений хранится в ledger (type=REFERRAL_BONUS, metadata_json.source='deposit').
    """
    if deposit_amount <= 0:
        return

    referrers = await _get_referrer_chain(db, from_user.id, MAX_LEVELS)
    if not referrers:
        return

    for level_index, referrer in enumerate(referrers):
        level = level_index + 1
        if level > len(REFERRAL_LEVEL_PERCENTS):
            break
        pct = REFERRAL_LEVEL_PERCENTS[level_index]
        reward_amount = (deposit_amount * pct / Decimal("100")).quantize(Decimal("0.01"))
        if reward_amount <= 0:
            continue

        ledger_tx = LedgerTransaction(
            user_id=referrer.id,
            type=LEDGER_TYPE_REFERRAL_BONUS,
            amount_usdt=reward_amount,
            metadata_json={
                "source": "deposit",
                "from_user_id": from_user.id,
                "level": level,
                "deposit_amount": str(deposit_amount),
                "bonus_amount": str(reward_amount),
                "invoice_id": source_invoice_id,
                "external_payment_id": external_payment_id,
            },
        )
        db.add(ledger_tx)
        await db.flush()

        # Обновляем баланс реферера на основе ledger
        referrer_user = await db.get(User, referrer.id)
        if referrer_user:
            new_balance = await get_balance_usdt(db, referrer_user.id)
            referrer_user.balance_usdt = new_balance

