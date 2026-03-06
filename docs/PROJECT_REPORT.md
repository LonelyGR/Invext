# Отчёт по проекту Invext

Краткий обзор текущего состояния проекта: структура, что уже реализовано и как работает, а также приоритетные доработки.

## Содержание

1. [Структура проекта](#1-структура-проекта)
2. [Функциональность](#2-функциональность)
3. [Технологический стек](#3-технологический-стек)
4. [Баланс и денежные потоки](#4-баланс-и-денежные-потоки)
5. [Доработки и TODO](#5-доработки-и-todo)
6. [Краткая сводка статуса](#6-краткая-сводка-статуса)

---

## 1. Структура проекта

### Backend (`backend/`)

- **API (FastAPI):**
  - `auth` — аутентификация по Telegram‑данным, создание/обновление пользователя.
  - `wallet` — получение балансов по валютам (USDT/USDC).
  - `user_wallets` — сохранённые кошельки пользователя.
  - `deposits` — заявки на пополнение (ручные сценарии).
  - `withdrawals` — заявки на вывод.
  - `admin` — админские действия по заявкам.
  - `crypto_pay` — инвойсы Crypto Pay (создание, webhook, ручной sync).
  - `invest` — инвестирование средств с баланса (ledger).

- **Модели (SQLAlchemy 2, `src/models`):**
  - `User` — пользователи, реферальные связи, поле `balance_usdt`.
  - `UserWallet` — сохранённые адреса кошельков пользователей.
  - `WithdrawRequest` — заявки на вывод.
  - `WalletTransaction` — история операций по заявкам (DEPOSIT / WITHDRAW, в основном для USDC и legacy‑учёта).
  - `LedgerTransaction` — журнал операций по USDT (DEPOSIT / WITHDRAW / INVEST).
  - `Invoice` — инвойсы Crypto Pay (invoice_id, amount, asset, status).

- **Сервисы (`src/services`):**
  - `user_service`, `user_wallet_service` — работа с пользователями и кошельками.
  - `wallet_service` — агрегирует балансы (USDT по ledger, USDC по wallet_transactions).
  - `deposit_service` / `withdraw_service` — логика заявок, лимиты, проверки баланса.
  - `ledger_service` — вычисление баланса USDT и операции по ledger (в первую очередь для инвестиций).
  - `crypto_pay_service` — низкоуровневый HTTP‑клиент к Crypto Pay API (`createInvoice`, `getInvoices`, `getBalance`).

- **Схемы (Pydantic v2, `src/schemas`):**
  - DTO для auth, профиля, кошельков, заявок, инвестиций.
  - `crypto_pay` — схемы для создания инвойса и чтения его статуса.

- **Инфраструктура:**
  - PostgreSQL (asyncpg) + SQLAlchemy 2 (async).
  - Alembic‑миграции:
    - `001` — базовые таблицы (users, deposit/withdraw_requests, wallet_transactions).
    - `002` — user_wallets.
    - `003` — users.balance_usdt, nowpayments_payments, ledger_transactions.
    - `004` — legacy‑миграция blockchain‑депозитов (обнулена как no‑op).
    - `005` — удаление nowpayments_payments и related_payment_id.
    - `006` — таблица invoices для Crypto Pay.

### Bot (`bot/`)

- **Хендлеры:**
  - `start`, `profile`, `wallets`, `withdraw`, `invest`, `partners`, `team_turnover`, `stats`, `admin_handlers`.
  - `deposit` переписан под **инвойсы Crypto Pay**:
    - просит ввести сумму;
    - вызывает `/crypto/invoices` и даёт пользователю ссылку на оплату в CryptoBot;
    - по кнопке «Проверить оплату» вызывает `/crypto/invoices/{invoice_id}/sync`.

- **API‑клиент (`src/api_client/client.py`):**
  - Методы для всех основных эндпоинтов backend.
  - Новые методы:
    - `create_crypto_invoice` — обёртка над `POST /crypto/invoices`;
    - `sync_crypto_invoice` — обёртка над `POST /crypto/invoices/{id}/sync`.

- **Конфиг (`src/config/settings.py`):**
  - Читает `BOT_TOKEN`, `BACKEND_BASE_URL`, `ADMIN_API_KEY`, `ADMIN_TELEGRAM_IDS`, `MIN/MAX_*`.

### Инфраструктура

- **Docker Compose (корневой `docker-compose.yml`):**
  - `db` — PostgreSQL 15.
  - `app` — backend (FastAPI + Alembic).
  - `bot` — Telegram‑бот.

- **.env/.env.example:**
  - Общие настройки: `DATABASE_URL`, `BACKEND_HOST`, `BACKEND_PORT`.
  - Админские: `ADMIN_API_KEY`, `ADMIN_TELEGRAM_IDS`.
  - Лимиты: `MIN_DEPOSIT`, `MAX_DEPOSIT`, `MIN_WITHDRAW`, `MAX_WITHDRAW`.
  - Бот: `BOT_TOKEN`.
  - Crypto Pay: `CRYPTO_PAY_TOKEN`, `APP_URL`.

Watcher и blockchain‑логика **удалены** из основного потока пополнения.

---

## 2. Функциональность

### Регистрация и профиль

- `/start` и `/start ref_code` — создание/обновление пользователя, привязка реферала (через deep‑link с параметром).
- Профиль показывает:
  - баланс USDT/USDC (из `GET /v1/wallet/balances`);
  - реферальную ссылку для приглашения (deep‑link), количество рефералов, оборот команды;
  - базовую информацию о пользователе (имя, страна и т.п.).

### Пополнение через Crypto Pay

- В боте кнопка «💳 Пополнить»:
  - спрашивает сумму;
  - через backend создаёт инвойс в Crypto Pay;
  - возвращает пользователю ссылку `bot_invoice_url` и кнопку «Проверить оплату».
- После оплаты инвойса:
  - либо срабатывает webhook `/crypto/webhook`;
  - либо бот/пользователь вручную вызывает `/crypto/invoices/{invoice_id}/sync`.
- Backend:
  - помечает инвойс как `paid`;
  - увеличивает агрегированное поле `users.balance_usdt` (интеграция ledger — планируется).

### Заявки на пополнение/вывод (legacy/админские)

- **Пополнение (заявки):**
  - `POST /v1/deposits/request` — пользователь создаёт заявку;
  - `GET /v1/deposits/my` — история заявок;
  - админ подтверждает/отклоняет заявки через бот;
  - при подтверждении создаётся `WalletTransaction` (DEPOSIT, COMPLETED).

- **Вывод:**
  - `POST /v1/withdrawals/request` — создание заявки, проверка баланса и лимитов;
  - `GET /v1/withdrawals/my` — история заявок;
  - админ подтверждает/отклоняет заявки через бот;
  - при подтверждении создаётся `WalletTransaction` (WITHDRAW, COMPLETED).
  - Фактический перевод USDT в сеть остаётся ручной операцией.

### Инвестиции

- Эндпоинт `POST /api/invest`:
  - проверяет, что у пользователя достаточно USDT‑баланса (через `get_balance_usdt` / ledger);
  - минимальная сумма инвестиций — 100 USDT;
  - создаёт запись в `ledger_transactions` с типом INVEST;
  - возвращает новую величину баланса с учётом списания.

### Партнёрка и статистика

- Партнёры, оборот команды, статистика и админка по заявкам — работают так же, как в исходном проекте.

---

## 3. Технологический стек

| Часть      | Стек |
|-----------|------|
| Backend   | Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2 (async), asyncpg, Alembic, httpx, uvicorn |
| Bot       | Python 3.11+, aiogram 3.x, FSM, httpx |
| БД        | PostgreSQL 15 |
| Платежи   | Crypto Pay API (CryptoBot), HTTP‑интеграция без прямой работы с блокчейном |
| Инфра     | Docker, Docker Compose, `.env` |

---

## 4. Баланс и денежные потоки

### Источник истины для баланса

- Планируемый «источник истины» — **ledger (`ledger_transactions`)**, где каждая операция, влияющая на баланс USDT, — это отдельная запись с типом и суммой.
- В исторической версии:
  - DEPOSIT приходил от blockchain‑watcher;
  - WITHDRAW/INVEST списывали средства через ledger.
- После перехода на Crypto Pay:
  - новые депозиты фиксируются через таблицу `invoices` и поле `users.balance_usdt`;
  - ledger уже используется для инвестиций и частично для проверок баланса;
  - требуется доработка, чтобы любые пополнения/выводы автоматически отражались в ledger.

### Как сейчас считается баланс (важно)

- Модуль `wallet_service`:
  - USDT: вызывает `ledger_service.get_balance_usdt(user_id)`:
    - DEPOSIT‑записи увеличивают баланс;
    - WITHDRAW/INVEST уменьшают;
  - USDC: считает по `wallet_transactions` (DEPOSIT − WITHDRAW).
- Баланс, который видит пользователь, — результат этого вычисления.

В текущей версии нужно иметь в виду:

- Пополнения через Crypto Pay уже увеличивают `users.balance_usdt`, но ещё не создают отдельную запись в ledger — без дополнительной интеграции такие депозиты **не учитываются в ledger‑балансе USDT**.
- Инвестиции (`/api/invest`) и ряд проверок используют именно ledger. Поэтому следующий шаг развития — связать оплату инвойса с созданием DEPOSIT‑записи в `ledger_transactions`.

### Денежные потоки в целом

- **Входящий поток (deposit)** — через Crypto Pay:
  - выгодно тем, что не нужно управлять своими адресами, RPC и приватными ключами;
  - вся логика зачисления — внутри CryptoBot.
- **Исходящий поток (withdraw)** — через заявки:
  - технически отправка техники (подпись и отправка транзакций) вынесена за рамки проекта;
  - проект отвечает за внутренний баланс и учёт, а не за on‑chain транзакции.

---

## 5. Доработки и TODO

Краткий список приоритетных доработок:

- **Интегрировать Crypto Pay с ledger:**
  - при оплате инвойса создавать `LedgerTransaction` с типом DEPOSIT;
  - при approve вывода создавать `LedgerTransaction` с типом WITHDRAW;
  - использовать ledger как единый источник баланса USDT.
- **Автоматизировать вывод:**
  - спроектировать signer‑сервис и hot wallet;
  - добавить лимиты и мониторинг.
- **Инвест‑модуль и сделки:**
  - базовый модуль сделок реализован: есть таблицы `deals` / `deal_investments`, планировщик, который открывает/закрывает сделки и начисляет прибыль, а также Telegram‑уведомления для инвесторов и раздел «Сделки» в админ‑dashboard;
  - дальнейшие доработки — расширить отчётность, добавить больше аналитики для пользователя и админки.
- **Усилить тесты:** покрыть сервисы `wallet_service`, `crypto_pay_service`, заявки на вывод/пополнение и инвест‑поток.

---

## 6. Краткая сводка статуса

| Блок                           | Статус |
|--------------------------------|--------|
| Регистрация, профиль, кошельки | ✅ Работает |
| Пополнение через Crypto Pay    | ✅ Работает (создание инвойса, ручной sync/webhook) |
| Логика заявок на пополнение    | ✅ Работает (legacy, ручные сценарии) |
| Вывод + админка                | ✅ Работает как заявки (отправка on‑chain — вне проекта) |
| Инвестиции (ledger)            | ✅ Работают |
| Партнёрка, оборот, статистика  | ✅ Работают |
| Документация                   | ✅ Обновлена под Crypto Pay и баланс |

Проект готов к дальнейшему развитию как «балансовый» backend поверх Crypto Pay API, без необходимости держать свои ноды и приватные ключи.

