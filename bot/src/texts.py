"""
Все текстовые сообщения бота, вынесенные в один модуль
для удобного редактирования и форматирования.
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Mapping, Any


# === formatting helpers ===

def _fmt_usdt(value: Any) -> str:
    """
    Формат денег для UI: всегда 2 знака после запятой.
    Не влияет на расчёты — только отображение.
    """
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "0.00"


# === /start, приветствие ===

WELCOME_ABOUT = """📊 <b>О проекте</b>

Создаём программные решения для трейдинга на биржах — спотовые и фьючерсные рынки.

📈 <b>Простые условия:</b>
• 1 сделка в сутки  
• Фиксированный лимит — 50$  
• Минимум действий со стороны пользователя  

💸 <b>Дополнительный доход:</b>
10-уровневая реферальная система  
+0,5% с каждой сделки партнёров  

🗓 <b>Торговые дни:</b> Пн–Пт  
Выходные: Сб–Вс"""

def format_personal_data(
    me: Mapping[str, Any],
    balances: Mapping[str, Any],
    invested_usdt: str = "0.00",
    ref_link: str | None = None,
) -> str:
    """Формирует блок «Личные данные» для второго сообщения при /start."""
    usdt_s = _fmt_usdt(balances.get("USDT", 0) or 0)

    name = me.get("name") or me.get("username") or "не указано"
    email = me.get("email") or "не указано"
    country = me.get("country") or "не указано"
    referrals = me.get("referrals_count", 0)

    if ref_link:
        ref_block = f"🔗 Реферальная ссылка:\n{ref_link}"
    else:
        ref_block = "⚠️ Реферальная ссылка временно недоступна. Попробуйте позже."

    return (
        "<b>👤 Профиль</b>\n\n"

        "💰 <b>Баланс</b>\n"
        f"USDT: {usdt_s}\n\n"

        "🔒 <b>В инвестициях</b>\n"
        f"USDT: {invested_usdt}\n\n"

        "📌 <b>Личные данные</b>\n"
        f"Имя: {name}\n"
        f"Email: {email}\n"
        f"Страна: {country}\n\n"

        "👥 <b>Рефералы</b>\n"
        f"Количество: {referrals}\n"
        f"{ref_block}"
    )


# === Баланс ===

def make_balance_text(usdt: Any) -> str:
    """Основной экран раздела «Баланс»."""
    return (
        "💰 <b>Баланс</b>\n\n"
        f"USDT: {_fmt_usdt(usdt)}\n\n"
        "📌 Реферальные бонусы уже включены в баланс\n"
        "Вы можете использовать их для инвестиций или вывести в любой момент."
    )


# === Пополнение (депозит) ===

def make_deposit_start_text(min_dep: Any) -> str:
    """Текст запроса суммы пополнения."""
    return (
        "💳 <b>Пополнение баланса</b>\n\n"
        "Введите сумму в USD:\n\n"
        f"Минимальная сумма — {min_dep}\n"
        "Сеть: BEP20 (USDT)"
    )


def make_deposit_history_intro_text() -> str:
    """Короткое пояснение перед кнопкой «История пополнений»."""
    return (
        "📄 История пополнений доступна ниже.\n"
        "Нажмите кнопку «История пополнений», чтобы открыть список."
    )


def make_deposit_invoice_text(amount: Any) -> str:
    """Текст с созданным инвойсом NOWPayments."""
    return (
        "💳 <b>Пополнение через NOWPayments</b>\n\n"
        
        f"💰 Сумма: <b>{_fmt_usdt(amount)} USD</b>\n"
        "Сеть: BEP20 (USDT)\n\n"
        
        "📌 Как оплатить:\n"
        "1. Нажмите «Оплатить» и переведите USDT\n"
        "2. После оплаты нажмите «Проверить оплату»"
    )


def make_deposit_history_empty_text() -> str:
    """Текст, когда у пользователя нет пополнений."""
    return (
        "📭 <b>Пополнений пока нет</b>\n\n"
        "Введите сумму выше, чтобы создать счёт на оплату"
    )


def make_deposit_history_list_text(items: Iterable[Mapping[str, Any]]) -> str:
    """Список последних пополнений пользователя."""
    lines = [    "📋 <b>История пополнений</b>\n"
                    "Сеть: BEP20 (USDT)\n"]
    status_ru = {
        "finished": "✅ Оплачено",
        "waiting": "⏳ Ожидание оплаты",
        "partially_paid": "🟡 Частичная оплата",
        "expired": "⌛ Счёт истёк",
        "failed": "❌ Ошибка оплаты",
    }
    for inv in items:
        st = status_ru.get(str(inv.get("status", "")).lower(), inv.get("status", ""))
        cred = " (баланс начислен)" if inv.get("balance_credited") else ""
        dt_str = ""
        if inv.get("created_at"):
            try:
                dt_str = " " + str(inv["created_at"])[:16].replace("T", " ")
            except Exception:
                dt_str = ""
        lines.append(f"• +{_fmt_usdt(inv.get('amount', 0))} USDT — {st}{cred}{dt_str}")
    text = "\n".join(lines)
    if len(text) > 4000:
        text = "\n".join(lines[:12]) + "\n\n… и ещё."
    return text


def make_deposit_invoice_confirmed_text() -> str:
    """Короткое сообщение после успешного депозита по инвойсу."""
    return (
        "✅ Оплата подтверждена.\n\n"
        "Проверьте раздел «Баланс» — средства уже зачислены."
    )


def make_deposit_balance_credited_text() -> str:
    """Сообщение после успешного депозита, которое отправляется отдельным эффектным сообщением."""
    return (
        "✅ <b>Оплата получена</b>\n\n"
        "Средства уже зачислены на баланс\n"
        "Проверьте раздел «Баланс»"
    )


# === Вывод средств ===

def make_withdraw_choose_currency_text() -> str:
    return (
        "Выберите валюту вывода:\n\n"
        "ℹ️ Укажите сумму <b>списания с баланса</b>. Комиссия <b>10%</b> от неё "
    )


def make_withdraw_enter_amount_text(currency: str, min_wd: Any) -> str:
    return (
        f"💸 <b>Вывод средств ({currency})</b>\n\n"
        "Введите сумму <b>списания с баланса</b> (полную сумму заявки):\n\n"
        f"Минимум — {min_wd}\n\n"
        "Комиссия — <b>10%</b> от этой суммы."
    )


def make_withdraw_enter_address_text() -> str:
    return (
        "🏦 <b>Адрес для вывода</b>\n\n"
        "Введите адрес кошелька в сети BEP20, на который поступит сумма после вычета комиссии 10%."
    )


def make_withdraw_success_text(
    req_id: Any,
    *,
    gross: Any,
    fee: Any,
    net: Any,
    currency: str = "USDT",
) -> str:
    return (
        "✅ <b>Заявка на вывод создана</b>\n\n"
        "Заявка отправлена на проверку\n"
        "Средства будут переведены в течение 48 часов\n\n"
        f"Списание с баланса: <b>{gross}</b> {currency}\n"
        f"Комиссия (10%): <b>{fee}</b> {currency}\n"
        f"К получению на кошелёк: <b>{net}</b> {currency}\n\n"
        f"🆔 ID заявки: {req_id}"
    )


def make_my_withdrawals_list_text(items: list) -> str:
    """Текст экрана «мои заявки» (items — ответ /v1/withdrawals/my)."""
    status_ru = {
        "PENDING": "⏳ в обработке",
        "APPROVED": "✅ одобрена",
        "REJECTED": "❌ отклонена",
        "CANCELLED": "🚫 отменена",
    }
    header = "📋 <b>Ваши заявки на вывод</b>\n\n"
    if not items:
        return header + "Пока заявок нет.\n\nНажмите «Новая заявка», чтобы создать."
    lines: list[str] = [header]
    for it in items[:30]:
        wid = it.get("id")
        cur = it.get("currency") or "—"
        gross = it.get("amount")
        net = it.get("net_amount", "—")
        st = status_ru.get(str(it.get("status")), str(it.get("status")))
        created = it.get("created_at")
        created_s = ""
        if created:
            raw = str(created).replace("Z", "+00:00")
            try:
                d = datetime.fromisoformat(raw)
                created_s = d.strftime("%d.%m.%Y %H:%M")
            except Exception:
                created_s = str(created)[:16]
        lines.append(
            f"🆔 <b>#{wid}</b> · {cur}\n"
            f"   списание <b>{gross}</b> · к кошельку <b>{net}</b>\n"
            f"   {st}"
            + (f" · {created_s}" if created_s else "")
        )
    lines.append("")
    lines.append("<i>Отменить можно только заявки «в обработке».</i>")
    return "\n".join(lines)


# === Инвестиции (раздел «Сделка») ===

def make_invest_main_text_with_deal(
    deal_number: Any,
    available_usdt: str,
    deal_amount_hint: str | None = None,
    action_hint: str | None = None,
) -> str:
    amount_line = f"{deal_amount_hint}\n\n" if deal_amount_hint else ""
    action_line = action_hint or "Минимальная сумма будет показана при вводе"
    return (
        f"🚀 <b>Открыт сбор на сделку №{deal_number}</b>\n\n"
        
        "💰 <b>Доступный баланс</b>\n"
        f"USDT: {available_usdt}\n\n"
        f"{amount_line}"
        "📌 Нажмите «Участвовать», чтобы вложить средства\n"
        f"{action_line}"
    )


def make_invest_main_text_no_deal() -> str:
    return (
        "📭 <b>Сейчас нет активного сбора</b>\n\n"
        "Ожидайте уведомление о новом сборе.\n\n"
        "После уведомления перейдите в раздел <b>📈 Сделка</b> "
        "и нажмите «Участвовать»"
    )


def make_invest_enter_amount_text(hint: str) -> str:
    return (
        "💸 <b>Сумма инвестиции</b>\n\n"
        "Введите сумму:\n\n"
        f"{hint}\n\n"
        "После ввода бот сразу проверит лимиты и баланс."
    )


def make_invest_success_text(invested: Any, new_balance: Any, payout_hint: str | None = None) -> str:
    payout_line = f"⏳ Выплата: {payout_hint}\n\n" if payout_hint else ""
    return (
        "✅ <b>Инвестиция принята</b>\n\n"
        
        f"💰 Сумма: {_fmt_usdt(invested)} USDT\n"
        f"📊 Баланс: {_fmt_usdt(new_balance)} USDT\n\n"
        f"{payout_line}"
        "Средства участвуют в текущей сделке.\n"
        "Срок выплаты после закрытия сбора задаётся расписанием в системе."
    )


def make_invest_deals_split_text(
    active_items: list[str],
    completed_items: list[str],
) -> str:
    active_block = "\n".join(active_items) if active_items else "— нет"
    completed_block = "\n".join(completed_items) if completed_items else "— нет"
    return (
        "\n\n📂 <b>Мои сделки</b>\n"
        f"🔄 Активные:\n{active_block}\n\n"
        f"✅ Завершённые(последние 3):\n{completed_block}"
    )


def make_invest_deals_dashboard_text(
    *,
    active_deal_number: Any | None,
    collecting_end: str | None,
    balance_usdt: Any,
    participate_amount_usdt: Any | None,
    pending_payout_block: str,
    history_lines: list[str],
    already_participating: bool = False,
    participation_in_open_deal_usdt: Any | None = None,
) -> str:
    sep = "────────────────"

    header_lines: list[str] = []
    if active_deal_number is not None:
        header_lines.append(f"🚀 <b>Сделка №{active_deal_number} открыта</b>\n")
        header_lines.append(f"💰 Ваш баланс: <b>{_fmt_usdt(balance_usdt)} USDT</b>\n")
        if already_participating:
            if participation_in_open_deal_usdt is not None:
                header_lines.append(
                    f"💵 Ваш вклад в этом сборе: <b>{_fmt_usdt(participation_in_open_deal_usdt)} USDT</b>\n"
                )
            header_lines.append(
                "✅ <b>Вы уже участвуете в этой сделке.</b>\n"
                "В одном сборе можно оформить только одно участие. "
                "Дальше просто дождитесь закрытия сбора — выплата будет по расписанию."
            )
        else:
            if participate_amount_usdt is not None:
                header_lines.append(f"💵 Сумма участия: <b>{_fmt_usdt(participate_amount_usdt)} USDT</b>\n")
            header_lines.append("👉 Нажмите «Участвовать», чтобы войти в сделку")
    else:
        header_lines.append("📭 <b>Сейчас нет активного сбора</b>\n")
        header_lines.append("Ожидайте уведомление о новом сборе.")

    in_work_block = pending_payout_block.strip() if pending_payout_block else "—"
    history_block = "\n".join(history_lines) if history_lines else "—"
    collecting_block = (
        f"🟡 <b>Сбор средств:</b>\nСделка #{active_deal_number}\nДо: {collecting_end or '—'}"
        if active_deal_number is not None
        else "🟡 <b>Сбор средств:</b>\n—"
    )
    return (
        "\n".join(header_lines).strip()
        + f"\n\n{sep}\n\n"
        f"{collecting_block}\n\n{sep}\n\n"
        "📊 <b>Ваши средства</b>\n\n"
        "🔥 <b>Ожидает выплаты:</b>\n"
        f"{in_work_block}\n\n"
        f"{sep}\n\n"
        "✅ <b>История выплат:</b>\n"
        f"{history_block}"
    )


# === Партнёрка / команда / бонусы ===

_PARTNERS_LEVEL_EMOJI = (
    "1️⃣",
    "2️⃣",
    "3️⃣",
    "4️⃣",
    "5️⃣",
    "6️⃣",
    "7️⃣",
    "8️⃣",
    "9️⃣",
    "🔟",
)


def make_partners_main_text(me: Mapping[str, Any], link: str | None, levels: list[tuple[float, str]]) -> str:
    sep = "────────────────"

    def _level_count(level: int) -> int:
        value = me.get(f"referrals_level_{level}", 0)
        if level == 1 and not value:
            value = me.get("referrals_count", 0)
        return int(value or 0)

    def _level_earned(level: int) -> str:
        # Источник: backend отдаёт агрегаты в /v1/telegram/me (referral_earned_level_{N}_usdt).
        key = f"referral_earned_level_{level}_usdt"
        return _fmt_usdt(me.get(key, "0"))

    if link:
        link_block = f"🔗 <b>Ваша ссылка</b>\n{link}"
    else:
        link_block = "⚠️ Ссылка временно недоступна. Попробуйте позже."

    lines: list[str] = [
        "<b>👥 Партнёрская программа</b>",
        "",
        link_block,
        "",
        sep,
        "",
        "📊 <b>Уровни рефералов</b>",
        "",
    ]
    n = min(len(levels), len(_PARTNERS_LEVEL_EMOJI))
    for i in range(n):
        count = _level_count(i + 1)
        emoji = _PARTNERS_LEVEL_EMOJI[i]
        earned = _level_earned(i + 1)
        lines.append(f"{emoji} {count} чел. • заработано: {earned} USDT")
        if i == 4:
            lines.append("")
    return "\n".join(lines)


def make_partners_no_link_text() -> str:
    return "⚠️ Реферальная ссылка временно недоступна. Попробуйте позже."


def make_partners_team_text(me: Mapping[str, Any]) -> str:
    levels_lines: list[str] = []
    for level in range(1, 11):
        count = me.get(f"referrals_level_{level}", 0)
        if level == 1 and not count:
            count = me.get("referrals_count", 0)
        levels_lines.append(f"{level} уровень — {int(count or 0)}")

    return "<b>📊 Моя команда</b>\n\n" + "\n".join(levels_lines)


# === Статистика ===

def make_stats_text(me: Mapping[str, Any]) -> str:
    d_usdt = me.get("my_deposits_total_usdt", "0")
    w_usdt = me.get("my_withdrawals_total_usdt", "0")
    deposits_count = me.get("deposits_count", 0)
    withdrawals_count = me.get("withdrawals_count", 0)

    balance_usdt = me.get("balance_usdt", "0")
    invested_total = me.get("invested_total_usdt", "0")
    profit_total = me.get("profit_total_usdt", "0")
    referral_income = me.get("referral_income_usdt", "0")

    return (
        "📊 <b>Статистика</b>\n\n"
        
        "💰 <b>Баланс</b>\n"
        f"{_fmt_usdt(balance_usdt)} USDT\n\n"
        
        "💳 <b>Депозиты</b>\n"
        f"{_fmt_usdt(d_usdt)} USDT\n\n"
        
        "💸 <b>Выводы</b>\n"
        f"{_fmt_usdt(w_usdt)} USDT\n\n"
        
        "📈 <b>Инвестиции и прибыль</b>\n"
        f"Инвестировано: {_fmt_usdt(invested_total)} USDT\n"
        f"Прибыль: {_fmt_usdt(profit_total)} USDT\n"
        f"Реферальный доход: {_fmt_usdt(referral_income)} USDT\n\n"
        
        "📄 <b>Заявки</b>\n"
        f"Пополнения: {deposits_count}\n"
        f"Выводы: {withdrawals_count}\n\n"
        "ℹ️ Это сводная статистика по вашему аккаунту на текущий момент."
    )


# === Профиль ===

def make_profile_text(me: Mapping[str, Any], usdt: Any, ref_link: str | None = None) -> str:
    name = me.get("name") or me.get("username") or "не указано"
    email = me.get("email") or "не указано"
    country = me.get("country") or "не указано"
    referrals_count = me.get("referrals_count", 0)

    invested = _fmt_usdt(me.get("invested_total_usdt", "0"))

    if ref_link:
        ref_part = f"🔗 <b>Реферальная ссылка</b>\n{ref_link}"
    else:
        ref_part = "⚠️ Реферальная ссылка временно недоступна. Попробуйте позже."

    return (
        "👤 <b>Профиль</b>\n\n"
        
        "💰 <b>Баланс</b>\n"
        f"{_fmt_usdt(usdt)} USDT\n\n"
        
        "🔒 <b>В инвестициях</b>\n"
        f"{invested} USDT\n\n"
        
        "📌 <b>Личные данные</b>\n"
        f"Имя: {name}\n"
        f"Email: {email}\n"
        f"Страна: {country}\n\n"
        
        "👥 <b>Рефералы</b>\n"
        f"{referrals_count}\n"
        f"{ref_part}"
    )


# === Start / Навигация / Fallback ===

def make_start_load_error_text(error: Any) -> str:
    return f"Ошибка загрузки данных: {error}"


def make_start_registration_error_text(error: Any) -> str:
    return f"Ошибка при регистрации: {error}"


def make_back_menu_title_text() -> str:
    return "Главное меню. Выберите действие:"


def make_back_menu_short_text() -> str:
    return "Выберите действие:"


def make_unknown_message_text() -> str:
    return (
        "Неизвестная команда.\n"
        "Пожалуйста, используйте кнопки меню ниже."
    )


def make_unknown_callback_text() -> str:
    return "Неизвестная команда."


# === Кошельки ===

def make_wallets_list_text(wallets: Iterable[Mapping[str, Any]], text_prefix: str = "") -> str:
    wallets_list = list(wallets)
    bep20_note = "Сеть для всех операций: BEP20.\n\n"
    if not wallets_list:
        return (text_prefix + "💼 <b>Ваши кошельки</b>\n\n" + bep20_note + "У вас нет сохранённых кошельков.").strip()

    lines = []
    for w in wallets_list:
        addr = str(w.get("address", ""))
        addr_show = f"{addr[:24]}..." if len(addr) > 24 else addr
        lines.append(f"• {w.get('name', 'Без названия')} ({w.get('currency', 'USDT')}): <code>{addr_show}</code>")
    return (text_prefix + "💼 <b>Ваши кошельки</b>\n\n" + bep20_note + "\n".join(lines)).strip()


def make_wallets_load_error_text(error: Any) -> str:
    return f"Ошибка: {error}"


def make_wallet_add_enter_name_text() -> str:
    return "Введите название для нового кошелька (например: «Мой основной кошелёк»):"


def make_wallet_name_empty_text() -> str:
    return "Название не может быть пустым. Введите название:"


def make_wallet_choose_currency_text() -> str:
    return "Пожалуйста, выберите валюту в кнопочном меню:"


def make_wallet_invalid_currency_text() -> str:
    return "Неверная валюта"


def make_wallet_currency_set_text(currency: str) -> str:
    return (
        f"Тип кошелька успешно установлен на {currency}!\n"
        f"Теперь отправьте адрес вашего кошелька для сети {currency}."
    )


def make_wallet_cancelled_text() -> str:
    return "Отменено"


def make_wallet_invalid_address_text() -> str:
    return "Адрес не может быть пустым и не более 512 символов."


def make_wallet_save_error_text(error: Any) -> str:
    return f"Ошибка при сохранении: {error}"


def make_wallet_added_text(name: str, currency: str) -> str:
    return f"✅ Кошелёк «{name}» ({currency}) добавлен."


def make_wallet_deleted_text() -> str:
    return "Кошелёк удалён"


# === Админка ===

def make_admin_access_denied_text() -> str:
    return "Доступ запрещён"


def make_admin_panel_text() -> str:
    return "Админ-панель. Выберите раздел:"


def make_admin_token_text(token: str, url: str) -> str:
    text = (
        "🔐 <b>Токен для входа в админ-сайт</b>\n\n"
        f"<code>{token}</code>\n\n"
        "Скопируйте токен, откройте админ-сайт и вставьте в форму входа. "
        "Токен действует 24 ч, одноразовый.\n\n"
    )
    if url and "your-domain" not in url:
        text += f"Админ-сайт: {url}"
    else:
        text += (
            "Админ-сайт: задайте в .env бэкенда APP_URL "
            "(например http://localhost). Страница входа: APP_URL/database"
        )
    return text


def make_admin_error_text(error: Any) -> str:
    return f"Ошибка: {error}"


def make_admin_no_pending_withdrawals_text() -> str:
    return "Нет заявок на вывод в статусе PENDING."


def make_admin_pending_withdrawals_text(items: Iterable[Mapping[str, Any]]) -> str:
    lines = []
    for r in items:
        addr = str(r.get("address", ""))
        fee = r.get("fee_amount")
        net = r.get("net_amount")
        if fee is not None and net is not None:
            amt = f"списание {r.get('amount')}, комиссия {fee}, к выплате {net} {r.get('currency')}"
        else:
            amt = f"{r.get('currency')} {r.get('amount')}"
        line = (
            f"ID: {r.get('id')} | {amt} → "
            f"{addr[:20]}{'...' if len(addr) > 20 else ''} | "
            f"user_id={r.get('user_telegram_id')}"
        )
        lines.append(line)
    return "📤 <b>Заявки на вывод (PENDING)</b>\n\n" + "\n\n".join(lines)


def make_admin_withdraw_card_text(item: Mapping[str, Any]) -> str:
    addr = str(item.get("address", ""))
    cur = item.get("currency", "USDT")
    gross = item.get("amount")
    fee = item.get("fee_amount")
    net = item.get("net_amount")
    if fee is not None and net is not None:
        amt_part = f"списание {gross} {cur}, комиссия {fee}, к выплате {net}"
    else:
        amt_part = f"{cur} {gross}"
    return (
        f"Вывод #{item.get('id')}: {amt_part} | "
        f"Адрес: {addr[:30]}{'...' if len(addr) > 30 else ''} | "
        f"TG: {item.get('user_telegram_id')}"
    )


def make_admin_fin_settings_text(data: Mapping[str, Any]) -> str:
    bonus_flag = data.get("allow_welcome_bonus")
    bonus_line = "включён" if bonus_flag else "выключен"
    return (
        "⚙️ <b>Финансовые настройки</b>\n\n"
        f"Минимальный депозит: {data.get('min_deposit_usdt')} USDT\n"
        f"Максимальный депозит: {data.get('max_deposit_usdt')} USDT\n\n"
        f"Минимальный вывод: {data.get('min_withdraw_usdt')} USDT\n"
        f"Максимальный вывод: {data.get('max_withdraw_usdt')} USDT\n"
        "(лимиты по сумме списания с баланса; комиссия 10%)\n\n"
        f"Минимальная инвестиция: {data.get('min_invest_usdt')} USDT\n"
        f"Максимальная инвестиция: {data.get('max_invest_usdt')} USDT\n\n"
        f"Приветственный бонус 100 USDT: {bonus_line}"
    )


def make_admin_unknown_setting_text() -> str:
    return "Неизвестная настройка"


def make_admin_enter_new_value_text() -> str:
    return "Введите новое значение (только число, > 0):"


def make_admin_invalid_number_text() -> str:
    return "Введите корректное число, например: 10 или 50.5"


def make_admin_value_gt_zero_text() -> str:
    return "Значение должно быть больше 0."


def make_admin_setting_updated_text() -> str:
    return "Настройка обновлена."


def make_admin_withdraw_approved_text(withdraw_id: int) -> str:
    return f"✅ Заявка на вывод #{withdraw_id} одобрена."


def make_admin_withdraw_rejected_text(withdraw_id: int) -> str:
    return f"❌ Заявка на вывод #{withdraw_id} отклонена."


def make_admin_invalid_request_data_text() -> str:
    return "Некорректные данные запроса"


def make_admin_invalid_user_id_text() -> str:
    return "Некорректный user_id"


def make_admin_ledger_applied_text() -> str:
    return "Коррекция применена."


def make_admin_ledger_apply_error_text() -> str:
    return "Ошибка применения"


def make_admin_ledger_declined_text() -> str:
    return "Коррекция отклонена."


def make_admin_deal_closed_text() -> str:
    return "Сбор закрыт. Средства ушли в работу."


def make_admin_deal_close_error_text() -> str:
    return "Ошибка закрытия"


def make_admin_deal_declined_text() -> str:
    return "Отклонено"
