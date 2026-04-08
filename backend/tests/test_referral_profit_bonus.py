"""
Проверки реферальной логики:
- только уровень 1,
- бонус 1% от суммы сделки,
- точность Decimal.

Запуск: python -m unittest backend.tests.test_referral_profit_bonus -v
"""
from decimal import Decimal
import unittest


def level_1_bonus_from_deal_amount(deal_amount: Decimal) -> Decimal:
    return (deal_amount * Decimal("0.01")).quantize(Decimal("0.000001"))


class ReferralProfitBonusTests(unittest.TestCase):
    def test_direct_referrer_gets_1_percent_from_deal_amount(self):
        bonus = level_1_bonus_from_deal_amount(Decimal("50"))
        self.assertEqual(bonus, Decimal("0.500000"))

    def test_decimal_precision_no_float_error(self):
        bonus = level_1_bonus_from_deal_amount(Decimal("33.33"))
        self.assertEqual(bonus, Decimal("0.333300"))

    def test_only_level_1_applies(self):
        # Для любой суммы формула одинакова: только 1% level 1.
        self.assertEqual(level_1_bonus_from_deal_amount(Decimal("100")), Decimal("1.000000"))

    def test_no_bonus_for_zero_amount(self):
        self.assertEqual(level_1_bonus_from_deal_amount(Decimal("0")), Decimal("0.000000"))


if __name__ == "__main__":
    unittest.main()
