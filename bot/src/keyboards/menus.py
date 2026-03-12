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
        [KeyboardButton(text="👥 Рефералы"), KeyboardButton(text="⚙️ Кошелек")],
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
    """Выбор валюты USDT / USDC. callback_prefix: 'deposit_' или 'withdraw_'."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="USDT", callback_data=f"{callback_prefix}USDT"),
                InlineKeyboardButton(text="USDC", callback_data=f"{callback_prefix}USDC"),
            ],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ]
    )


def admin_menu_kb() -> InlineKeyboardMarkup:
    """Админка: заявки на вывод; токен для админ-сайта; финансовые настройки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Заявки на вывод", callback_data="admin_withdrawals")],
            [InlineKeyboardButton(text="🔐 Токен для админ-сайта", callback_data="admin_dashboard_token")],
            [InlineKeyboardButton(text="⚙️ Финансовые настройки", callback_data="admin_fin_settings")],
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
            [InlineKeyboardButton(text="Изменить сумму сделки", callback_data="fin_set_deal_amount")],
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
                InlineKeyboardButton(text="USDC", callback_data="wallet_coin_USDC"),
            ],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="wallets_cancel")],
        ]
    )


def turnover_main_kb() -> InlineKeyboardMarkup:
    """Оборот команды: Обновить данные, Подробная статистика, Назад."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔄 Обновить данные", callback_data="turnover_update")],
            [InlineKeyboardButton(text="📊 Подробная статистика", callback_data="turnover_detail")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ]
    )


def turnover_detail_kb() -> InlineKeyboardMarkup:
    """Экран «Подробная статистика»: Общий оборот, Назад."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Общий оборот", callback_data="turnover_total")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ]
    )


def partners_main_kb() -> InlineKeyboardMarkup:
    """Партнёры: Моя команда, Реферальные бонусы, Поделиться ссылкой, Назад."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Моя команда", callback_data="partners_team")],
            [InlineKeyboardButton(text="🎁 Реферальные бонусы", callback_data="partners_bonuses")],
            [InlineKeyboardButton(text="📤 Поделиться ссылкой", callback_data="partners_share_link")],
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")],
        ]
    )


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
