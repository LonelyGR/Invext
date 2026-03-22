"""
Проверка формулы реферального бонуса: 0.5% от фактической прибыли реферала по сделке.

Запуск: python -m unittest backend.tests.test_referral_profit_bonus -v
(из корня репозитория, при необходимости PYTHONPATH=backend)
"""
from decimal import Decimal
import unittest


def level_bonus_from_user_profit(user_profit: Decimal, level_pct: Decimal = Decimal("0.5")) -> Decimal:
    """Как в referral_service: pct% от прибыли, квантование 6 знаков."""
    return (user_profit * level_pct / Decimal("100")).quantize(Decimal("0.000001"))


class ReferralProfitBonusTests(unittest.TestCase):
    def test_example_50_usd_3pct_profit(self):
        investment = Decimal("50")
        deal_profit_pct = Decimal("3")
        user_profit = investment * deal_profit_pct / Decimal("100")
        self.assertEqual(user_profit, Decimal("1.5"))
        bonus = level_bonus_from_user_profit(user_profit)
        self.assertEqual(bonus, Decimal("0.007500"))


if __name__ == "__main__":
    unittest.main()
