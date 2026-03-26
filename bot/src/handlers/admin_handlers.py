"""
Админка: /admin — только для ADMIN_TELEGRAM_IDS. Список pending заявок, Approve/Reject.
"""
from decimal import Decimal

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from src.config.settings import ADMIN_TELEGRAM_IDS
from src.api_client.client import api
from src.keyboards.menus import (
    admin_menu_kb,
    withdraw_actions_kb,
    fin_settings_kb,
    admin_deals_kb,
    admin_maintenance_kb,
)
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from src.texts import (
    make_admin_access_denied_text,
    make_admin_panel_text,
    make_admin_token_text,
    make_admin_error_text,
    make_admin_no_pending_withdrawals_text,
    make_admin_pending_withdrawals_text,
    make_admin_withdraw_card_text,
    make_admin_fin_settings_text,
    make_admin_unknown_setting_text,
    make_admin_enter_new_value_text,
    make_admin_invalid_number_text,
    make_admin_value_gt_zero_text,
    make_admin_setting_updated_text,
    make_admin_withdraw_approved_text,
    make_admin_withdraw_rejected_text,
    make_admin_invalid_request_data_text,
    make_admin_invalid_user_id_text,
    make_admin_ledger_applied_text,
    make_admin_ledger_apply_error_text,
    make_admin_ledger_declined_text,
    make_admin_deal_closed_text,
    make_admin_deal_close_error_text,
    make_admin_deal_declined_text,
)

router = Router(name="admin")


def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_TELEGRAM_IDS


class FinSettingsStates(StatesGroup):
    waiting_value = State()
    field = State()


def confirm_kb(confirm_cb: str, cancel_cb: str = "admin_back_panel") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Подтвердить", callback_data=confirm_cb),
                InlineKeyboardButton(text="❌ Отмена", callback_data=cancel_cb),
            ]
        ]
    )


@router.message(F.text == "🔧 Админка")
async def admin_button(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer(make_admin_access_denied_text())
        return
    await message.answer(make_admin_panel_text(), reply_markup=admin_menu_kb())


# Команда /admin
@router.message(F.text == "/admin")
async def admin_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer(make_admin_access_denied_text())
        return
    await message.answer(make_admin_panel_text(), reply_markup=admin_menu_kb())


@router.callback_query(F.data == "admin_back_panel")
async def admin_back_panel(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    await callback.message.edit_text(make_admin_panel_text(), reply_markup=admin_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "admin_status")
async def admin_status(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    try:
        data = await api.admin_status_summary()
        active = data.get("active_deal")
        active_line = (
            f"#{active.get('number')} · {active.get('status')} · до {active.get('end_at')}"
            if active
            else "нет"
        )
        text = (
            "📊 <b>Статус системы</b>\n\n"
            f"Пользователи: <b>{data.get('users_count', 0)}</b>\n"
            f"Pending выводов: <b>{data.get('pending_withdrawals', 0)}</b>\n"
            f"Платежей: <b>{data.get('deposits_count', 0)}</b>\n"
            f"Активная сделка: <b>{active_line}</b>"
        )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_menu_kb())
    except Exception as e:
        await callback.message.edit_text(make_admin_error_text(e), reply_markup=admin_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "admin_deals")
async def admin_deals(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    await callback.message.edit_text("📈 <b>Управление сделками</b>", parse_mode="HTML", reply_markup=admin_deals_kb())
    await callback.answer()


@router.callback_query(F.data == "admin_deal_active")
async def admin_deal_active(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    try:
        data = await api.admin_status_summary()
        active = data.get("active_deal")
        if not active:
            text = "📍 Активной сделки нет."
        else:
            text = (
                "📍 <b>Активная сделка</b>\n\n"
                f"ID: {active.get('id')}\n"
                f"Номер: #{active.get('number')}\n"
                f"Статус: {active.get('status')}\n"
                f"Старт: {active.get('start_at')}\n"
                f"Конец: {active.get('end_at')}"
            )
        await callback.message.edit_text(text, parse_mode="HTML", reply_markup=admin_deals_kb())
    except Exception as e:
        await callback.message.edit_text(make_admin_error_text(e), reply_markup=admin_deals_kb())
    await callback.answer()


@router.callback_query(F.data == "admin_deal_open_now")
async def admin_deal_open_now(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    await callback.message.edit_text(
        "🟢 Открыть новую сделку прямо сейчас?\n\nЭто отправит уведомление пользователям.",
        reply_markup=confirm_kb("admin_deal_open_now_confirm", "admin_deals"),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_deal_open_now_confirm")
async def admin_deal_open_now_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    try:
        res = await api.admin_open_deal_now(decided_by_telegram_id=callback.from_user.id)
        await callback.message.edit_text(
            f"✅ Сделка открыта: #{res.get('deal_number')}",
            reply_markup=admin_deals_kb(),
        )
    except Exception as e:
        await callback.message.edit_text(make_admin_error_text(e), reply_markup=admin_deals_kb())
    await callback.answer()


@router.callback_query(F.data == "admin_deal_force_close_now")
async def admin_deal_force_close_now(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    await callback.message.edit_text(
        "⛔ Досрочно закрыть активную сделку?\n\nДействие необратимо.",
        reply_markup=confirm_kb("admin_deal_force_close_now_confirm", "admin_deals"),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_deal_force_close_now_confirm")
async def admin_deal_force_close_now_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    try:
        res = await api.admin_deal_force_close(decided_by_telegram_id=callback.from_user.id)
        await callback.message.edit_text(
            f"✅ Сделка #{res.get('deal_number')} закрыта досрочно.",
            reply_markup=admin_deals_kb(),
        )
    except Exception as e:
        await callback.message.edit_text(make_admin_error_text(e), reply_markup=admin_deals_kb())
    await callback.answer()


@router.callback_query(F.data == "admin_maintenance")
async def admin_maintenance(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    await callback.message.edit_text(
        "🧹 <b>Быстрая очистка</b>\n\nТолько частичные сценарии, без полного reset.",
        parse_mode="HTML",
        reply_markup=admin_maintenance_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.in_({"admin_clear_logs", "admin_clear_broadcasts", "admin_clear_deals", "admin_clear_payments"}))
async def admin_maintenance_confirm(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    labels = {
        "admin_clear_logs": "Очистить только логи",
        "admin_clear_broadcasts": "Очистить только рассылки",
        "admin_clear_deals": "Очистить только сделки",
        "admin_clear_payments": "Очистить только платежи",
    }
    action = callback.data
    await callback.message.edit_text(
        f"⚠️ {labels.get(action)}?\n\nПодтвердите действие.",
        reply_markup=confirm_kb(f"{action}_confirm", "admin_maintenance"),
    )
    await callback.answer()


@router.callback_query(F.data.in_({"admin_clear_logs_confirm", "admin_clear_broadcasts_confirm", "admin_clear_deals_confirm", "admin_clear_payments_confirm"}))
async def admin_maintenance_execute(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    action = callback.data
    try:
        if action == "admin_clear_logs_confirm":
            res = await api.admin_maintenance_clear_logs()
            txt = f"✅ Логи очищены. Удалено строк: {res.get('cleared_rows', 0)}"
        elif action == "admin_clear_broadcasts_confirm":
            res = await api.admin_maintenance_clear_broadcasts()
            txt = f"✅ Рассылки очищены. Удалено строк: {res.get('cleared_rows', 0)}"
        elif action == "admin_clear_deals_confirm":
            res = await api.admin_maintenance_clear_deals()
            txt = f"✅ Сделки очищены. Удалено строк: {res.get('cleared_rows', 0)}"
        else:
            res = await api.admin_maintenance_clear_payments()
            txt = f"✅ Платежи очищены. Удалено строк: {res.get('cleared_rows', 0)}"
        await callback.message.edit_text(txt, reply_markup=admin_maintenance_kb())
    except Exception as e:
        await callback.message.edit_text(make_admin_error_text(e), reply_markup=admin_maintenance_kb())
    await callback.answer()


@router.callback_query(F.data == "admin_dashboard_token")
async def admin_get_dashboard_token(callback: CallbackQuery):
    """Выдать одноразовый токен для входа в админ-сайт /database."""
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    try:
        data = await api.create_dashboard_token(callback.from_user.id)
        token = data["token"]
        url = data.get("dashboard_url", "")
        text = make_admin_token_text(token, url)
        await callback.message.edit_text(text, parse_mode="HTML")
    except Exception as e:
        await callback.message.edit_text(make_admin_error_text(e))
    await callback.answer()


@router.callback_query(F.data == "admin_withdrawals")
async def admin_list_withdrawals(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    try:
        items = await api.admin_pending_withdrawals()
    except Exception as e:
        await callback.message.edit_text(make_admin_error_text(e))
        await callback.answer()
        return

    if not items:
        await callback.message.edit_text(make_admin_no_pending_withdrawals_text())
        await callback.answer()
        return

    text = make_admin_pending_withdrawals_text(items)
    await callback.message.edit_text(text, parse_mode="HTML")
    for r in items:
        msg_text = make_admin_withdraw_card_text(r)
        await callback.message.answer(
            msg_text,
            reply_markup=withdraw_actions_kb(r["id"]),
        )
    await callback.answer()


@router.callback_query(F.data == "admin_fin_settings")
async def admin_fin_settings(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    try:
        data = await api.get_system_settings()
    except Exception as e:
        await callback.message.edit_text(make_admin_error_text(e))
        await callback.answer()
        return

    text = make_admin_fin_settings_text(data)
    await callback.message.edit_text(text, reply_markup=fin_settings_kb(), parse_mode="HTML")
    await callback.answer()


@router.callback_query(F.data.startswith("fin_set_"))
async def fin_setting_choose(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
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
        await callback.answer(make_admin_unknown_setting_text())
        return
    await state.set_state(FinSettingsStates.waiting_value)
    await state.update_data(field=field)
    await callback.message.edit_text(make_admin_enter_new_value_text())
    await callback.answer()


@router.message(FinSettingsStates.waiting_value, F.text)
async def fin_setting_value(message: Message, state: FSMContext):
    telegram_id = message.from_user.id
    if not is_admin(telegram_id):
        await message.answer(make_admin_access_denied_text())
        await state.clear()
        return
    data = await state.get_data()
    field = data.get("field")
    raw = (message.text or "").replace(",", ".").strip()
    try:
        value = Decimal(raw)
    except Exception:
        await message.answer(make_admin_invalid_number_text())
        return
    if value <= 0:
        await message.answer(make_admin_value_gt_zero_text())
        return

    try:
        await api.update_system_settings_field(field, str(value))
    except Exception as e:
        await message.answer(f"Ошибка обновления настройки: {e}")
        return

    await message.answer(make_admin_setting_updated_text())
    await state.clear()


@router.callback_query(F.data.startswith("admin_w_approve_"))
async def admin_withdraw_approve(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    withdraw_id = int(callback.data.replace("admin_w_approve_", ""))
    try:
        await api.admin_approve_withdraw(withdraw_id, callback.from_user.id)
        await callback.message.edit_text(make_admin_withdraw_approved_text(withdraw_id))
    except Exception as e:
        await callback.message.edit_text(make_admin_error_text(e))
    await callback.answer()


@router.callback_query(F.data.startswith("admin_w_reject_"))
async def admin_withdraw_reject(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return
    withdraw_id = int(callback.data.replace("admin_w_reject_", ""))
    try:
        await api.admin_reject_withdraw(withdraw_id, callback.from_user.id)
        await callback.message.edit_text(make_admin_withdraw_rejected_text(withdraw_id))
    except Exception as e:
        await callback.message.edit_text(make_admin_error_text(e))
    await callback.answer()


@router.callback_query(F.data.startswith("ledger_adj:"))
async def admin_ledger_adjust_callback(callback: CallbackQuery):
    """Подтверждение/отклонение ручной корректировки баланса из бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return

    parts = (callback.data or "").split(":")
    if len(parts) < 5:
        await callback.answer(make_admin_invalid_request_data_text())
        return

    _, action, user_id_str, amount_str, request_tag = parts[:5]
    try:
        user_id = int(user_id_str)
    except ValueError:
        await callback.answer(make_admin_invalid_user_id_text())
        return

    if action == "approve":
        try:
            result = await api.admin_ledger_adjust(
                user_id=user_id,
                amount_usdt=amount_str,
                comment=None,
                request_tag=request_tag,
                decided_by_telegram_id=callback.from_user.id,
            )
            if result.get("already_processed"):
                by_admin = result.get("decided_by_telegram_id")
                by_line = f" админом {by_admin}" if by_admin else ""
                await callback.message.edit_text(callback.message.text + f"\n\nℹ️ Уже обработано{by_line}.")
                await callback.answer("Уже обработано")
            else:
                await callback.message.edit_text(callback.message.text + "\n\n✅ Коррекция применена.")
                await callback.answer(make_admin_ledger_applied_text())
        except Exception as e:
            await callback.message.edit_text(f"{callback.message.text}\n\n❌ Ошибка применения: {e}")
            await callback.answer(make_admin_ledger_apply_error_text())
    else:
        await callback.message.edit_text(callback.message.text + "\n\n❌ Коррекция отклонена.")
        await callback.answer(make_admin_ledger_declined_text())


@router.callback_query(F.data.startswith("deal_fc:"))
async def admin_deal_force_close_callback(callback: CallbackQuery):
    """Подтверждение/отклонение досрочного закрытия сделки из бота."""
    if not is_admin(callback.from_user.id):
        await callback.answer(make_admin_access_denied_text())
        return

    parts = (callback.data or "").split(":")
    if len(parts) < 2:
        await callback.answer(make_admin_invalid_request_data_text())
        return

    _, action = parts[:2]

    if action == "approve":
        try:
            await api.admin_deal_force_close(decided_by_telegram_id=callback.from_user.id)
            await callback.message.edit_text(callback.message.text + "\n\n✅ Сбор досрочно закрыт. Средства ушли в работу.")
            await callback.answer(make_admin_deal_closed_text())
        except Exception as e:
            await callback.message.edit_text(f"{callback.message.text}\n\n❌ Ошибка закрытия: {e}")
            await callback.answer(make_admin_deal_close_error_text())
    else:
        await callback.message.edit_text(callback.message.text + "\n\n❌ Досрочное закрытие отклонено.")
        await callback.answer(make_admin_deal_declined_text())
