# NOWPayments: реализация и инструкции

## 1. Архитектура

- **Единственный провайдер депозитов**: NOWPayments (USDT BEP20).
- **Слои**:
  - **Router**: `backend/src/api/routers/payments.py` — HTTP endpoints.
  - **Service**: `backend/src/services/payment_service.py` — применение оплаты к балансу (ledger + user).
  - **Integration**: `backend/src/integrations/nowpayments/` — клиент API, схемы, проверка IPN-подписи, создание invoice.

**Flow:**
1. Пользователь инициирует пополнение (бот / frontend).
2. Backend: `POST /v1/payments/deposit/create-invoice` (telegram_id, amount USD) → вызов NOWPayments API → сохранение `PaymentInvoice` → возврат `invoice_url`, `order_id`, статус.
3. Пользователь переходит по ссылке и платит USDT (BEP20).
4. NOWPayments отправляет IPN на `POST /v1/payments/webhook/nowpayments`.
5. Webhook: проверка подписи `x-nowpayments-sig` (HMAC-SHA512), запись в `payment_webhook_events`, при статусе `finished`/`sent`/`confirmed` — в транзакции БД: создание записи в `ledger_transactions` (type=DEPOSIT, provider=nowpayments), пересчёт и обновление `users.balance_usdt`, пометка `PaymentInvoice.is_balance_applied = True`. Идемпотентность: повторный webhook не дублирует начисление.

---

## 2. Таблицы и миграции

- **payment_invoices** — один инвойс на пополнение (user_id, order_id, external_invoice_id, invoice_url, price_amount, pay_currency, network, status, is_balance_applied, raw_response_json, created_at, updated_at, completed_at и др.).
- **payment_webhook_events** — сырые IPN (provider, order_id, payload_json, signature_header, processing_status, processing_error, created_at).
- **ledger_transactions** — добавлены поля: `provider`, `external_payment_id`, `metadata_json` (для аудита депозитов).

Миграция: `alembic/versions/010_payment_invoices_and_webhook_events.py`.  
Применить: `alembic upgrade head` (из каталога backend).

Таблица **invoices** (Crypto Pay) оставлена в БД для истории; новый поток её не использует.

---

## 3. API Endpoints

| Метод | Путь | Описание |
|-------|------|----------|
| POST | /v1/payments/deposit/create-invoice | Создать инвойс (body: telegram_id, amount). Возврат: invoice_id, order_id, invoice_url, amount, currency, pay_currency, network, status, created_at. |
| GET | /v1/payments/deposit/history | История депозитов пользователя (query: telegram_id, limit, offset, status_filter). |
| GET | /v1/payments/deposit/{invoice_id} | Один инвойс (query: telegram_id). |
| POST | /v1/payments/webhook/nowpayments | IPN callback NOWPayments (проверка подписи, идемпотентная обработка). |

Админка:
- GET /database/api/deposits — список PaymentInvoice (фильтры: status, provider, user_id, order_id, external_id, даты).
- GET /database/api/deposits/{id} — детали + raw_webhook_payloads.

---

## 4. Переменные окружения

См. `.env.example`. Основные:

- `NOWPAYMENTS_API_KEY` — API ключ из кабинета NOWPayments.
- `NOWPAYMENTS_IPN_SECRET` — секрет IPN (Payment Settings).
- `NOWPAYMENTS_BASE_URL` — https://api.nowpayments.io или sandbox.
- `NOWPAYMENTS_CALLBACK_URL` — полный URL webhook (например `https://your-domain.com/v1/payments/webhook/nowpayments`).
- `NOWPAYMENTS_SUCCESS_URL`, `NOWPAYMENTS_CANCEL_URL` — редиректы после оплаты (опционально).
- `MIN_DEPOSIT`, `MAX_DEPOSIT` — лимиты суммы (уже были в проекте).

---

## 5. Тестирование

### 5.1 Локально

1. Поднять БД, применить миграции: `alembic upgrade head`.
2. В .env задать `NOWPAYMENTS_API_KEY`, `NOWPAYMENTS_IPN_SECRET`, `NOWPAYMENTS_BASE_URL` (sandbox при тестах), `NOWPAYMENTS_CALLBACK_URL` (например через ngrok: `https://xxx.ngrok.io/v1/payments/webhook/nowpayments`).
3. Запустить backend. Создать инвойс:  
   `POST /v1/payments/deposit/create-invoice` с телом `{"telegram_id": <id>, "amount": "10"}`.  
   Проверить ответ (invoice_url, order_id) и запись в `payment_invoices`.
4. История: `GET /v1/payments/deposit/history?telegram_id=<id>`.
5. Один инвойс: `GET /v1/payments/deposit/<invoice_id>?telegram_id=<id>`.

### 5.2 Webhook

- В личном кабинете NOWPayments указать IPN Callback URL = `NOWPAYMENTS_CALLBACK_URL` и сохранить IPN Secret в `NOWPAYMENTS_IPN_SECRET`.
- Локально: использовать ngrok или аналог, чтобы NOWPayments мог достучаться до вашего `/v1/payments/webhook/nowpayments`.
- После тестовой оплаты проверить: запись в `payment_webhook_events`, при успешном статусе — новая запись в `ledger_transactions`, обновлённый `users.balance_usdt`, у соответствующего `payment_invoices` — `is_balance_applied = true`.

### 5.3 Проверка идемпотентности

- Отправить один и тот же валидный IPN payload дважды (с одной и той же подписью). Второй раз баланс не должен увеличиваться повторно, в логах — «already applied» / «skipped».

---

## 6. Удалённые и изменённые файлы

**Удалены:**
- `backend/src/api/routers/crypto_pay.py`
- `backend/src/services/crypto_pay_service.py`
- `backend/src/schemas/crypto_pay.py`

**Убраны из main/router list:** роутеры `deposits`, `crypto_pay`.

**Изменены:**
- `backend/src/main.py`, `backend/src/api/routers/__init__.py` — подключён роутер `payments`, убраны `deposits` и `crypto_pay`.
- `backend/src/core/config.py` — добавлены настройки NOWPayments; `CRYPTO_PAY_TOKEN` сделан необязательным (default="").
- `backend/src/models/ledger_transaction.py` — поля provider, external_payment_id, metadata_json.
- `backend/src/models/user.py` — связь `payment_invoices`.
- `backend/src/models/__init__.py` — экспорт PaymentInvoice, PaymentWebhookEvent.
- `backend/src/api/routers/admin_dashboard.py` — список/детали депозитов переведены на PaymentInvoice, добавлены фильтры и raw webhook.
- `backend/src/api/routers/wallet.py` — GET /v1/wallet/invoices отдаёт данные из PaymentInvoice.
- `backend/src/services/user_service.py` — deposits_count считается по PaymentInvoice.
- `backend/src/schemas/admin_dashboard.py`, `backend/src/schemas/wallet.py` — поля под PaymentInvoice (order_id, provider, network и т.д.).
- `admin-frontend/static/admin.js` — раздел «Пополнения» под NOWPayments (статусы, фильтры, order_id, детали + raw webhook).
- `bot/src/api_client/client.py` — create_deposit_invoice, get_deposit_invoice, get_my_invoices (те же URL, где изменился контракт).
- `bot/src/handlers/deposit.py` — поток пополнения через NOWPayments, тексты и статусы.

Модель и таблица **Invoice** (Crypto Pay) не удалялись; используются только для старых данных.
