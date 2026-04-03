"""
Агрегация actually_paid по нескольким IPN NOWPayments для одного order_id.

Один invoice может получить несколько webhook с разными payment_id (в т.ч. child с
parent_payment_id). Сумма для tolerance и зачисления берётся как сумма
max(actually_paid) по каждому уникальному payment_id по всем сохранённым событиям,
исключая терминальные неуспешные статусы в отдельном событии.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.payment_webhook_event import PROVIDER_NOWPAYMENTS, PaymentWebhookEvent
from src.models.payment_invoice import PaymentInvoice
from src.services.nowpayments_ipn import (
    NOWPAYMENTS_TERMINAL_NEGATIVE_STATUSES,
    normalize_ipn_payment_status,
)


def parse_actually_paid_for_ipn(raw: object) -> Decimal | None:
    """Фактически оплаченная сумма из поля IPN; None если нет или неположительное."""
    if raw is None:
        return None
    try:
        d = Decimal(str(raw))
        return d if d > 0 else None
    except Exception:
        return None


def _payment_id_key(raw: object) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s if s else None


def aggregate_nowpayments_paid_from_payload_list(
    payloads: list[dict[str, Any]],
) -> tuple[Decimal, list[str], str]:
    """
    Чистая агрегация по списку payload (порядок событий не влияет на итог).

    - Для каждого payment_id берётся максимум actually_paid среди учитываемых событий
      (повторы одного payment_id не суммируются).
    - События с payment_status в TERMINAL_NEGATIVE не дают вклада в сумму.
    - События без валидного payment_id пропускаются (нечего дедуплицировать).
    - parent_payment_id не нужен для суммы: parent и child — разные payment_id,
      оба попадают в словарь отдельно.
    """
    per_pid_max: dict[str, Decimal] = {}
    skipped_terminal = 0
    skipped_no_pid = 0
    skipped_no_amount = 0

    for payload in payloads:
        st = normalize_ipn_payment_status(payload)
        if st in NOWPAYMENTS_TERMINAL_NEGATIVE_STATUSES:
            skipped_terminal += 1
            continue
        pid = _payment_id_key(payload.get("payment_id"))
        if pid is None:
            skipped_no_pid += 1
            continue
        amt = parse_actually_paid_for_ipn(payload.get("actually_paid"))
        if amt is None:
            skipped_no_amount += 1
            continue
        prev = per_pid_max.get(pid)
        per_pid_max[pid] = amt if prev is None else max(prev, amt)

    total = sum(per_pid_max.values(), Decimal("0"))
    pids_sorted = sorted(per_pid_max.keys())
    explanation = (
        f"sum(max(actually_paid) per payment_id) over {len(payloads)} payload(s); "
        f"unique_payment_ids={len(pids_sorted)} total={total}; "
        f"skipped terminal={skipped_terminal} no_payment_id={skipped_no_pid} no_amount={skipped_no_amount}"
    )
    return total, pids_sorted, explanation


async def compute_aggregated_nowpayments_paid(
    db: AsyncSession,
    invoice: PaymentInvoice,
    current_payload: dict[str, Any] | None,
) -> tuple[Decimal, list[str], str]:
    """
    Агрегированная сумма по всем сохранённым webhook для order_id инвойса.

    current_payload зарезервирован для явной связи с вызовом из webhook (строка уже в БД
    после flush текущего PaymentWebhookEvent).
    """
    _ = current_payload  # документирующий параметр; источник истины — payment_webhook_events
    order_id = invoice.order_id
    result = await db.execute(
        select(PaymentWebhookEvent.payload_json)
        .where(
            PaymentWebhookEvent.provider == PROVIDER_NOWPAYMENTS,
            PaymentWebhookEvent.order_id == order_id,
        )
        .order_by(PaymentWebhookEvent.id.asc())
    )
    rows = result.all()
    payloads = [row[0] for row in rows if isinstance(row[0], dict)]
    return aggregate_nowpayments_paid_from_payload_list(payloads)
