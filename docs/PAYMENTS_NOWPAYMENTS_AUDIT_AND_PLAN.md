# Аудит текущей платёжной логики и план перехода на NOWPayments

## 1. Краткий аудит текущей платежной логики

### 1.1 Текущая система (Crypto Pay)

| Компонент | Файлы / сущности |
|-----------|-------------------|
| **Env** | `CRYPTO_PAY_TOKEN`, `APP_URL` (для webhook) в `backend/src/core/config.py`, `.env.example` |
| **API client** | `backend/src/services/crypto_pay_service.py` — вызовы Crypto Pay API (createInvoice, getInvoices) |
| **Endpoints** | `backend/src/api/routers/crypto_pay.py`: `POST /crypto/invoices`, `POST /crypto/invoices/{id}/sync`, `POST /crypto/webhook` |
| **Webhook** | В том же роутере; проверка подписи `crypto-pay-api-signature`, обработка `invoice_paid` |
| **Services** | `crypto_pay_service` + логика начисления в `crypto_pay.py` (ledger + balance_usdt) |
| **Models** | `backend/src/models/invoice.py` — `Invoice` (user_id, invoice_id, amount, asset, status, paid_at) |
| **Ledger** | `LedgerTransaction` (type=DEPOSIT), `ledger_service.get_balance_usdt`, обновление `users.balance_usdt` |
| **Admin** | `admin_dashboard.py`: `GET /database/api/deposits`, `GET /database/api/deposits/{id}` — список/деталка по `Invoice` |
| **Frontend (admin)** | `admin-frontend/static/admin.js` — раздел «Пополнения», фильтры, модалка детали, данные из `/database/api/deposits` |
| **Bot** | `bot/src/handlers/deposit.py` — «💳 Пополнить», создание инвойса через `api.create_crypto_invoice`, «Проверить оплату» через `api.sync_crypto_invoice`, «История пополнений» |
| **API client (bot)** | `bot/src/api_client/client.py`: `create_crypto_invoice`, `sync_crypto_invoice`, `get_my_invoices` |
| **Wallet API** | `backend/src/api/routers/wallet.py`: `GET /v1/wallet/invoices` — «мои пополнения» по `Invoice` |
| **Схемы** | `backend/src/schemas/crypto_pay.py` — CreateInvoiceRequest, InvoiceResponse |
| **User stats** | `user_service.get_user_with_stats`: `deposits_count` по `Invoice` (уже переведено с DepositRequest на Invoice) |

### 1.2 Сломанные ссылки после прошлой зачистки

- `backend/src/main.py` и `backend/src/api/routers/__init__.py` импортируют `deposits` — модуль `deposits.py` был удалён, приложение не запустится. Нужно убрать импорт/включение роутера `deposits`.

### 1.3 Что остаётся и переиспользуется

- **Ledger**: `LedgerTransaction`, `ledger_service.get_balance_usdt`, типы `DEPOSIT`/`WITHDRAW`/`INVEST`/`PROFIT` — остаются; добавим поля для провайдера и внешнего id.
- **Баланс**: `users.balance_usdt`, обновление после начисления — без изменений концепции.
- **Структура API**: префиксы `/v1/` для пользовательских эндпоинтов; админка под `/database/api` с JWT — сохраняем.
- **Бот**: сценарий «Пополнить» (сумма → ссылка → история) — переключаем на NOWPayments API.

---

## 2. Пошаговый план изменений

| Шаг | Действие |
|-----|----------|
| 1 | Удалить импорт/роутер `deposits` из `main.py` и `routers/__init__.py`. |
| 2 | Добавить модуль `src/integrations/nowpayments/`: client, schemas, service, security (HMAC IPN). |
| 3 | Ввести модели `PaymentInvoice`, `PaymentWebhookEvent`; в `LedgerTransaction` добавить `provider`, `external_id`, `metadata` (JSON). |
| 4 | Миграции Alembic: таблицы `payment_invoices`, `payment_webhook_events`; изменения `ledger_transactions`; опционально удалить/переименовать `invoices` после переноса логики. |
| 5 | Добавить роутер платежей: `POST /v1/payments/deposit/create-invoice`, `GET /v1/payments/deposit/history`, `GET /v1/payments/deposit/{id}`, `POST /v1/payments/webhook/nowpayments`. |
| 6 | Конфиг: NOWPAYMENTS_API_KEY, NOWPAYMENTS_IPN_SECRET, NOWPAYMENTS_BASE_URL, NOWPAYMENTS_CALLBACK_URL, MIN/MAX_DEPOSIT, pay_currency (usdtbsc) и т.д. |
| 7 | Удалить Crypto Pay: роутер `crypto_pay`, сервис `crypto_pay_service`, схемы `crypto_pay`; убрать `Invoice` из нового потока (оставить таблицу в БД для истории или миграция drop — по решению). Заменить использование `Invoice` в админке и в `GET /v1/wallet/invoices` на `PaymentInvoice`. |
| 8 | Админ-панель: раздел «Пополнения» перевести на `payment_invoices` (поиск по user_id, order_id, external_invoice_id; фильтры статус/дата/провайдер; детали + raw webhook). |
| 9 | Бот: пополнение через новый `create-invoice`; история и проверка статуса через новые endpoints. |
| 10 | Документация: архитектура, таблицы, endpoints, flow, тестирование, список удалённых модулей. |

---

## 3. Конкретные изменения по файлам (сводка)

- **Удалить**: `backend/src/api/routers/crypto_pay.py`, `backend/src/services/crypto_pay_service.py`, `backend/src/schemas/crypto_pay.py`. Из `main.py` и `routers/__init__.py` — роутер `deposits` и роутер `crypto_pay`.
- **Добавить**: `backend/src/integrations/nowpayments/` (client, schemas, service, security), `backend/src/api/routers/payments.py`, модели `PaymentInvoice`, `PaymentWebhookEvent`, миграции, обновления `ledger_transaction` и конфига.
- **Изменить**: `admin_dashboard.py` (deposits → payment_invoices), `wallet.py` (invoices → payment_invoices), `user_service` (deposits_count по PaymentInvoice), бот client и deposit handler, админский JS.

Далее — реализация по шагам.
