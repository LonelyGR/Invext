"""
Реферальные бонусы:

1) ДЕПОЗИТНАЯ ЛИНИЯ (deposit_referral):
   - отключена.

2) ИНВЕСТИЦИОННАЯ ЛИНИЯ (investment_referral):
   - только 1 уровень (прямой реферер);
   - бонус 1% от суммы входа реферала в сделку;
   - начисление в момент успешного открытия участия в сделке.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models import Deal, DealParticipation, ReferralReward, User
from src.models.referral_reward import STATUS_PENDING

# Инвестиционная линия: только прямой реферер, 1% от суммы участия в сделке.
REFERRAL_LEVEL_1_PERCENT = Decimal("0.01")
REFERRAL_LEVEL_1 = 1
REFERRAL_AMOUNT_QUANT = Decimal("0.000001")


async def apply_referral_rewards_for_deposit(
    db: AsyncSession,
    from_user: User,
    deposit_amount: Decimal,
    source_invoice_id: int,
    external_payment_id: str,
) -> None:
    """
    Депозитная реферальная линия отключена.
    Функция оставлена для обратной совместимости вызовов.
    """
    _ = (db, from_user, deposit_amount, source_invoice_id, external_payment_id)
    return


async def apply_referral_rewards_for_investment(
    db: AsyncSession,
    investor: User,
    deal: Deal,
    deal_amount_usdt: Decimal,
) -> None:
    """
    Инвестиционная реферальная линия:
    - только прямой реферер (level=1);
    - бонус = 1% от суммы участия реферала в сделке;
    - создаётся запись ReferralReward со статусом PENDING;
    - фактическое зачисление происходит в process_pending_payouts.
    """
    if deal_amount_usdt <= 0:
        return

    if not investor.referrer_id:
        return

    if investor.referrer_id == investor.id:
        return

    referrer = await db.get(User, investor.referrer_id)
    if not referrer:
        return

    existing_result = await db.execute(
        select(ReferralReward.id).where(
            ReferralReward.deal_id == deal.id,
            ReferralReward.from_user_id == investor.id,
            ReferralReward.to_user_id == referrer.id,
            ReferralReward.level == REFERRAL_LEVEL_1,
        )
    )
    if existing_result.scalar_one_or_none() is not None:
        return

    reward_amount = (deal_amount_usdt * REFERRAL_LEVEL_1_PERCENT).quantize(REFERRAL_AMOUNT_QUANT)
    if reward_amount <= 0:
        return

    db.add(
        ReferralReward(
            deal_id=deal.id,
            from_user_id=investor.id,
            to_user_id=referrer.id,
            level=REFERRAL_LEVEL_1,
            amount=reward_amount,
            status=STATUS_PENDING,
        )
    )


async def get_potential_referral_bonuses_for_deal(
    db: AsyncSession,
    deal: Deal,
) -> dict[int, Decimal]:
    """
    Рассчитать потенциальные реферальные бонусы по текущей сделке.
    Для новой логики: 1% от суммы участия только прямому рефереру.

    Возвращает словарь {referrer_user_id: сумма_бонуса}.
    Ничего не записывает в БД, только считает по текущим участиям.
    """
    # Все участия в сделке.
    participations_result = await db.execute(
        select(DealParticipation).where(DealParticipation.deal_id == deal.id)
    )
    participations = list(participations_result.scalars().all())
    if not participations:
        return {}

    bonuses: dict[int, Decimal] = {}
    for p in participations:
        investor_id = p.user_id
        amount = p.amount
        if amount <= 0:
            continue

        investor = await db.get(User, investor_id)
        if not investor or not investor.referrer_id:
            continue
        if investor.referrer_id == investor.id:
            continue
        reward_amount = (amount * REFERRAL_LEVEL_1_PERCENT).quantize(REFERRAL_AMOUNT_QUANT)
        if reward_amount <= 0:
            continue
        bonuses[investor.referrer_id] = bonuses.get(investor.referrer_id, Decimal("0")) + reward_amount

    return bonuses