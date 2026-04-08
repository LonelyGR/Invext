from decimal import Decimal
from pathlib import Path
import sys
import unittest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from src.models.deal import Deal
from src.models.referral_reward import STATUS_PENDING
from src.models.user import User
from src.services.referral_service import apply_referral_rewards_for_investment


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _FakeDb:
    def __init__(self, *, referrer=None, existing_reward_id=None):
        self._referrer = referrer
        self._existing_reward_id = existing_reward_id
        self.added = []

    async def get(self, model, obj_id):
        _ = model
        if self._referrer is not None and int(getattr(self._referrer, "id", -1)) == int(obj_id):
            return self._referrer
        return None

    async def execute(self, query):
        _ = query
        return _ScalarResult(self._existing_reward_id)

    def add(self, obj):
        self.added.append(obj)


class ReferralLevel1LogicTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_referrer_gets_one_percent_from_deal_amount(self):
        referrer = User(id=1, telegram_id=1001, ref_code="REF1")
        investor = User(id=2, telegram_id=1002, ref_code="INV1", referrer_id=1)
        deal = Deal(id=10, number=10, status="active")
        db = _FakeDb(referrer=referrer, existing_reward_id=None)

        await apply_referral_rewards_for_investment(
            db,
            investor=investor,
            deal=deal,
            deal_amount_usdt=Decimal("50"),
        )

        self.assertEqual(len(db.added), 1)
        rw = db.added[0]
        self.assertEqual(rw.from_user_id, 2)
        self.assertEqual(rw.to_user_id, 1)
        self.assertEqual(rw.level, 1)
        self.assertEqual(rw.amount, Decimal("0.500000"))
        self.assertEqual(rw.status, STATUS_PENDING)

    async def test_no_referrer_no_bonus(self):
        investor = User(id=2, telegram_id=1002, ref_code="INV1", referrer_id=None)
        deal = Deal(id=10, number=10, status="active")
        db = _FakeDb(referrer=None, existing_reward_id=None)

        await apply_referral_rewards_for_investment(
            db,
            investor=investor,
            deal=deal,
            deal_amount_usdt=Decimal("50"),
        )

        self.assertEqual(db.added, [])

    async def test_only_level_1_direct_referrer_used(self):
        direct_referrer = User(id=11, telegram_id=2011, ref_code="REF11")
        investor = User(id=12, telegram_id=2012, ref_code="INV12", referrer_id=11)
        deal = Deal(id=20, number=20, status="active")
        db = _FakeDb(referrer=direct_referrer, existing_reward_id=None)

        await apply_referral_rewards_for_investment(
            db,
            investor=investor,
            deal=deal,
            deal_amount_usdt=Decimal("50"),
        )

        self.assertEqual(len(db.added), 1)
        self.assertEqual(db.added[0].to_user_id, 11)
        self.assertEqual(db.added[0].level, 1)

    async def test_idempotency_existing_reward_skips_second_insert(self):
        referrer = User(id=1, telegram_id=1001, ref_code="REF1")
        investor = User(id=2, telegram_id=1002, ref_code="INV1", referrer_id=1)
        deal = Deal(id=10, number=10, status="active")
        db = _FakeDb(referrer=referrer, existing_reward_id=999)

        await apply_referral_rewards_for_investment(
            db,
            investor=investor,
            deal=deal,
            deal_amount_usdt=Decimal("50"),
        )

        self.assertEqual(db.added, [])


if __name__ == "__main__":
    unittest.main()
