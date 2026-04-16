"""
Одноразовое исправление: сделка №11 должна давать 8% по телу участия,
при закрытии могла быть зафиксирована 3% в deal_participations.profit_amount
и referral_rewards.amount.

Не меняет глобальную логику приложения. Только deal.number == 11 (по умолчанию).

Режимы:
  --dry-run   только отчёт (по умолчанию)
  --apply     выполнить правки + компенсации

Из корня backend:
  set PYTHONPATH=.
  python scripts/fix_deal11_profit_8pct.py --dry-run
  python scripts/fix_deal11_profit_8pct.py --apply

Затронутые сущности при --apply:
  - deals: profit_percent
  - deal_participations: profit_amount (только status=in_progress_payout)
  - referral_rewards: amount (PENDING и опционально MISSED), без изменения PAID
  - ledger_transactions: новые строки PROFIT / REFERRAL_BONUS (компенсации)
  - users.balance_usdt: пересчёт кэша для затронутых user_id
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from decimal import Decimal
from pathlib import Path

# Запуск как файл: PYTHONPATH должен указывать на каталог backend (где лежит src/).
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import async_session_maker
from src.models.deal import (
    DEAL_STATUS_CLOSED,
    DEAL_STATUS_COMPLETED,
    Deal,
)
from src.models.deal_participation import (
    PARTICIPATION_STATUS_COMPLETED,
    PARTICIPATION_STATUS_IN_PROGRESS,
    DealParticipation,
)
from src.models.ledger_transaction import LedgerTransaction
from src.models.referral_reward import ReferralReward
from src.models.referral_reward import STATUS_MISSED, STATUS_PAID, STATUS_PENDING
from src.services.ledger_service import (
    LEDGER_TYPE_PROFIT,
    LEDGER_TYPE_REFERRAL_BONUS,
    sync_user_balance,
)
from src.services.referral_service import INVEST_REFERRAL_LEVEL_PERCENTS

DEFAULT_DEAL_NUMBER = 11
OLD_PROFIT_PCT = Decimal("3")
NEW_PROFIT_PCT = Decimal("8")
DELTA_USER_PCT = NEW_PROFIT_PCT - OLD_PROFIT_PCT  # 5% от тела — дельта по прибыли

OP_PROFIT_COMP = "deal11_profit_delta_3_to_8"
OP_REF_COMP = "deal11_referral_delta_3_to_8"

Q6 = Decimal("0.000001")


def _profit_from_body(amount: Decimal, pct: Decimal) -> Decimal:
    return (amount * pct / Decimal("100")).quantize(Q6)


def _referral_for_profit(profit: Decimal, level: int) -> Decimal:
    if level < 1 or level > len(INVEST_REFERRAL_LEVEL_PERCENTS):
        return Decimal("0").quantize(Q6)
    pct = INVEST_REFERRAL_LEVEL_PERCENTS[level - 1]
    return (profit * pct / Decimal("100")).quantize(Q6)


async def _ledger_exists(
    db: AsyncSession,
    *,
    user_id: int,
    tx_type: str,
    meta: dict,
) -> bool:
    res = await db.execute(
        select(LedgerTransaction.id)
        .where(
            LedgerTransaction.user_id == user_id,
            LedgerTransaction.type == tx_type,
            LedgerTransaction.metadata_json.contains(meta),
        )
        .limit(1)
    )
    return res.scalar_one_or_none() is not None


async def run(*, deal_number: int, apply: bool) -> None:
    async with async_session_maker() as db:
        dres = await db.execute(select(Deal).where(Deal.number == deal_number))
        deal = dres.scalar_one_or_none()
        if not deal:
            print(f"Сделка с number={deal_number} не найдена.")
            return

        pres = await db.execute(
            select(DealParticipation).where(DealParticipation.deal_id == deal.id)
        )
        parts = list(pres.scalars().all())

        rres = await db.execute(
            select(ReferralReward).where(ReferralReward.deal_id == deal.id)
        )
        rewards = list(rres.scalars().all())

        by_status: dict[str, int] = {}
        for p in parts:
            by_status[p.status] = by_status.get(p.status, 0) + 1

        print("=== Анализ ===")
        print(f"deal.id={deal.id} number={deal.number} status={deal.status}")
        print(f"deal.profit_percent={deal.profit_percent} legacy percent={deal.percent}")
        print(f"Участий по статусам: {by_status}")
        print("--- deal_participations (id, user_id, status, amount, profit_amount) ---")
        for p in sorted(parts, key=lambda x: x.id):
            print(
                f"  p={p.id} user={p.user_id} st={p.status} "
                f"amount={p.amount} profit_amount={p.profit_amount}"
            )
        print("--- referral_rewards (id, from, to, level, status, amount) ---")
        for r in sorted(rewards, key=lambda x: x.id):
            print(
                f"  rw={r.id} from={r.from_user_id} to={r.to_user_id} "
                f"L{r.level} st={r.status} amt={r.amount}"
            )

        inprog = [p for p in parts if p.status == PARTICIPATION_STATUS_IN_PROGRESS]
        completed = [p for p in parts if p.status == PARTICIPATION_STATUS_COMPLETED]

        if completed and not inprog:
            strategy = (
                "Все выплаты по участиям уже completed — не трогаем старые суммы в deal_participations; "
                "доначисляем 5% прибыли и дельту рефералки отдельными ledger-записями."
            )
        elif inprog and not completed:
            strategy = (
                "Выплаты ещё не completed — безопасно пересчитать profit_amount на 8% и PENDING-рефералки; "
                "ledger по телу/прибыли сформирует process_pending_payouts позже из обновлённых сумм."
            )
        else:
            strategy = (
                "Смешанный режим: для in_progress_payout — пересчёт profit_amount и PENDING; "
                "для completed — доначисления в ledger (прибыль 5% и дельта по PAID рефералке)."
            )

        print("\n=== Вывод ===")
        print(f"Стратегия: {strategy}")
        if not apply:
            print("\nРежим dry-run: изменений нет. Для применения: --apply")
            await db.rollback()
            return

        if deal.status not in (DEAL_STATUS_CLOSED, DEAL_STATUS_COMPLETED):
            print(
                f"\nОТКАЗ: сделка в status={deal.status}, ожидается closed/completed. "
                "Не применяем правки, чтобы не трогать активный сбор."
            )
            await db.rollback()
            return

        part_by_user: dict[int, DealParticipation] = {p.user_id: p for p in parts}

        deal.profit_percent = NEW_PROFIT_PCT

        for p in inprog:
            new_profit = _profit_from_body(p.amount, NEW_PROFIT_PCT)
            p.profit_amount = new_profit

        for rw in rewards:
            if rw.status != STATUS_PENDING:
                continue
            inv = part_by_user.get(rw.from_user_id)
            if not inv:
                continue
            profit_8 = _profit_from_body(inv.amount, NEW_PROFIT_PCT)
            rw.amount = _referral_for_profit(profit_8, rw.level)

        for rw in rewards:
            if rw.status != STATUS_MISSED:
                continue
            if OLD_PROFIT_PCT == 0:
                continue
            ratio = NEW_PROFIT_PCT / OLD_PROFIT_PCT
            rw.amount = (rw.amount * ratio).quantize(Q6)

        affected_users: set[int] = set()

        for p in completed:
            delta = _profit_from_body(p.amount, DELTA_USER_PCT)
            if delta <= 0:
                continue
            meta = {"op": OP_PROFIT_COMP, "participation_id": p.id, "deal_number": deal.number}
            if await _ledger_exists(db, user_id=p.user_id, tx_type=LEDGER_TYPE_PROFIT, meta=meta):
                continue
            db.add(
                LedgerTransaction(
                    user_id=p.user_id,
                    type=LEDGER_TYPE_PROFIT,
                    amount_usdt=delta,
                    metadata_json={
                        **meta,
                        "reason": "correction 3% -> 8% on closed deal participation",
                        "delta_percent": str(DELTA_USER_PCT),
                    },
                )
            )
            affected_users.add(p.user_id)

        for rw in rewards:
            if rw.status != STATUS_PAID:
                continue
            if OLD_PROFIT_PCT == 0:
                continue
            delta_ref = (rw.amount * (NEW_PROFIT_PCT - OLD_PROFIT_PCT) / OLD_PROFIT_PCT).quantize(Q6)
            if delta_ref <= 0:
                continue
            meta = {"op": OP_REF_COMP, "referral_reward_id": rw.id, "deal_number": deal.number}
            if await _ledger_exists(
                db, user_id=rw.to_user_id, tx_type=LEDGER_TYPE_REFERRAL_BONUS, meta=meta
            ):
                continue
            db.add(
                LedgerTransaction(
                    user_id=rw.to_user_id,
                    type=LEDGER_TYPE_REFERRAL_BONUS,
                    amount_usdt=delta_ref,
                    metadata_json={
                        **meta,
                        "reason": "referral reward was from 3% investor profit; align to 8%",
                    },
                )
            )
            affected_users.add(rw.to_user_id)

        await db.flush()

        for uid in affected_users:
            await sync_user_balance(db, uid)

        await db.commit()
        print("\nПрименено: deals.profit_percent, участия in_progress, PENDING/MISSED рефералка, ledger-компенсации, балансы.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Fix deal #11 profit 3%% -> 8%% (point fix).")
    ap.add_argument("--deal-number", type=int, default=DEFAULT_DEAL_NUMBER)
    ap.add_argument(
        "--apply",
        action="store_true",
        help="Выполнить изменения (без флага — только отчёт).",
    )
    args = ap.parse_args()
    asyncio.run(run(deal_number=args.deal_number, apply=args.apply))


if __name__ == "__main__":
    main()
