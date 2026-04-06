"""
NOWPayments IPN: нормализация статусов и проверка суммы (tolerance).

Сравнение для tolerance (обе стороны в USDT по смыслу депозита):
- aggregated actually_paid из IPN — фактически получено провайдером.
- expected_deposit_amount_for_tolerance(invoice) — номинал депозита USDT (поля expected_amount
  или price_amount; для новых инвойсов оба задаются при создании как выбранная пользователем сумма).

Зачисление на баланс: номинал депозита при прохождении tolerance; факт IPN хранится в
invoice.actually_paid_amount (см. payment_service.apply_payment_to_balance).
"""
from __future__ import annotations

from decimal import Decimal

from src.models.payment_invoice import PaymentInvoice

# Успешные статусы NOWPayments IPN, при которых допускается попытка зачисления
# (после проверки tolerance и is_balance_applied).
# Включаем `paid`: внутренняя статистика/админка ожидают finished|paid; NOWPayments может прислать paid.
NOWPAYMENTS_CREDIT_ELIGIBLE_STATUSES = frozenset(
    {"finished", "sent", "confirmed", "paid"}
)

NOWPAYMENTS_PARTIAL_STATUS = "partially_paid"

NOWPAYMENTS_TERMINAL_NEGATIVE_STATUSES = frozenset({"failed", "expired", "refunded"})

# Допустимое отклонение: зачисление, если actually_paid >= expected * FACTOR (0.5%).
DEPOSIT_PAID_TOLERANCE_FACTOR = Decimal("0.995")


def normalize_ipn_payment_status(payload: dict) -> str:
    """Единый источник: payment_status или status."""
    raw = payload.get("payment_status") or payload.get("status") or ""
    return str(raw).strip().lower()


def map_ipn_to_invoice_status_for_non_credit(ipn_status: str) -> str | None:
    """
    Статус для записи в PaymentInvoice без зачисления (terminal / partial).
    None — не менять поле status инвойса.
    """
    s = ipn_status.lower()
    if s == NOWPAYMENTS_PARTIAL_STATUS:
        return "partially_paid"
    if s in NOWPAYMENTS_TERMINAL_NEGATIVE_STATUSES:
        return s
    return None


def expected_deposit_amount_for_tolerance(invoice: PaymentInvoice) -> Decimal:
    """
    Номинал депозита USDT для порога и зачисления.

    Приоритет: expected_amount, иначе price_amount (старые строки).
    """
    if invoice.expected_amount is not None and invoice.expected_amount > 0:
        return Decimal(invoice.expected_amount)
    return Decimal(invoice.price_amount)


def is_paid_amount_sufficient_for_credit(
    actually_paid: Decimal,
    expected: Decimal,
    factor: Decimal = DEPOSIT_PAID_TOLERANCE_FACTOR,
) -> bool:
    if expected <= 0:
        return False
    threshold = (expected * factor).quantize(Decimal("0.000001"))
    return actually_paid >= threshold
