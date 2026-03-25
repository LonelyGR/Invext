"""
Инлайн-клавиатуры и кнопки меню бота.
"""
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton

from src.config.settings import ALLOWED_CURRENCIES


def main_menu_kb(is_admin: bool = False) -> ReplyKeyboardMarkup:
    """Главное меню: финансы, сделка, партнёрка, настройки, статистика, админка (только для админов)."""
    keyboard: list[list[KeyboardButton]] = [
        # ФИНАНСЫ
        [KeyboardButton(text="💰 Баланс"), KeyboardButton(text="📈 Сделка")],
        [KeyboardButton(text="📥 Пополнить"), KeyboardButton(text="📤 Вывести")],
        # ПАРТНЁРКА / НАСТРОЙКИ
        [KeyboardButton(text="👥 Партнёры"), KeyboardButton(text="⚙️ Кошелёк")],
        # СТАТИСТИКА
        [KeyboardButton(text="📊 Статистика")],
    ]
    if is_admin:
        # АДМИН (только для админов)
        keyboard.append([KeyboardButton(text="🔧 Админка")])

    return ReplyKeyboardMarkup(
        keyboard=keyboard,
        resize_keyboard=True,
    )


def profile_kb() -> InlineKeyboardMarkup:
    """Профиль: редактировать данные, кошельки, назад (инлайн — для ответов после редактирования)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Редактировать имя", callback_data="profile_edit_name")],
            [InlineKeyboardButton(text="✏️ Редактировать email", callback_data="profile_edit_email")],
            [InlineKeyboardButton(text="✏️ Редактировать страну", callback_data="profile_edit_country")],
            [InlineKeyboardButton(text="💼 Кошельки", callback_data="profile_wallets")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ]
    )


def profile_reply_kb() -> ReplyKeyboardMarkup:
    """Нижняя клавиатура в разделе «Профиль»: кнопки редакции вместо навигации."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✏️ Редактировать имя")],
            [KeyboardButton(text="✏️ Редактировать email")],
            [KeyboardButton(text="✏️ Редактировать страну")],
            [KeyboardButton(text="💼 Кошельки")],
            [KeyboardButton(text="◀️ Назад")],
        ],
        resize_keyboard=True,
    )


def back_kb() -> InlineKeyboardMarkup:
    """Кнопка «Назад» в главное меню (инлайн — для возврата после выбора действия)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ]
    )


def currency_kb(callback_prefix: str) -> InlineKeyboardMarkup:
    """Выбор валюты USDT. callback_prefix: 'deposit_' или 'withdraw_'."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="USDT", callback_data=f"{callback_prefix}USDT"),
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ]
    )


def admin_menu_kb() -> InlineKeyboardMarkup:
    """Админка: заявки на вывод; токен для админ-сайта; финансовые настройки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Статус системы", callback_data="admin_status")],
            [InlineKeyboardButton(text="📈 Сделки", callback_data="admin_deals")],
            [InlineKeyboardButton(text="📤 Заявки на вывод", callback_data="admin_withdrawals")],
            [InlineKeyboardButton(text="🔐 Токен для админ-сайта", callback_data="admin_dashboard_token")],
            [InlineKeyboardButton(text="⚙️ Финансовые настройки", callback_data="admin_fin_settings")],
            [InlineKeyboardButton(text="🧹 Быстрая очистка", callback_data="admin_maintenance")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ]
    )


def fin_settings_kb() -> InlineKeyboardMarkup:
    """Клавиатура управления финансовыми настройками."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="Изменить мин. депозит", callback_data="fin_set_min_deposit")],
            [InlineKeyboardButton(text="Изменить макс. депозит", callback_data="fin_set_max_deposit")],
            [InlineKeyboardButton(text="Изменить мин. вывод", callback_data="fin_set_min_withdraw")],
            [InlineKeyboardButton(text="Изменить макс. вывод", callback_data="fin_set_max_withdraw")],
            [InlineKeyboardButton(text="Изменить мин. инвестицию", callback_data="fin_set_min_invest")],
            [InlineKeyboardButton(text="Изменить макс. инвестицию", callback_data="fin_set_max_invest")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ]
    )


def wallets_list_kb() -> InlineKeyboardMarkup:
    """Кошельки: добавить, назад."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="➕ Добавить кошелёк", callback_data="wallets_add")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ]
    )


def wallet_coin_kb() -> InlineKeyboardMarkup:
    """Выбор валюты при добавлении кошелька."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="USDT", callback_data="wallet_coin_USDT"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="wallets_cancel")],
        ]
    )

def partners_main_kb(share_url: str | None = None) -> InlineKeyboardMarkup:
    """Партнёры: Моя команда, Реферальные бонусы, Поделиться ссылкой (нативный share), Назад."""
    rows = [
        [InlineKeyboardButton(text="📊 Моя команда", callback_data="partners_team")],
        [InlineKeyboardButton(text="🎁 Реферальные бонусы", callback_data="partners_bonuses")],
    ]
    if share_url:
        from urllib.parse import quote
        telegram_share = f"https://t.me/share/url?url={quote(share_url, safe='')}"
        rows.append([InlineKeyboardButton(text="📤 Поделиться ссылкой", url=telegram_share)])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def partners_team_kb() -> InlineKeyboardMarkup:
    """Экран «Моя команда»: Бонусы по рефералам, Назад."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Бонусы по рефералам", callback_data="partners_bonuses")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="partners_back")],
        ]
    )


def partners_bonuses_kb() -> InlineKeyboardMarkup:
    """Экран «Реферальные бонусы»: Моя команда, Назад."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Моя команда", callback_data="partners_team")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="partners_back")],
        ]
    )


def withdraw_actions_kb(withdraw_id: int) -> InlineKeyboardMarkup:
    """Кнопки Approve / Reject для одной заявки на вывод."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Approve", callback_data=f"admin_w_approve_{withdraw_id}"),
                InlineKeyboardButton(text="❌ Reject", callback_data=f"admin_w_reject_{withdraw_id}"),
            ],
        ]
    )


def admin_deals_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📍 Активная сделка", callback_data="admin_deal_active")],
            [InlineKeyboardButton(text="🟢 Открыть новую сделку", callback_data="admin_deal_open_now")],
            [InlineKeyboardButton(text="⛔ Закрыть активную сделку", callback_data="admin_deal_force_close_now")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back_panel")],
        ]
    )


def admin_maintenance_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🧾 Очистить только логи", callback_data="admin_clear_logs")],
            [InlineKeyboardButton(text="📣 Очистить только рассылки", callback_data="admin_clear_broadcasts")],
            [InlineKeyboardButton(text="📈 Очистить только сделки", callback_data="admin_clear_deals")],
            [InlineKeyboardButton(text="💳 Очистить только платежи", callback_data="admin_clear_payments")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="admin_back_panel")],
        ]
    )
