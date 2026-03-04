# Архитектура пополнения баланса через Crypto Pay

## Содержание

1. [Обзор](#обзор)
2. [Компоненты](#компоненты)
   1. [Backend](#backend)
   2. [Crypto Pay API](#crypto-pay-api)
   3. [Telegram‑бот](#telegram-бот)
   4. [База данных](#база-данных)
3. [Жизненный цикл депозита](#жизненный-цикл-депозита)
4. [Баланс и ledger](#баланс-и-ledger)
5. [Безопасность и защита от двойного начисления](#безопасность-и-защита-от-двойного-начисления)
6. [Конфигурация и запуск](#конфигурация-и-запуск)

---

## Обзор

После рефакторинга система **не работает напрямую с блокчейном**. Пополнение баланса пользователя происходит через инвойсы [Crypto Pay API](https://help.crypt.bot/crypto-pay-api) (приложение в `@CryptoBot`):

1. Пользователь в боте нажимает «Пополнить» и вводит сумму.
2. Backend создаёт инвойс через Crypto Pay API.
3. Инвойс сохраняется в таблице `invoices` со статусом `pending`.
4. Пользователь оплачивает инвойс в CryptoBot.
5. Статус инвойса фиксируется:
   - либо через webhook `/crypto/webhook`,
   - либо вручную через `POST /crypto/invoices/{invoice_id}/sync`.
6. При статусе `paid` баланс пользователя увеличивается, а инвойс помечается как `paid`.

Вывод средств и инвестиции по‑прежнему реализованы через заявки и ручное подтверждение админом.

---

## Компоненты

### Backend

FastAPI‑приложение (`backend/`):

- REST‑API для бота и админки.
- Создание инвойсов в Crypto Pay (`POST /crypto/invoices`).
- Фиксация оплаты инвойса через webhook (`POST /crypto/webhook`) или ручной sync (`POST /crypto/invoices/{invoice_id}/sync`).
- Учёт заявок на пополнение/вывод, инвестиций, партнёрки и т.д.

### Crypto Pay API

Внешний сервис, часть экосистемы `@CryptoBot`:

- Методы `createInvoice`, `getInvoices`, `getBalance` и др.
- Webhook‑уведомления с типом `invoice_paid`.
- Авторизация через заголовок `Crypto-Pay-API-Token`.

Backend не хранит никаких приватных ключей, работает только с HTTP‑API.

### Telegram‑бот

Директория `bot/`:

- Aiogram 3, FSM.
- Кнопка «💳 Пополнить»:
  - Запрашивает сумму.
  - Вызывает backend (`/crypto/invoices`), получает `invoice_id` и `bot_invoice_url`.
  - Показывает пользователю кнопку «Оплатить» (ссылка на CryptoBot) и «Проверить оплату».
- Кнопка «Проверить оплату»:
  - Вызывает backend `POST /crypto/invoices/{invoice_id}/sync`.
  - По ответу показывает, зачислен ли депозит.

### База данных

Основные таблицы, связанные с депозитами и балансом:

- `users` — пользователи (telegram_id, профиль, реферальные поля, кэш‑поле `balance_usdt`).
- `invoices` — инвойсы Crypto Pay:
  - `id` — внутренний id.
  - `user_id` — к какому пользователю относится.
  - `invoice_id` — id инвойса в Crypto Pay API.
  - `amount`, `asset` — сумма и актив (обычно USDT).
  - `status` — `pending` / `paid` / `expired` (в текущей версии используются `pending` и `paid`).
  - `created_at`, `paid_at`.
- `ledger_transactions` — общий ledger для операций USDT (DEPOSIT / INVEST / PROFIT / WITHDRAW, используется как источник истины по балансу).
- `deposit_requests` / `withdraw_requests` / `wallet_transactions` — ручные заявки на пополнение/вывод и история транзакций (legacy‑часть, главным образом для USDC и старых сценариев).

---

## Жизненный цикл депозита

### 1. Создание инвойса

1. Пользователь нажимает «💳 Пополнить» в боте.
2. Бот просит ввести сумму пополнения в USDT, проверяет лимиты `MIN_DEPOSIT` / `MAX_DEPOSIT`.
3. Бот вызывает backend:
   ```http
   POST /crypto/invoices
   {
     "telegram_id": 123456789,
     "amount": 100.5,
     "asset": "USDT"
   }
   ```
4. Backend через Crypto Pay API вызывает `createInvoice` и получает объект Invoice с полями `invoice_id`, `amount`, `asset`, `bot_invoice_url` и др.
5. Backend создаёт запись в таблице `invoices` со статусом `pending`.
6. Бот отправляет пользователю ссылку `bot_invoice_url` и кнопку «🔄 Проверить оплату».

### 2. Оплата пользователем

Пользователь оплачивает инвойс в `@CryptoBot`. Crypto Pay меняет статус инвойса на `paid`.

### 3. Фиксация оплаты (два варианта)

#### Вариант A — Webhook

1. Crypto Pay шлёт POST‑запрос на `/crypto/webhook`:
   - Заголовок `crypto-pay-api-signature` (HMAC‑подпись тела).
   - Тело содержит JSON `Update` с полями:
     - `update_type = "invoice_paid"`,
     - `payload` — объект `Invoice`.
2. Backend:
   - Проверяет подпись (HMAC‑SHA256 по телу, секрет — `SHA256(CRYPTO_PAY_TOKEN)`).
   - Если `update_type != "invoice_paid"` — игнорирует.
   - В транзакции загружает `Invoice` по `invoice_id` и лочит её (`SELECT ... FOR UPDATE`).
   - Если статус уже `paid` — делает `{"ok": true}` (идемпотентность).
   - Иначе:
     - увеличивает поле `users.balance_usdt` на сумму инвойса,
     - обновляет `invoices.status` на `paid`, проставляет `paid_at`.
   - Возвращает `{"ok": true}`.

#### Вариант B — Ручной sync без webhook

Если webhook не настроен или недоступен, бот по кнопке «Проверить оплату» вызывает:

```http
POST /crypto/invoices/{invoice_id}/sync
```

Backend:

- Делает `getInvoices` в Crypto Pay API по `invoice_id`.
- Если статус инвойса в Crypto Pay не `paid` — возвращает текущий локальный статус.
- Если `paid` — выполняет ту же транзакционную логику, что и webhook (увеличивает `balance_usdt`, помечает инвойс как `paid`).

---

## Баланс и ledger

### Что такое «баланс» пользователя

В системе есть два слоя учёта:

- **`ledger_transactions`** — детальный журнал операций по USDT (источник истины).
- **`users.balance_usdt`** — агрегированное кэш‑поле, которое синхронизируется с ledger.

После перехода на Crypto Pay и внедрения сделок/инвестиций логика такая:

- **пополнения через Crypto Pay**:
  - при оплате инвойса создаётся запись в `ledger_transactions` c типом `DEPOSIT`;
  - `users.balance_usdt` пересчитывается из ledger (кэш);
- **инвестиции** (`/api/invest`):
  - перед инвестированием баланс проверяется через `get_balance_usdt` (ledger);
  - создаётся запись `INVEST`, уменьшающая баланс;
- **прибыль по сделке**:
  - после закрытия/завершения сделки создаются две записи: `DEPOSIT` (возврат тела) и `PROFIT` (прибыль);
- **выводы**:
  - пользователь создаёт заявку в `withdraw_requests`;
  - при `approve` в админ‑dashboard создаётся `WITHDRAW` в ledger и обновляется кэш `balance_usdt`.

Баланс, который видит пользователь в боте (`/v1/wallet/balances`), для USDT считается через `ledger_service.get_balance_usdt`:

- USDT = сумма по типам `DEPOSIT` и `PROFIT` минус сумма по типам `INVEST` и `WITHDRAW`.
- USDC = «legacy» по таблице `wallet_transactions` (DEPOSIT − WITHDRAW).

---

## Безопасность и защита от двойного начисления

Основные меры безопасности:

- **Нет приватных ключей** — backend не хранит seed, приватные ключи и не подписывает транзакции. Деньги находятся на счетах в CryptoBot, мы работаем только через API.
- **Секреты в `.env`** — `CRYPTO_PAY_TOKEN`, `DATABASE_URL`, `ADMIN_API_KEY` и др. задаются через переменные окружения.
- **Проверка подписи webhook** — каждая нотификация проверяется через HMAC‑SHA256, секрет вычисляется как `SHA256(CRYPTO_PAY_TOKEN)`.
- **Идемпотентность по `invoice_id`**:
  - В таблице `invoices` `invoice_id` уникален.
  - Локальный инвойс лочится по `SELECT ... FOR UPDATE`.
  - Если статус уже `paid`, повторные webhook или ручные проверки не изменяют баланс повторно.

---

## Конфигурация и запуск

### Переменные окружения

Критичные для депозитов переменные в `.env`:

```env
CRYPTO_PAY_TOKEN=your-crypto-pay-token
APP_URL=https://your-domain.com
MIN_DEPOSIT=1
MAX_DEPOSIT=100000
```

- `CRYPTO_PAY_TOKEN` — API‑токен приложения в `@CryptoBot` / `@CryptoTestnetBot`.
- `APP_URL` — публичный URL backend (используется при настройке webhook).
- `MIN_DEPOSIT` / `MAX_DEPOSIT` — лимиты суммы пополнения.

### Настройка webhook в Crypto Pay

1. Запустить backend (`docker compose up --build`).
2. Убедиться, что `APP_URL` указывает на реальный HTTPS‑домен, по которому доступен `/crypto/webhook`.
3. В `@CryptoBot` → Crypto Pay → My Apps → ваше приложение → **Webhooks…**:
   - нажать «🌕 Enable Webhooks»;
   - указать URL `https://your-domain.com/crypto/webhook`.

### Запуск всего стека

```bash
docker compose up --build
```

Это поднимет:

- `db` — PostgreSQL;
- `app` — FastAPI backend (с миграциями);
- `bot` — Telegram‑бот.

# Архитектура системы депозитов USDT (blockchain)

## Обзор

Полностью автоматизированная система депозитов USDT без платёжных агрегаторов: пользователь получает уникальный депозитный адрес, отправляет USDT, система по событиям контракта после N подтверждений зачисляет средства на внутренний баланс через ledger.

## Компоненты

### Backend (FastAPI)

- **Депозитные адреса**: `GET /v1/deposit-addresses?telegram_id=...&chain_id=...` — выдаёт или создаёт адрес из HD-кошелька (xpub). Приватные ключи в сервисе не хранятся.
- **Баланс**: баланс USDT считается по таблице `ledger_transactions` (сумма депозитов минус вывод/инвестиции). Поле `users.balance_usdt` не используется как источник истины для новых депозитов.

### Watcher (отдельный сервис)

- Подключается к RPC (BSC/Polygon/Ethereum).
- Слушает события `Transfer` официального контракта USDT.
- Фильтрует по полю `to` (наши депозитные адреса из БД).
- Проверяет, что `contract address` совпадает с настроенным USDT.
- Ждёт заданное число подтверждений (`DEPOSIT_CONFIRMATIONS`).
- Пишет сырые события в `blockchain_events`, создаёт записи в `ledger_transactions` (идемпотентно по `chain_id`, `tx_hash`, `log_index`).

### База данных

- **users** — пользователи.
- **deposit_addresses** — привязка `user_id` + `chain_id` к адресу и `derivation_index`.
- **blockchain_events** — сырые события Transfer (уникальность по `chain_id`, `tx_hash`, `log_index`).
- **ledger_transactions** — все движения по балансу; для блокчейн-депозитов — уникальность по `chain_id`, `tx_hash`, `log_index`.
- **watcher_cursor** — последний обработанный блок по `chain_id` (чтобы не пропускать блоки и не обрабатывать повторно).

## Безопасность

- Никаких приватных ключей и seed в коде и логах.
- Проверка официального контракта USDT по адресу из конфига.
- Минимум N подтверждений перед зачислением.
- Идемпотентность обработки событий (unique по tx_hash + log_index).
- Конфигурация через переменные окружения; xpub только для деривации адресов.

## Запуск

1. Настроить `.env`: `DEPOSIT_XPUB`, `CHAIN_ID`, `USDT_CONTRACT_ADDRESS`, `RPC_URL`, `DEPOSIT_CONFIRMATIONS`.
2. Миграции: `docker compose exec backend alembic upgrade head`.
3. Запуск: `docker compose up -d` (backend + watcher + bot + postgres).

## Замена RPC

Чтобы перейти на свой нод, достаточно поменять `RPC_URL` в `.env`; бизнес-логика и контракт не меняются.
