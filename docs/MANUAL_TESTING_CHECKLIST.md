## Manual testing checklist

### Withdraw request
- Create withdrawal via bot: `📤 Вывести` → currency → amount → address.
- Verify bot reply contains: “в течение 48 часов”.
- Verify DB: new row in `withdraw_requests` with `status=PENDING`, correct `user_id/amount/address`, `created_at/updated_at` filled.
- Duplicate protection: send the same amount+address twice quickly → should return the same `id` (no duplicate PENDING rows).
- Balance protection: try withdraw more than available → should get an error and no new request created.

### Referral rewards (3 levels) — ONLY from deposit
Setup:
- User A has `ref_code`.
- User B registers via `/start <A.ref_code>` (so `B.referrer_id = A.id`).
- User C registers via `/start <B.ref_code>` (so C is level-2 for A).
- User D registers via `/start <C.ref_code>` (so D is level-3 for A).

Checks:
- Make a successful deposit for B (NOWPayments / webhook):
  - `ledger_transactions`: B has `type=DEPOSIT`.
  - `ledger_transactions`: A has `type=REFERRAL_BONUS` with `metadata_json.source=deposit`, `from_user_id=B.id`, `level=1`, amount = 3% of deposit.
- Make a successful deposit for C:
  - B gets level-1 bonus; A gets level-2 bonus.
- Make a successful deposit for D:
  - C gets level-1 bonus; B gets level-2 bonus; A gets level-3 bonus.
- Ensure no bonuses on investments:
  - Let B invest into a deal → only `type=INVEST` ledger appears, no new `REFERRAL_BONUS`.
- Idempotency:
  - Re-send the same payment webhook / re-run applying for the same invoice → no second `REFERRAL_BONUS` rows.

### Deal notifications + scheduler
- Ensure scheduler is running (app logs):
  - `process_due_deals job started/finished` once per minute.
  - Daily jobs:
    - `close_deal_1200 job started/finished`
    - `open_deal_1300 job started/finished`
- Deal close message variants:
  - Create an active deal with participants and set `end_at` so it closes.
  - After close:
    - participants get text with “Ваша прибыль X%”
    - non-participants get text without profit line
- Deal open message:
  - At 13:00 (UTC+1) job should create a new deal and send “Открыт сбор на сделку #N …” to all users.

