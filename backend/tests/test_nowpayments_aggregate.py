"""
Unit-тесты агрегации actually_paid по нескольким IPN (без БД).

Запуск из корня репозитория:
  python -m unittest backend.tests.test_nowpayments_aggregate -v
с PYTHONPATH, включающим backend (или из каталога backend: python -m unittest tests.test_nowpayments_aggregate -v).
"""
from decimal import Decimal
import unittest

from src.services.nowpayments_aggregate import aggregate_nowpayments_paid_from_payload_list


class NowpaymentsAggregateTests(unittest.TestCase):
    def test_one_partial_insufficient_alone(self):
        payloads = [
            {
                "payment_id": "a",
                "payment_status": "partially_paid",
                "actually_paid": "40",
            }
        ]
        total, pids, _note = aggregate_nowpayments_paid_from_payload_list(payloads)
        self.assertEqual(total, Decimal("40"))
        self.assertEqual(pids, ["a"])

    def test_one_finished_sufficient_amount(self):
        payloads = [
            {
                "payment_id": "x",
                "payment_status": "finished",
                "actually_paid": "100",
            }
        ]
        total, pids, _ = aggregate_nowpayments_paid_from_payload_list(payloads)
        self.assertEqual(total, Decimal("100"))
        self.assertEqual(pids, ["x"])

    def test_parent_and_child_distinct_payment_ids_sum(self):
        payloads = [
            {
                "payment_id": "main-1",
                "parent_payment_id": None,
                "payment_status": "partially_paid",
                "actually_paid": "30",
            },
            {
                "payment_id": "child-2",
                "parent_payment_id": "main-1",
                "payment_status": "partially_paid",
                "actually_paid": "70",
            },
        ]
        total, pids, _ = aggregate_nowpayments_paid_from_payload_list(payloads)
        self.assertEqual(total, Decimal("100"))
        self.assertEqual(set(pids), {"child-2", "main-1"})

    def test_duplicate_payment_id_does_not_double_count(self):
        payloads = [
            {
                "payment_id": "same",
                "payment_status": "partially_paid",
                "actually_paid": "50",
            },
            {
                "payment_id": "same",
                "payment_status": "partially_paid",
                "actually_paid": "50",
            },
        ]
        total, _, _ = aggregate_nowpayments_paid_from_payload_list(payloads)
        self.assertEqual(total, Decimal("50"))

    def test_repeat_webhook_increases_max_not_sum(self):
        payloads = [
            {
                "payment_id": "same",
                "payment_status": "partially_paid",
                "actually_paid": "40",
            },
            {
                "payment_id": "same",
                "payment_status": "partially_paid",
                "actually_paid": "60",
            },
        ]
        total, _, _ = aggregate_nowpayments_paid_from_payload_list(payloads)
        self.assertEqual(total, Decimal("60"))

    def test_terminal_negative_excluded_from_sum(self):
        payloads = [
            {
                "payment_id": "p1",
                "payment_status": "partially_paid",
                "actually_paid": "50",
            },
            {
                "payment_id": "p2",
                "payment_status": "failed",
                "actually_paid": "999",
            },
        ]
        total, pids, _ = aggregate_nowpayments_paid_from_payload_list(payloads)
        self.assertEqual(total, Decimal("50"))
        self.assertEqual(pids, ["p1"])


if __name__ == "__main__":
    unittest.main()
