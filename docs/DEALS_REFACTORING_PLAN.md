# План рефакторинга: сделки, участие, рефералы, уведомления

## 1. Аудит текущего кода (кратко)

- **Модели сделок:** `Deal` (number, percent, status open/closed/finished, opened_at, closed_at, finished_at), `DealInvestment` (deal_id, user_id, amount, profit_amount, status active/paid).
- **Участие:** один пользователь может создать несколько DealInvestment в одну сделку (нет unique constraint). Роутер `POST /api/invest`, сервис `invest_into_active_deal` — списание INVEST в ledger, создание DealInvestment.
- **Реферальная система:** User.ref_code, User.referrer_id (один уровень). Бонусы по сделкам не начисляются.
- **Уведомления:** в `deal_service` — рассылка о новой сделке всем, о закрытии сбора только инвесторам, об отработанной сделке только инвесторам. Отправка с бэкенда через Telegram API.
- **Планировщик:** 12:00 UTC+1 закрыть сделку, 13:00 UTC+1 открыть новую, каждые 5 мин — начисление прибыли по «зрелым» сделкам.

Подробный аудит: `docs/AUDIT_DEALS_REFERRALS_NOTIFICATIONS.md`.

---

## 2. План изменений

### 2.1 Модель Deal (обновить)

- **Новые/изменяемые поля:** title, start_at, end_at, status (draft | active | closed | completed), profit_percent, referral_processed (bool), close_notification_sent (bool), created_at, updated_at.
- **Сохранять для отображения:** number (для «Сделка #N»).
- **Убрать/не использовать в новой логике:** percent (заменён на profit_percent), opened_at/closed_at/finished_at (заменены на start_at/end_at и status).

### 2.2 Новая таблица deal_participations

- Поля: id, deal_id, user_id, amount, created_at.
- Ограничение: UNIQUE(deal_id, user_id) — один пользователь одно участие в сделке.
- Участие = списание с баланса (ledger INVEST) + запись в deal_participations. Старая таблица deal_investments остаётся для истории, новая логика только deal_participations.

### 2.3 Новая таблица referral_rewards

- Поля: id, deal_id, from_user_id, to_user_id, level, amount, created_at, status.
- Начисление после закрытия сделки: для каждого участника обход цепочки рефереров до 10 уровней; если реферер участвовал в этой же сделке — создать запись и начислить бонус на баланс (ledger REFERRAL_BONUS).

### 2.4 Леджер

- Добавить тип LEDGER_TYPE_REFERRAL_BONUS для начисления реферальных бонусов.

### 2.5 Алгоритм закрытия сделки

1. Найти сделки с status=active и end_at <= now.
2. Для каждой: установить status=closed.
3. Обработать реферальные начисления (если ещё не referral_processed): создать referral_rewards, проводки в ledger, установить referral_processed=True.
4. Разослать уведомления (если ещё не close_notification_sent): всем пользователям разный текст (участникам — с прибылью profit_percent), установить close_notification_sent=True.

### 2.6 Уведомления

- После закрытия: всем пользователям с telegram_id сообщение «Сделка #N завершена.»; участникам добавить «Ваша прибыль: M%» (M = deal.profit_percent).

### 2.7 Планировщик

- Убрать фиксированные 12:00/13:00. Добавить периодический джоб (например каждую минуту): найти сделки с status=active и end_at <= now, для каждой выполнить алгоритм закрытия.

### 2.8 Админка

- Сделки: поля title, start_at, end_at, profit_percent, status; возможность создавать/редактировать; отображение referral_processed и close_notification_sent.

---

## 3. Список изменяемых/новых файлов

| Файл | Действие |
|------|----------|
| backend/src/models/deal.py | Обновить: новые поля, статусы |
| backend/src/models/deal_participation.py | Создать |
| backend/src/models/referral_reward.py | Создать |
| backend/src/models/__init__.py | Экспорт новых моделей |
| backend/src/models/user.py | Связь deal_participations (опционально) |
| backend/src/services/ledger_service.py | Добавить LEDGER_TYPE_REFERRAL_BONUS |
| backend/src/services/deal_service.py | Переписать: активная сделка по start_at/end_at, участие в deal_participations, закрытие, рефералы, уведомления |
| backend/src/services/notification_service.py | Создать: отправка в Telegram (закрытие сделки) |
| backend/src/api/routers/invest.py | Использовать новую логику участия (deal_participations) |
| backend/src/api/routers/admin_dashboard.py | Сделки: новые поля, profit_percent, CRUD под новую модель |
| backend/src/schemas/admin_dashboard.py | DealRow, DealUpdateRequest с новыми полями |
| backend/alembic/versions/011_deals_refactor_participations_referral_rewards.py | Миграция |
| backend/src/main.py | Планировщик: один джоб закрытия по end_at |
| docs/DEALS_REFACTORING_PLAN.md | Этот документ |

Старая таблица deal_investments и модель DealInvestment не удаляются (история); новый поток только через deal_participations и обновлённый Deal.

---

## 4. Инструкция по тестированию

### 4.1 Миграции
- Выполнить: `alembic upgrade head` (из каталога backend).
- Проверить: в БД появились колонки в `deals` (title, start_at, end_at, profit_percent, referral_processed, close_notification_sent, created_at, updated_at), таблицы `deal_participations` и `referral_rewards`.

### 4.2 Участие в сделке (одно на пользователя)
- Создать сделку в админке (draft), выставить start_at и end_at так, чтобы окно было открыто (now между start_at и end_at), status=active (или создать с окном — тогда станет active). Указать profit_percent (например 18).
- От имени пользователя с балансом: `POST /api/invest` с body `{"user_id": <telegram_id>, "amount_usdt": 100}`.
- Повторный запрос с теми же user_id и той же сделкой должен вернуть 400: «Вы уже участвуете в этой сделке».

### 4.3 Закрытие сделки
- У сделки выставить end_at в прошлое (или подождать минуту — джоб раз в минуту).
- После срабатывания джоба: status=closed, referral_processed=True, close_notification_sent=True.
- В Telegram всем пользователям приходит «Сделка #N завершена.»; участникам — с добавлением «Ваша прибыль: 18%» (если profit_percent=18).

### 4.4 Реферальные начисления
- Пользователь A (реферер) и B (реферал, referrer_id=A) оба участвуют в одной сделке до закрытия.
- После закрытия: в таблице referral_rewards появляются записи (from_user_id=B, to_user_id=A, level=1, amount=...).
- Баланс A увеличивается на реферальный бонус (ledger REFERRAL_BONUS).

### 4.5 Защита от повторной обработки
- Дважды не начислять рефералы: флаг referral_processed.
- Дважды не слать уведомления: флаг close_notification_sent.
- При повторном запуске джоба для уже закрытой сделки ничего не делать.
