# Документация проекта Invext

Проект Invext — это backend + Telegram‑бот для ведения внутреннего баланса пользователей (USDT/USDC), заявок на пополнение/вывод и простых инвестиций. Пополнение баланса реализовано через инвойсы Crypto Pay API (CryptoBot), без прямой работы с блокчейном.

## Содержание

1. [Общее описание](#1-общее-описание)
2. [Архитектура](#2-архитектура)
3. [Баланс пользователя](#3-баланс-пользователя)
4. [База данных](#4-база-данных)
5. [Конфигурация (.env)](#5-конфигурация-env)
6. [Запуск и окружения](#6-запуск-и-окружения)
7. [Безопасность и секреты](#7-безопасность-и-секреты)
8. [Планы на развитие](#8-планы-на-развитие)

---

## 1. Общее описание

### Что делает система

С точки зрения пользователя:

- Telegram‑бот показывает **баланс** в USDT/USDC, профиль, партнёрский раздел и т.п.
- Позволяет:
  - пополнить баланс через инвойс CryptoBot (Crypto Pay API);
  - создать заявку на вывод средств (c подтверждением админом);
  - «инвестировать» часть баланса (списание USDT в отдельный учёт).

С точки зрения backend‑разработчика:

- Есть единый FastAPI‑backend с БД PostgreSQL.
- Бот ходит к backend по REST‑API.
- Пополнения не зависят от RPC/нод — только через Crypto Pay API.

---

## 2. Архитектура

### Компоненты

| Компонент          | Описание |
|-------------------|----------|
| **Backend**       | FastAPI‑приложение (`backend/`). REST‑API для бота и админ‑dashboard, работа с Crypto Pay, ledger, инвестициями и заявками. |
| **Bot**           | Telegram‑бот (`bot/`) на aiogram 3. Работает только через backend‑API, сам не ходит в Crypto Pay. |
| **Admin dashboard** | Статический HTML/CSS/JS‑сайт (`admin-frontend/`) c префиксом `/database`, отдаётся через Nginx. Работает через закрытое API `/database/api/*`, показывает сводные KPI, пользователей, сделки, заявки на вывод и логи. Вход — по одноразовому токену, который админ получает в боте. |
| **PostgreSQL**    | Хранит пользователей, заявки, инвойсы, ledger и прочие данные. |
| **Nginx**         | Роутит `/database` на админ‑frontend и `/database/api` на backend. |
| **Crypto Pay**    | Внешний сервис (`@CryptoBot` / `@CryptoTestnetBot`), создаёт и обрабатывает платежные инвойсы. |

Прямой работы с блокчейном нет: нет RPC, xpub, watcher‑процесса и генерации адресов.

### Потоки данных (высокоуровнево)

- **Пополнение**:
  1. Бот → Backend: `POST /crypto/invoices` (создать инвойс).
  2. Backend → Crypto Pay: `createInvoice`.
  3. Crypto Pay → Бот (через backend): `bot_invoice_url` отправляется пользователю.
  4. Оплата инвойса в CryptoBot.
  5. Crypto Pay → Backend: webhook `invoice_paid` *или* Бот → Backend: `POST /crypto/invoices/{id}/sync`.
  6. Backend увеличивает баланс пользователя и помечает инвойс как `paid`.

- **Вывод**:
  - Пользователь создаёт заявку (сумма + адрес), backend проверяет баланс и лимиты и сохраняет заявку `PENDING`.
  - Админ через бот подтверждает/отклоняет заявку; при подтверждении создаётся запись в истории операций.
  - Фактическая отправка средств в сеть остаётся ручной/внешней задачей.

- **Инвестиции**:
  - Backend проверяет, что есть достаточный баланс USDT.
  - Создаёт запись в ledger с типом INVEST и уменьшает доступный баланс.

Поток пополнения реализован через Crypto Pay (`/crypto/invoices`) и леджер (`ledger_transactions`).

---

## 3. Баланс пользователя

Баланс пользователя в интерфейсе бота возвращается эндпоинтом `GET /v1/wallet/balances` и считается в сервисе `wallet_service.get_balances`.

### USDT

Для USDT используется **ledger‑подход** (таблица `ledger_transactions`) c типами (см. `ledger_service`):

- `DEPOSIT` — любое пополнение (в т.ч. оплаченное инвойсом Crypto Pay);
- `INVEST` — перевод средств в сделку (инвестиция);
- `PROFIT` — начисленная прибыль по сделке;
- `WITHDRAW` — списание при подтверждённом выводе.

Функция `get_balance_usdt` считает:

- сумму `amount_usdt` по типам `DEPOSIT` и `PROFIT`;
- минус сумму `amount_usdt` по типам `INVEST` и `WITHDRAW`.

Связка с остальной логикой:

- **Пополнения через Crypto Pay**:
  - создают запись в таблице `invoices` (связка «инвойс ↔ пользователь»);
  - при статусе `paid` создаётся запись в `ledger_transactions` с типом `DEPOSIT`;
  - поле `users.balance_usdt` пересчитывается как кэш из ledger для быстрого отображения.
- **Выводы**:
  - пользователь создаёт заявку `withdraw_requests` (PENDING);
  - при `approve` в админ‑dashboard создаётся `LedgerTransaction` с типом `WITHDRAW`, а `users.balance_usdt` синхронизируется с ledger;
  - сам on‑chain вывод (перевод USDT) выполняется вручную/внешними инструментами.
- **Инвестиции и сделки**:
  - при `POST /api/invest` баланс проверяется через `get_balance_usdt`;
  - создаётся запись в `ledger_transactions` с типом `INVEST`, уменьшающая баланс;
  - сделки и инвестиции дополнительно хранятся в таблицах `deals` и `deal_investments`;
  - планировщик (APScheduler) по расписанию:
    - закрывает открытую сделку (статус `open` → `closed`) и уведомляет инвесторов сообщением «Сбор на сделку #N закрыт, средства идут в работу.»;
    - открывает новую сделку и рассылает всем пользователям «Открыт сбор на сделку #N…»;
    - спустя 24 часа после закрытия начисляет прибыль, возвращает тело инвестиции в ledger и отправляет инвесторам сообщение «Сделка #N отработана. Ваш доход X%.».

### USDC

USDC поддерживается как «legacy» и считается по таблице `wallet_transactions`:

- DEPOSIT — пополнение;
- WITHDRAW — списание;
- баланс = сумма DEPOSIT − сумма WITHDRAW (`status = COMPLETED`).

### Что видит пользователь в боте

Эндпоинт `GET /v1/wallet/balances` возвращает словарь вида:

```json
{
  "USDT": "...",
  "USDC": "..."
}
```

В хендлере профиля/баланса бот просто отображает эти значения.

---

## 4. База данных

Подробная схема есть в миграциях Alembic (`backend/alembic/versions`). Кратко по ключевым таблицам:

- `users` — пользователи, Telegram‑идентификаторы, профиль, рефералы, поле `balance_usdt` (кэш баланса USDT).
- `deposit_requests` — «ручные» заявки на пополнение (PENDING/APPROVED/REJECTED), могут использоваться для админских сценариев.
- `withdraw_requests` — заявки на вывод (аналогично).
- `wallet_transactions` — история по заявкам (DEPOSIT/WITHDRAW) и старая логика балансов (для USDC и legacy‑кейсов).
- `ledger_transactions` — журнал операций по USDT (`DEPOSIT` / `INVEST` / `PROFIT` / `WITHDRAW`).
- `invoices` — инвойсы Crypto Pay: `invoice_id`, `user_id`, `amount`, `asset`, `status`, `created_at`, `paid_at`.
- `deals`, `deal_investments` — сделки и инвестиции в них.
- `admin_tokens`, `admin_logs` — одноразовые токены доступа в админ‑dashboard и журнал админских действий.

Более подробное описание см. в `docs/PROJECT_REPORT.md`.

---

## 5. Конфигурация (.env)

Пример `.env.example` в корне проекта. Ключевые параметры:

```env
PROJECT_NAME=Invext
DATABASE_URL=postgresql+asyncpg://user:password@db:5432/invext
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000

ADMIN_API_KEY=...
ADMIN_TELEGRAM_IDS=123456789
ADMIN_JWT_SECRET=change-me
ADMIN_ALLOWED_IPS=  # опционально, список IP через запятую

MIN_DEPOSIT=1
MAX_DEPOSIT=100000
MIN_WITHDRAW=1
MAX_WITHDRAW=100000

BOT_TOKEN=...

CRYPTO_PAY_TOKEN=...
APP_URL=https://your-domain.com
```

Пояснения:

- `DATABASE_URL` — строка подключения к PostgreSQL (используется backend и Alembic).
- `ADMIN_API_KEY` — ключ, которым бот подписывает админские запросы к backend (legacy‑админка по API).
- `ADMIN_TELEGRAM_IDS` — ID админов (строка с числами через запятую).
- `ADMIN_JWT_SECRET` — секрет для подписи JWT‑сессий админ‑dashboard (`/database`).
- `ADMIN_ALLOWED_IPS` — (опционально) список IP через запятую, которым разрешён доступ к `/database/api/*`. Если пусто — доступ не ограничен по IP.
- `MIN_*` / `MAX_*` — лимиты для валидации сумм.
- `BOT_TOKEN` — токен бота от `@BotFather`.
- `CRYPTO_PAY_TOKEN` — API‑токен Crypto Pay (создаётся в `@CryptoBot` → Crypto Pay → My Apps).
- `APP_URL` — внешний URL backend (нужен для настройки webhook в Crypto Pay).

---

## 6. Запуск и окружения

### В Docker (рекомендуется)

В корне проекта:

```bash
cp .env.example .env
# заполнить значения в .env

docker compose up --build
```

Запустятся:

- `db` — PostgreSQL;
- `app` — backend (с автоматическим `alembic upgrade head`);
- `bot` — Telegram‑бот;
- `admin-frontend` — статический фронтенд админ‑dashboard;
- `nginx` — единая точка входа.

Основные адреса:

- Backend API: `http://localhost:8000` (Swagger — `http://localhost:8000/docs`).
- Админ‑dashboard: `http://localhost/database` (логин через одноразовый токен).

### Локально (backend без Docker)

1. Запустить PostgreSQL (через Docker или системный):
   ```bash
   docker compose up -d db
   ```
2. Создать и активировать виртуальное окружение:
   ```bash
   cd backend
   python -m venv .venv
   .venv\Scripts\activate  # Windows
   # source .venv/bin/activate  # Linux/macOS
   pip install -r requirements.txt
   ```
3. Применить миграции:
   ```bash
   alembic upgrade head
   ```
4. Запустить backend:
   ```bash
   uvicorn src.main:app --reload --port 8000
   ```
5. В отдельном терминале запустить бота (`bot/`), передав нужные переменные окружения (`BOT_TOKEN`, `BACKEND_BASE_URL` и др.).

---

## 7. Безопасность и секреты

Основные принципы:

- Все секреты (`DATABASE_URL`, `CRYPTO_PAY_TOKEN`, `ADMIN_API_KEY`, `BOT_TOKEN`) хранятся только в `.env` / переменных окружения и **не коммитятся** в репозиторий.
- Backend не работает с приватными ключами и seed‑фразами, не подписывает блокчейн‑транзакции.
- Webhook Crypto Pay проверяется по HMAC‑подписи (см. `crypto_pay` router).
- Доступ к админским операциям в боте ограничен по `ADMIN_TELEGRAM_IDS` и `ADMIN_API_KEY`.

---

## 8. Планы на развитие

Краткий список следующих шагов:

- **Полная интеграция Crypto Pay с ledger**:
  - при оплате инвойса создавать запись в `ledger_transactions` с типом DEPOSIT;
  - при подтверждении вывода создавать запись WITHDRAW в ledger;
  - вычислять USDT‑баланс строго из ledger, а `balance_usdt` использовать как кэш.
- **Автоматизация вывода**:
  - вынести отправку средств в отдельный сервис (signer + hot wallet);
  - добавить лимиты на вывод и мониторинг.
- **Расширение инвест‑модуля**:
  - таблица сделок, статусы, проценты, реинвестирование.
- **Тесты** для ключевых сервисов (`wallet_service`, `crypto_pay_service`, заявок, инвестиций).

