"""
Реферальные бонусы:

1) ДЕПОЗИТНАЯ ЛИНИЯ (deposit_referral):
   - отключена.

2) ИНВЕСТИЦИОННАЯ ЛИНИЯ (investment_referral):
   - До 10 уровней, каждому уровню 0.5% от фактической прибыли реферала по сделке
     (после расчёта profit_amount при закрытии сделки).
   - Начисление только если получатель бонуса сам участвовал в этой сделке.
   - Если не участвовал — бонус не начисляется, но фиксируется как упущенный.
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.models import Deal, DealParticipation, ReferralReward, User
from src.models.referral_reward import STATUS_MISSED, STATUS_PENDING

# Инвестиционная линия: 10 уровней по 0.5%
INVEST_REFERRAL_LEVEL_PERCENTS: List[Decimal] = [Decimal("0.5")] * 10
MAX_LEVELS = 10


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
    origin_user_id = user_id
    current_id: Optional[int] = user_id
    visited: set[int] = {origin_user_id}

    for _ in range(max_levels):
        if current_id is None:
            break

        res = await db.execute(select(User).where(User.id == current_id))
        u = res.scalar_one_or_none()
        if not u or u.referrer_id is None:
            break

        # Самореферал и очевидные циклы
        if u.referrer_id == u.id:
            break

        next_referrer_id = u.referrer_id
        # Защита от циклов и возврата к исходному пользователю.
        if next_referrer_id in visited:
            break

        res_ref = await db.execute(select(User).where(User.id == next_referrer_id))
        referrer = res_ref.scalar_one_or_none()
        if not referrer:
            break
        if referrer.id == origin_user_id:
            break
        chain.append(referrer)
        visited.add(referrer.id)
        current_id = referrer.id

    return chain


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
    user_profit_usdt: Decimal,
) -> None:
    """
    Инвестиционная реферальная линия:
    - до 10 уровней, каждому уровню 0.5% от фактической прибыли инвестора по сделке
      (user_profit_usdt — то же, что profit_amount у участия после закрытия сделки);
    - если реферер участвует в этой сделке -> создаётся PENDING бонус
      (фактическое начисление происходит вместе с payout через 24 часа);
    - иначе фиксируется запись ReferralReward со статусом MISSED (упущенная прибыль).

    Вызывается из close_deal_flow после расчёта profit_amount по участию (не при вводе суммы инвестиции).
    """
    if user_profit_usdt <= 0:
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

    # Защита от дублей:
    # собираем уже созданные referral_rewards по этой сделке/инвестору и пропускаем дубли.
    referrer_ids = [r.id for r in referrers]
    existing_rewards_result = await db.execute(
        select(ReferralReward.to_user_id, ReferralReward.level).where(
            ReferralReward.deal_id == deal.id,
            ReferralReward.from_user_id == investor.id,
            ReferralReward.to_user_id.in_(referrer_ids),
        )
    )
    existing_reward_keys = {(int(r[0]), int(r[1])) for r in existing_rewards_result.all()}

    for level_index, referrer in enumerate(referrers):
        level = level_index + 1
        if level > len(INVEST_REFERRAL_LEVEL_PERCENTS):
            break
        if (referrer.id, level) in existing_reward_keys:
            continue

        pct = INVEST_REFERRAL_LEVEL_PERCENTS[level_index]
        reward_amount = (user_profit_usdt * pct / Decimal("100")).quantize(Decimal("0.000001"))
        if reward_amount <= 0:
            continue

        # Проверяем: сам ли реферер участвует в этой сделке.
        if referrer.id in participant_user_ids:
            pending = ReferralReward(
                deal_id=deal.id,
                from_user_id=investor.id,
                to_user_id=referrer.id,
                level=level,
                amount=reward_amount,
                status=STATUS_PENDING,
            )
            db.add(pending)
        else:
            missed = ReferralReward(
                deal_id=deal.id,
                from_user_id=investor.id,
                to_user_id=referrer.id,
                level=level,
                amount=reward_amount,
                status=STATUS_MISSED,
            )
            db.add(missed)


async def get_potential_referral_bonuses_for_deal(
    db: AsyncSession,
    deal: Deal,
) -> dict[int, Decimal]:
    """
    Рассчитать потенциальные реферальные бонусы по текущей сделке для пользователей,
    которые ещё НЕ участвуют в ней, но могут получить бонус, если успеют войти.

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

    participant_user_ids = {p.user_id for p in participations}

    bonuses: dict[int, Decimal] = {}

    profit_pct = deal.profit_percent or deal.percent
    for p in participations:
        investor_id = p.user_id
        amount = p.amount
        if amount <= 0:
            continue

        referrers = await _get_referrer_chain(db, investor_id, MAX_LEVELS)
        if not referrers:
            continue

        # Оценка потенциальной прибыли по текущему % сделки (для напоминания до закрытия).
        if profit_pct is None:
            estimated_profit = Decimal("0")
        else:
            estimated_profit = (
                amount * Decimal(str(profit_pct)) / Decimal("100")
            ).quantize(Decimal("0.000001"))

        for level_index, referrer in enumerate(referrers):
            level = level_index + 1
            if level > len(INVEST_REFERRAL_LEVEL_PERCENTS):
                break

            # Нас интересуют только те, кто ПОКА не участвует в сделке.
            if referrer.id in participant_user_ids:
                continue

            pct = INVEST_REFERRAL_LEVEL_PERCENTS[level_index]
            reward_amount = (estimated_profit * pct / Decimal("100")).quantize(Decimal("0.000001"))
            if reward_amount <= 0:
                continue

            bonuses[referrer.id] = bonuses.get(referrer.id, Decimal("0")) + reward_amount

    return bonuses