"""
Админка: /admin — только для ADMIN_TELEGRAM_IDS. Список pending заявок, Approve/Reject.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.config.settings import ADMIN_TELEGRAM_IDS
from src.api_client.client import api
from src.keyboards.menus import admin_menu_kb, withdraw_actions_kb, fin_settings_kb

router = Router(name="admin")


def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_TELEGRAM_IDS


class FinSettingsStates(StatesGroup):
    waiting_value = State()
    field = State()


@router.message(F.text == "🔧 Админка")
async def admin_button(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Доступ запрещён.")
        return
    await message.answer("Админ-панель. Выберите раздел:", reply_markup=admin_menu_kb())


# Команда /admin
@router.message(F.text == "/admin")
async def admin_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("Доступ запрещён.")
        return
    await message.answer("Админ-панель. Выберите раздел:", reply_markup=admin_menu_kb())


@router.callback_query(F.data == "admin_dashboard_token")
async def admin_get_dashboard_token(callback: CallbackQuery):
    """Выдать одноразовый токен для входа в админ-сайт /database."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    try:
        data = await api.create_dashboard_token(callback.from_user.id)
        token = data["token"]
        url = data.get("dashboard_url", "")
        text = (
            "🔐 <b>Токен для входа в админ-сайт</b>\n\n"
            f"<code>{token}</code>\n\n"
            "Скопируйте токен, откройте админ-сайт и вставьте в форму входа. Токен действует 24 ч, одноразовый.\n\n"
        )
        if url and "your-domain" not in url:
            text += f"Админ-сайт: {url}"
        else:
            text += "Админ-сайт: задайте в .env бэкенда APP_URL (например http://localhost). Страница входа: APP_URL/database"
        await callback.message.edit_text(text, parse_mode="HTML")
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}")
    await callback.answer()


@router.callback_query(F.data == "admin_withdrawals")
async def admin_list_withdrawals(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    try:
        items = await api.admin_pending_withdrawals()
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}")
        await callback.answer()
        return

    if not items:
        await callback.message.edit_text("Нет заявок на вывод в статусе PENDING.")
        await callback.answer()
        return

    lines = []
    for r in items:
        addr = r["address"]
        line = (
            f"ID: {r['id']} | {r['currency']} {r['amount']} → {addr[:20]}{'...' if len(addr) > 20 else ''} | "
            f"user_id={r['user_telegram_id']}"
        )
        lines.append(line)
    text = "📤 <b>Заявки на вывод (PENDING)</b>\n\n" + "\n\n".join(lines)
    await callback.message.edit_text(text, parse_mode="HTML")
    for r in items:
        addr = r["address"]
        msg_text = (
            f"Вывод #{r['id']}: {r['currency']} {r['amount']} | "
            f"Адрес: {addr[:30]}{'...' if len(addr) > 30 else ''} | TG: {r['user_telegram_id']}"
        )
        await callback.message.answer(
            msg_text,
            reply_markup=withdraw_actions_kb(r["id"]),
        )
    await callback.answer()


@router.callback_query(F.data == "admin_fin_settings")
async def admin_fin_settings(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    try:
        data = await api.get_system_settings()
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}")
        await callback.answer()
        return

    text = (
        "⚙️ <b>Финансовые настройки</b>\n\n"
        f"Минимальный депозит: {data['min_deposit_usdt']} USDT\n"
        f"Максимальный депозит: {data['max_deposit_usdt']} USDT\n\n"
        f"Минимальный вывод: {data['min_withdraw_usdt']} USDT\n"
        f"Максимальный вывод: {data['max_withdraw_usdt']} USDT\n\n"
        f"Минимальная инвестиция: {data['min_invest_usdt']} USDT\n"
        f"Максимальная инвестиция: {data['max_invest_usdt']} USDT"
    )
    await callback.message.edit_text(text, reply_markup=fin_settings_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("fin_set_"))
async def fin_setting_choose(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    field_map = {
        "fin_set_min_deposit": "min_deposit_usdt",
        "fin_set_max_deposit": "max_deposit_usdt",
        "fin_set_min_withdraw": "min_withdraw_usdt",
        "fin_set_max_withdraw": "max_withdraw_usdt",
        "fin_set_min_invest": "min_invest_usdt",
        "fin_set_max_invest": "max_invest_usdt",
    }
    key = callback.data
    field = field_map.get(key)
    if not field:
        await callback.answer("Неизвестная настройка")
        return
    await state.set_state(FinSettingsStates.waiting_value)
    await state.update_data(field=field)
    await callback.message.edit_text("Введите новое значение (только число, > 0):")
    await callback.answer()


@router.message(FinSettingsStates.waiting_value, F.text)
async def fin_setting_value(message: Message, state: FSMContext):
    telegram_id = message.from_user.id
    if not is_admin(telegram_id):
        await message.answer("Доступ запрещён.")
        await state.clear()
        return
    data = await state.get_data()
    field = data.get("field")
    raw = (message.text or "").replace(",", ".").strip()
    try:
        value = Decimal(raw)  # type: ignore[name-defined]
    except Exception:
        await message.answer("Введите корректное число, например: 10 или 50.5")
        return
    if value <= 0:
        await message.answer("Значение должно быть больше 0.")
        return

    try:
        await api.update_system_settings_field(field, str(value))
    except Exception as e:
        await message.answer(f"Ошибка обновления настройки: {e}")
        return

    await message.answer("Настройка обновлена.")
    await state.clear()


@router.callback_query(F.data.startswith("admin_w_approve_"))
async def admin_withdraw_approve(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    withdraw_id = int(callback.data.replace("admin_w_approve_", ""))
    try:
        await api.admin_approve_withdraw(withdraw_id, callback.from_user.id)
        await callback.message.edit_text(f"✅ Заявка на вывод #{withdraw_id} одобрена.")
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}")
    await callback.answer()


@router.callback_query(F.data.startswith("admin_w_reject_"))
async def admin_withdraw_reject(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return
    withdraw_id = int(callback.data.replace("admin_w_reject_", ""))
    try:
        await api.admin_reject_withdraw(withdraw_id, callback.from_user.id)
        await callback.message.edit_text(f"❌ Заявка на вывод #{withdraw_id} отклонена.")
    except Exception as e:
        await callback.message.edit_text(f"Ошибка: {e}")
    await callback.answer()


@router.callback_query(F.data.startswith("ledger_adj:"))
async def admin_ledger_adjust_callback(callback: CallbackQuery):
    """Подтверждение/отклонение ручной корректировки баланса из бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return

    parts = (callback.data or "").split(":")
    if len(parts) < 4:
        await callback.answer("Некорректные данные запроса")
        return

    _, action, user_id_str, amount_str = parts[:4]
    try:
        user_id = int(user_id_str)
    except ValueError:
        await callback.answer("Некорректный user_id")
        return

    if action == "approve":
        try:
            await api.admin_ledger_adjust(
                user_id=user_id,
                amount_usdt=amount_str,
                comment=None,
                decided_by_telegram_id=callback.from_user.id,
            )
            await callback.message.edit_text(callback.message.text + "\n\n✅ Коррекция применена.")
            await callback.answer("Коррекция применена.")
        except Exception as e:
            await callback.message.edit_text(f"{callback.message.text}\n\n❌ Ошибка применения: {e}")
            await callback.answer("Ошибка применения")
    else:
        await callback.message.edit_text(callback.message.text + "\n\n❌ Коррекция отклонена.")
        await callback.answer("Коррекция отклонена.")


@router.callback_query(F.data.startswith("deal_fc:"))
async def admin_deal_force_close_callback(callback: CallbackQuery):
    """Подтверждение/отклонение досрочного закрытия сделки из бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ запрещён")
        return

    parts = (callback.data or "").split(":")
    if len(parts) < 2:
        await callback.answer("Некорректные данные запроса")
        return

    _, action = parts[:2]

    if action == "approve":
        try:
            await api.admin_deal_force_close(decided_by_telegram_id=callback.from_user.id)
            await callback.message.edit_text(callback.message.text + "\n\n✅ Сделка досрочно закрыта.")
            await callback.answer("Сделка закрыта.")
        except Exception as e:
            await callback.message.edit_text(f"{callback.message.text}\n\n❌ Ошибка закрытия: {e}")
            await callback.answer("Ошибка закрытия")
    else:
        await callback.message.edit_text(callback.message.text + "\n\n❌ Досрочное закрытие отклонено.")
        await callback.answer("Отклонено")
