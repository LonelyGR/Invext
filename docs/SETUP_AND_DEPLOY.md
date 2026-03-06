# Первичная настройка и деплой Invext

## Содержание

1. [Требования](#1-требования)
2. [Подготовка `.env`](#2-подготовка-env)
3. [Локальный запуск через Docker](#3-локальный-запуск-через-docker)
4. [Деплой на сервер (Docker Compose)](#4-деплой-на-сервер-docker-compose)
5. [Настройка Crypto Pay webhook](#5-настройка-crypto-pay-webhook)
6. [Админ‑dashboard `/database`](#6-админ-dashboard-database)

---

## 1. Требования

- ОС: Linux/Windows/macOS (для продакшена рекомендуются Linux‑серверы).
- Установлено:
  - Docker (`docker --version`);
  - Docker Compose v2 (`docker compose version`).
- Открытые порты на сервере:
  - `80` (HTTP) — для Nginx (можно повесить на него HTTPS через внешний reverse‑proxy или Traefik/Certbot);
  - `5432` (PostgreSQL) — **не обязательно** публиковать наружу.

---

## 2. Подготовка `.env`

В корне проекта есть пример:

```bash
cp .env.example .env
```

Обязательные поля, которые нужно заполнить/проверить:

- **База данных**
  - `DATABASE_URL=postgresql+asyncpg://user:password@db:5432/invext`
  - при необходимости поменять логин/пароль/имя БД.
- **Backend**
  - `PROJECT_NAME=Invext`
  - `BACKEND_HOST=0.0.0.0`
  - `BACKEND_PORT=8000`
- **Админ‑ключи (бот + dashboard)**
  - `ADMIN_API_KEY=...` — секрет, которым бот подписывает админские запросы к legacy‑админке.
  - `ADMIN_TELEGRAM_IDS=...` — список Telegram ID админов (через запятую).
  - `ADMIN_JWT_SECRET=...` — длинная случайная строка (секрет для JWT‑сессий `/database`).
  - `ADMIN_ALLOWED_IPS=` — (опционально) список IP через запятую, которым разрешён доступ к `/database/api/*` (если пусто — без ограничения по IP).
- **Бот**
  - `BOT_TOKEN=...` — токен из `@BotFather`.
  - `BACKEND_BASE_URL=http://app:8000` — URL backend для бота внутри Docker‑сети.
- **Лимиты**
  - `MIN_DEPOSIT`, `MAX_DEPOSIT`
  - `MIN_WITHDRAW`, `MAX_WITHDRAW`
- **Crypto Pay**
  - `CRYPTO_PAY_TOKEN=...` — API‑токен приложения из `@CryptoBot` → Crypto Pay → My Apps.
  - `APP_URL=https://your-domain.com` — публичный HTTPS‑URL backend (нужен для webhook).

Все секреты (`DATABASE_URL`, `BOT_TOKEN`, `CRYPTO_PAY_TOKEN`, `ADMIN_*`) не должны попадать в git.

---

## 3. Локальный запуск через Docker

В корне проекта:

```bash
docker compose up --build
```

После успешного старта:

- Backend API: `http://localhost:8000` (Swagger — `http://localhost:8000/docs`);
- Бот: подключается по `BOT_TOKEN` (убедитесь, что токен корректный);
- Админ‑dashboard: `http://localhost/database`.

Миграции Alembic применяются автоматически при старте backend (`alembic upgrade head` в `Dockerfile`).

Остановка и чистый запуск:

```bash
docker compose down
docker compose up --build
```

---

## 4. Деплой на сервер (Docker Compose)

Шаги типового деплоя на VPS:

1. Скопировать код на сервер (git clone или rsync).
2. Установить Docker / Docker Compose.
3. Создать `.env` и заполнить значения (особенно `DATABASE_URL`, `BOT_TOKEN`, `CRYPTO_PAY_TOKEN`, `ADMIN_JWT_SECRET`, `APP_URL`).
4. Запустить стек в фоне:

   ```bash
   docker compose up -d --build
   ```

5. Проверить состояние контейнеров:

   ```bash
   docker compose ps
   docker compose logs app -f
   docker compose logs bot -f
   docker compose logs nginx -f
   ```

6. Настроить DNS, чтобы домен (например, `your-domain.com`) указывал на IP сервера.
7. Повесить HTTPS (варианты):
   - внешний reverse‑proxy (Cloudflare, nginx на хосте, Traefik);
   - выделенный Nginx/Certbot вне Docker (за рамками этого файла).

По умолчанию Nginx внутри Docker слушает `80` и отдаёт:

- `/database` → контейнер `admin-frontend`;
- `/database/api` → контейнер `app` (FastAPI).

При необходимости вы можете расширить конфиг `nginx/nginx.conf` под свой домен/SSL.

---

## 5. Настройка Crypto Pay webhook

1. Убедиться, что backend доступен по `APP_URL` (например, `https://your-domain.com`).
2. Прописать `APP_URL` в `.env` и перезапустить стек:

   ```bash
   docker compose down
   docker compose up -d --build
   ```

3. В `@CryptoBot` → Crypto Pay → My Apps → нужное приложение:
   - нажать **Webhooks…**;
   - включить webhooks;
   - указать URL: `https://your-domain.com/crypto/webhook`.

4. Проверить, что при оплате тестового инвойса:
   - в логах backend виден вызов `/crypto/webhook`;
   - баланс пользователя увеличивается;
   - инвойс меняет статус на `paid`.

Если нет возможности настроить webhook (например, при локальной разработке), можно использовать ручной sync через `/crypto/invoices/{invoice_id}/sync` (бот уже вызывает этот endpoint по кнопке «Проверить оплату»).

---

## 6. Админ‑dashboard `/database`

Админ‑панель живёт по пути `/database` и состоит из двух частей:

- статический frontend (`admin-frontend/` → Nginx → `/database`);
- закрытое API backend (`/database/api/*`).

### 6.1. Вход через одноразовый токен

1. Админ в Telegram‑боте нажимает кнопку «Токен для админ‑сайта» (админ‑меню), бот запрашивает токен в backend и показывает:
   - сам UUID‑токен;
   - прямую ссылку вида `APP_URL/database` (если `APP_URL` задан корректно).
2. Токен сохраняется в таблицу `admin_tokens` и живёт 24 часа (`expires_at = now + 24h`).
3. Админ открывает `/database` (или ссылку из бота), вводит токен в форму логина.
4. Backend:
   - валидирует токен (`admin_tokens.token`, `expires_at`);
   - создаёт JWT‑сессию и устанавливает httpOnly‑cookie `admin_jwt` на 24 часа;
   - помечает токен как `is_used = true` (одноразовый сценарий);
   - пишет запись в `admin_logs` с типом `LOGIN`.

### 6.2. Защита API `/database/api/*`

- Все запросы, кроме `POST /database/api/login`, проходят через middleware:
  - проверяется JWT‑cookie `admin_jwt` (подпись через `ADMIN_JWT_SECRET`);
  - при наличии `ADMIN_ALLOWED_IPS` проверяется, что IP клиента входит в список.
- При ошибке авторизации возвращается `401/403`.

### 6.3. Основные разделы

- **Dashboard**:
  - общее количество пользователей;
  - суммарный баланс по ledger (USDT);
  - активная сделка и сумма инвестиций в неё;
  - количество `PENDING`‑выводов.
- **Users**:
  - таблица пользователей с `balance_usdt`, `ledger_balance`, текущими инвестициями;
  - поиск по username / Telegram ID;
  - переход на страницу конкретного пользователя.
- **User detail**:
  - основная информация о пользователе;
  - история по ledger с цветовой индикацией (`DEPOSIT/PROFIT` зелёным, `INVEST/WITHDRAW` красным);
  - экспорт ledger в CSV;
  - список инвестиций и заявок на вывод.
- **Withdrawals**:
  - список заявок на вывод (по умолчанию PENDING);
  - кнопки `Approve` / `Reject`:
    - при `Approve` создаётся ledger‑запись `WITHDRAW` и обновляется кэш `balance_usdt`;
    - действия логируются в `admin_logs`.
- **Logs**:
  - просмотр `admin_logs` (входы, approve/reject, просмотры ключевых страниц);
  - фильтрация по дате и строке поиска.

Админ‑панель использует только закрытое API `/database/api/*` и не даёт прямого доступа к остальным эндпоинтам backend. Для безопасности всегда держите `ADMIN_JWT_SECRET` и `ADMIN_API_KEY` в секрете и, по возможности, ограничивайте доступ к `/database/api` по IP. 
