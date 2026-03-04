# Invext

Telegram‑бот + backend для внутреннего USDT/USDC‑баланса, пополнений через Crypto Pay (CryptoBot), заявок на вывод и простых инвестиций.

- **Этот файл (`README.md` в корне)** — короткий обзор и быстрый старт.
- **Подробная документация** — в `docs/`:
  - `docs/README.md` — общая архитектура и описание проекта;
  - `docs/DEPOSITS_ARCHITECTURE.md` — архитектура пополнений через Crypto Pay и ledger;
  - `docs/PROJECT_REPORT.md` — технический отчёт;
  - `docs/SETUP_AND_DEPLOY.md` — первичная настройка и деплой.

## Быстрый старт (Docker)

```bash
cd Invext
cp .env.example .env
# заполнить переменные в .env (см. docs/SETUP_AND_DEPLOY.md и docs/ENV_VARS.md)
docker compose up --build
```

После старта:

- Backend API: `http://localhost:8000` (Swagger: `/docs`)
- Админ‑dashboard: `http://localhost/database`

Подробнее про назначение переменных окружения и сценарии работы см. в `docs/ENV_VARS.md` и `docs/README.md`.
