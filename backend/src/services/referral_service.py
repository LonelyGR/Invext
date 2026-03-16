"""
Реферальные бонусы:

1) ДЕПОЗИТНАЯ ЛИНИЯ (deposit_referral):
   - 1 уровень, 3% от суммы депозита реферала.
   - Начисление только с подтверждённого депозита (DEPOSIT в ledger).

2) ИНВЕСТИЦИОННАЯ ЛИНИЯ (investment_referral):
   - До 3 уровней, каждому уровню 0.5% от суммы инвестиции.
   - Начисление только если получатель бонуса сам участвовал в этой сделке.
   - Если не участвовал — бонус не начисляется, но фиксируется как упущенный.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import Deal, DealParticipation, LedgerTransaction, ReferralReward, User
from src.models.referral_reward import STATUS_MISSED
from src.services.ledger_service import LEDGER_TYPE_REFERRAL_BONUS, get_balance_usdt

# Депозитная линия: только 1 уровень, 3%
DEPOSIT_REFERRAL_PCT = Decimal("3")

# Инвестиционная линия: 3 уровня по 0.5%
INVEST_REFERRAL_LEVEL_PERCENTS: List[Decimal] = [
    Decimal("0.5"),
    Decimal("0.5"),
    Decimal("0.5"),
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
    - Только 1 уровень: 3% от суммы депозита.
    - История начислений хранится в ledger (type=REFERRAL_BONUS, metadata_json.source='deposit').
    """
    if deposit_amount <= 0:
        return

    referrers = await _get_referrer_chain(db, from_user.id, max_levels=1)
    if not referrers:
        return

    referrer = referrers[0]
    reward_amount = (deposit_amount * DEPOSIT_REFERRAL_PCT / Decimal("100")).quantize(Decimal("0.01"))
    if reward_amount <= 0:
        return

    ledger_tx = LedgerTransaction(
        user_id=referrer.id,
        type=LEDGER_TYPE_REFERRAL_BONUS,
        amount_usdt=reward_amount,
        metadata_json={
            "source": "deposit",
            "from_user_id": from_user.id,
            "level": 1,
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


async def apply_referral_rewards_for_investment(
    db: AsyncSession,
    investor: User,
    deal: Deal,
    investment_amount: Decimal,
) -> None:
    """
    Инвестиционная реферальная линия:
    - до 3 уровней, каждому уровню 0.5% от суммы инвестиции;
    - бонус начисляется только если реферер сам участвует в этой сделке;
    - иначе фиксируется запись ReferralReward со статусом MISSED (упущенная прибыль).
    """
    if investment_amount <= 0:
        return

    referrers = await _get_referrer_chain(db, investor.id, MAX_LEVELS)
    if not referrers:
        return

    # Загрузим всех участников сделки разом, чтобы быстро проверять участие.
    participations_result = await db.execute(
        select(DealParticipation)
        .options(selectinload(DealParticipation.user))
        .where(DealParticipation.deal_id == deal.id)
    )
    participations = participations_result.scalars().all()
    participant_user_ids = {p.user_id for p in participations}

    for level_index, referrer in enumerate(referrers):
        level = level_index + 1
        if level > len(INVEST_REFERRAL_LEVEL_PERCENTS):
            break

        pct = INVEST_REFERRAL_LEVEL_PERCENTS[level_index]
        reward_amount = (investment_amount * pct / Decimal("100")).quantize(Decimal("0.01"))
        if reward_amount <= 0:
            continue

        # Проверяем: сам ли реферер участвует в этой сделке.
        if referrer.id in participant_user_ids:
            # Начисляем бонус в ledger.
            ledger_tx = LedgerTransaction(
                user_id=referrer.id,
                type=LEDGER_TYPE_REFERRAL_BONUS,
                amount_usdt=reward_amount,
                metadata_json={
                    "source": "investment",
                    "from_user_id": investor.id,
                    "level": level,
                    "deal_id": deal.id,
                    "investment_amount": str(investment_amount),
                    "bonus_amount": str(reward_amount),
                },
            )
            db.add(ledger_tx)
            await db.flush()

            referrer_user = await db.get(User, referrer.id)
            if referrer_user:
                new_balance = await get_balance_usdt(db, referrer_user.id)
                referrer_user.balance_usdt = new_balance
        else:
            # Фиксируем упущенную прибыль.
            missed = ReferralReward(
                deal_id=deal.id,
                from_user_id=investor.id,
                to_user_id=referrer.id,
                level=level,
                amount=reward_amount,
                status=STATUS_MISSED,
            )
            db.add(missed)