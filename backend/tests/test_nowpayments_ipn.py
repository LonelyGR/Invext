"""
Тесты нормализации IPN NOWPayments и tolerance (без БД).

Запуск из корня: python -m unittest backend.tests.test_nowpayments_ipn -v
(PYTHONPATH может понадобиться включить backend.)
"""
from decimal import Decimal
import unittest

from src.services.nowpayments_ipn import (
    NOWPAYMENTS_CREDIT_ELIGIBLE_STATUSES,
    NOWPAYMENTS_PARTIAL_STATUS,
    NOWPAYMENTS_TERMINAL_NEGATIVE_STATUSES,
    expected_deposit_amount_for_tolerance,
    is_paid_amount_sufficient_for_credit,
    normalize_ipn_payment_status,
)
from unittest.mock import MagicMock


class NowpaymentsIpnTests(unittest.TestCase):
    def test_normalize_ipn_prefers_payment_status(self):
        self.assertEqual(
            normalize_ipn_payment_status({"payment_status": "Finished", "status": "waiting"}),
            "finished",
        )

    def test_credit_eligible_contains_finished_sent_confirmed_paid(self):
        self.assertTrue({"finished", "sent", "confirmed", "paid"}.issubset(NOWPAYMENTS_CREDIT_ELIGIBLE_STATUSES))

    def test_partial_is_distinct(self):
        self.assertEqual(NOWPAYMENTS_PARTIAL_STATUS, "partially_paid")

    def test_terminal_negative(self):
        self.assertIn("failed", NOWPAYMENTS_TERMINAL_NEGATIVE_STATUSES)

    def test_tolerance_sufficient_at_995(self):
        self.assertTrue(
            is_paid_amount_sufficient_for_credit(Decimal("99.5"), Decimal("100"), Decimal("0.995"))
        )

    def test_tolerance_insufficient_below_threshold(self):
        self.assertFalse(
            is_paid_amount_sufficient_for_credit(Decimal("99.4"), Decimal("100"), Decimal("0.995"))
        )

    def test_expected_for_tolerance_prefers_expected_amount_crypto(self):
        inv = MagicMock()
        inv.price_amount = Decimal("50")
        inv.expected_amount = Decimal("50.12345678")
        self.assertEqual(expected_deposit_amount_for_tolerance(inv), Decimal("50.12345678"))

    def test_expected_for_tolerance_fallback_price_when_no_expected(self):
        inv = MagicMock()
        inv.price_amount = Decimal("50")
        inv.expected_amount = None
        self.assertEqual(expected_deposit_amount_for_tolerance(inv), Decimal("50"))


if __name__ == "__main__":
    unittest.main()
