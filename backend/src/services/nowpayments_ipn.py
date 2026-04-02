"""
NOWPayments IPN: нормализация статусов и проверка суммы (tolerance).

Единое место для литералов статусов, чтобы webhook и остальной код не расходились.

Сравнение для tolerance (совместимые величины — обе в валюте оплаты pay_currency):
- actually_paid (IPN) — фактически получено в крипте (USDT BEP20 и т.д.).
- expected_amount (инвойс) — ожидаемая сумма к оплате в той же валюте (= pay_amount при создании).
Если expected_amount не задан (старые записи), fallback: price_amount (заказ в price_currency,
обычно usd; численно 1:1 с намерением пополнения в USDT).

Зачисление на баланс по-прежнему использует actually_paid как сумму в USDT (см. payment_service).
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
    Ожидаемая сумма для сравнения с actually_paid (обе стороны — в валюте оплаты, pay_currency).

    Приоритет: expected_amount (crypto), иначе price_amount (fallback для совместимости со старыми строками).
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
