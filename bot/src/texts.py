"""
Все текстовые сообщения бота, вынесенные в один модуль
для удобного редактирования и форматирования.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Any


# === /start, приветствие ===

WELCOME_ABOUT = """<b>Invext</b> — торговое сообщество, объединяющее финансовые рынки, технологии и цифровую культуру.

Мы создали понятную и прозрачную систему, где каждый участник может зарабатывать вместе с командой.

За 5+ лет работы на финансовых рынках мы:
— собрали сильную команду трейдеров  
— выстроили эффективную торговую систему  
— внедрили строгий риск-менеджмент  

Это позволяет нам стабильно адаптироваться к рынку и показывать устойчивые результаты.

💰 <b>Доход:</b> от <b>3% до 9%</b> чистой прибыли ежедневно  
🔁 Вы можете вывести средства вместе с инвестицией уже после одной сделки  

📈 <b>Как это работает:</b>  
Мы объединяем капитал участников → увеличиваем торговые объёмы → повышаем общую прибыль.

🤝 <b>Реферальная программа:</b>  
Пассивный доход за приглашённых пользователей:

— 3% с депозитов рефералов 1 уровня  
— 0.5% с инвестиций рефералов 1–3 уровней (если вы участвуете в сделке)

<b>Реферальные уровни:</b>  
1 уровень — 3% с депозитов + 0.5% с инвестиций  
2 уровень — 0.5% с инвестиций  
3 уровень — 0.5% с инвестиций  

⚠️ Для активации: баланс от <b>100 USD</b>

Реферальные начисления приходят автоматически и доступны к выводу сразу (при участии в сделке).

📌 <b>Условия:</b>  
• Обработка выплат — до 48 часов  
• Минимальный вывод — 5 USDT  
• Минимальная инвестиция — 100 USDT  
• Без скрытых комиссий  

<b>Invext</b> — это понятная система, команда и стабильный подход к заработку."""


def format_personal_data(
    me: Mapping[str, Any],
    balances: Mapping[str, Any],
    invested_usdt: str = "0.00",
    ref_link: str | None = None,
) -> str:
    """Формирует блок «Личные данные» для второго сообщения при /start."""
    usdt = float(balances.get("USDT", 0) or 0)
    usdt_s = f"{usdt:.2f}"

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
        f"USDT: {usdt}\n\n"
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
        
        f"💰 Сумма: <b>{amount} USD</b>\n"
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
        lines.append(f"• +{inv.get('amount', 0)} USDT — {st}{cred}{dt_str}")
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
    return "Выберите валюту вывода:"


def make_withdraw_enter_amount_text(currency: str, min_wd: Any, max_wd: Any) -> str:
    return (
        f"💸 <b>Вывод средств ({currency})</b>\n\n"
        "Введите сумму:\n\n"
        f"Минимум — {min_wd}\n"
        f"Максимум — {max_wd}"
    )


def make_withdraw_enter_address_text() -> str:
    return ("🏦 <b>Адрес для вывода</b>\n\n"
            "Введите адрес кошелька:")


def make_withdraw_success_text(req_id: Any) -> str:
    return (
        "✅ <b>Заявка на вывод создана</b>\n\n"
        "Заявка отправлена на проверку\n"
        "Средства будут переведены в течение 48 часов\n\n"
        f"🆔 ID заявки: {req_id}"
    )


# === Инвестиции (раздел «Сделка») ===

def make_invest_main_text_with_deal(deal_number: Any, available_usdt: str) -> str:
    return (
        f"🚀 <b>Сделка #{deal_number} открыта</b>\n\n"
        
        "💰 <b>Доступный баланс</b>\n"
        f"USDT: {available_usdt}\n\n"
        
        "📌 Нажмите «Участвовать», чтобы вложить средства\n"
        "Минимальная сумма будет показана при вводе"
    )


def make_invest_main_text_no_deal() -> str:
    return (
        "📭 <b>Сейчас нет активной сделки</b>\n\n"
        "Ожидайте уведомление о новой сделке.\n\n"
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
        
        f"💰 Сумма: {invested} USDT\n"
        f"📊 Баланс: {new_balance} USDT\n\n"
        f"{payout_line}"
        "Средства участвуют в текущей сделке.\n"
        "Прибыль будет начислена в течение 24 часов после закрытия сделки."
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


# === Партнёрка / команда / бонусы ===

def make_partners_main_text(me: Mapping[str, Any], link: str | None, levels: list[tuple[float, str]]) -> str:
    level1 = me.get("referrals_level_1", 0) or me.get("referrals_count", 0)
    level2 = me.get("referrals_level_2", 0)
    level3 = me.get("referrals_level_3", 0)
    counts = [level1, level2, level3]

    if link:
        link_block = f"🔗 Ваша реферальная ссылка:\n{link}"
    else:
        link_block = "⚠️ Реферальная ссылка временно недоступна. Попробуйте позже."

    lines: list[str] = [
        "<b>👥 Партнёрская программа</b>\n\n"
        f"{link_block}\n\n"
        "📊 <b>Уровни рефералов</b>"
    ]
    for i, (pct, label) in enumerate(levels):
        count = counts[i] if i < len(counts) else 0
        lines.append(f"  • {label}: {count} чел. — {pct:.1f}%")
    return "\n".join(lines)


def make_partners_no_link_text() -> str:
    return "⚠️ Реферальная ссылка временно недоступна. Попробуйте позже."


def make_partners_team_text(me: Mapping[str, Any]) -> str:
    level1 = me.get("referrals_level_1", 0) or me.get("referrals_count", 0)
    level2 = me.get("referrals_level_2", 0)
    level3 = me.get("referrals_level_3", 0)
    team_usdt = me.get("team_deposits_usdt", "0") or "0"
    try:
        team_float = float(team_usdt)
    except (TypeError, ValueError):
        team_float = 0.0
    lines = [
        "<b>📊 Моя команда</b>\n\n"
        
        f"1 уровень — {level1}\n"
        f"2 уровень — {level2}\n"
        f"3 уровень — {level3}\n\n"
        
        f"💎 Оборот команды: {team_float:.2f} USDT"
    ]
    return "\n".join(lines)


def make_partners_bonuses_text(me: Mapping[str, Any]) -> str:
    level1 = me.get("referrals_level_1", 0) or me.get("referrals_count", 0)
    level2 = me.get("referrals_level_2", 0)
    level3 = me.get("referrals_level_3", 0)
    team_usdt = me.get("team_deposits_usdt", "0") or "0"
    try:
        team_float = float(team_usdt)
    except (TypeError, ValueError):
        team_float = 0.0
    return (
        "🎁 <b>Реферальные бонусы</b>\n\n"
        
        f"1 уровень — {level1} чел. • 3% с депозитов + 0.5% с инвестиций\n"
        f"2 уровень — {level2} чел. • 0.5% с инвестиций\n"
        f"3 уровень — {level3} чел. • 0.5% с инвестиций\n\n"
        
        f"💎 Оборот команды: {team_float:.2f} USDT\n\n"
        
        "📌 Бонус с депозитов начисляется автоматически\n"
        "Бонус с инвестиций — только если вы участвуете в той же сделке"
    )


def make_team_turnover_main_text(me: Mapping[str, Any]) -> str:
    usdt = me.get("team_deposits_usdt", "0") or "0"
    try:
        total = float(usdt)
    except (TypeError, ValueError):
        total = 0.0
    return (
        "📊 <b>Оборот команды</b>\n\n"
        
        f"💎 Общий оборот: {total:.2f} USDT"
    )


def make_team_turnover_detail_text(me: Mapping[str, Any]) -> str:
    usdt = me.get("team_deposits_usdt", "0") or "0"
    ref_count = me.get("referrals_count", 0)
    try:
        usdt_f = float(usdt)
    except (TypeError, ValueError):
        usdt_f = 0.0
    return (
        "📈 <b>Статистика команды</b>\n\n"
        
        "💎 Оборот по уровням:\n\n"
        
        f"1 уровень — {ref_count} • {usdt_f:.2f} USDT\n"
        "2 уровень — 0 • 0.00 USDT\n"
        "3 уровень — 0 • 0.00 USDT\n"
    )


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
        f"{balance_usdt} USDT\n\n"
        
        "💳 <b>Депозиты</b>\n"
        f"{d_usdt} USDT\n\n"
        
        "💸 <b>Выводы</b>\n"
        f"{w_usdt} USDT\n\n"
        
        "📈 <b>Инвестиции и прибыль</b>\n"
        f"Инвестировано: {invested_total} USDT\n"
        f"Прибыль: {profit_total} USDT\n"
        f"Реферальный доход: {referral_income} USDT\n\n"
        
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

    invested_raw = me.get("invested_total_usdt", "0")
    try:
        invested = f"{float(invested_raw):.2f}"
    except (TypeError, ValueError):
        invested = "0.00"

    if ref_link:
        ref_part = f"🔗 <b>Реферальная ссылка</b>\n{ref_link}"
    else:
        ref_part = "⚠️ Реферальная ссылка временно недоступна. Попробуйте позже."

    return (
        "👤 <b>Профиль</b>\n\n"
        
        "💰 <b>Баланс</b>\n"
        f"{usdt} USDT\n\n"
        
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
    if not wallets_list:
        return (text_prefix + "💼 <b>Ваши кошельки</b>\n\nУ вас нет сохранённых кошельков.").strip()

    lines = []
    for w in wallets_list:
        addr = str(w.get("address", ""))
        addr_show = f"{addr[:24]}..." if len(addr) > 24 else addr
        lines.append(f"• {w.get('name', 'Без названия')} ({w.get('currency', 'USDT')}): <code>{addr_show}</code>")
    return (text_prefix + "💼 <b>Ваши кошельки</b>\n\n" + "\n".join(lines)).strip()


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
        line = (
            f"ID: {r.get('id')} | {r.get('currency')} {r.get('amount')} → "
            f"{addr[:20]}{'...' if len(addr) > 20 else ''} | "
            f"user_id={r.get('user_telegram_id')}"
        )
        lines.append(line)
    return "📤 <b>Заявки на вывод (PENDING)</b>\n\n" + "\n\n".join(lines)


def make_admin_withdraw_card_text(item: Mapping[str, Any]) -> str:
    addr = str(item.get("address", ""))
    return (
        f"Вывод #{item.get('id')}: {item.get('currency')} {item.get('amount')} | "
        f"Адрес: {addr[:30]}{'...' if len(addr) > 30 else ''} | "
        f"TG: {item.get('user_telegram_id')}"
    )


def make_admin_fin_settings_text(data: Mapping[str, Any]) -> str:
    return (
        "⚙️ <b>Финансовые настройки</b>\n\n"
        f"Минимальный депозит: {data.get('min_deposit_usdt')} USDT\n"
        f"Максимальный депозит: {data.get('max_deposit_usdt')} USDT\n\n"
        f"Минимальный вывод: {data.get('min_withdraw_usdt')} USDT\n"
        f"Максимальный вывод: {data.get('max_withdraw_usdt')} USDT\n\n"
        f"Минимальная инвестиция: {data.get('min_invest_usdt')} USDT\n"
        f"Максимальная инвестиция: {data.get('max_invest_usdt')} USDT"
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
    return "Сделка закрыта."


def make_admin_deal_close_error_text() -> str:
    return "Ошибка закрытия"


def make_admin_deal_declined_text() -> str:
    return "Отклонено"
