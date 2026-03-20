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
from src.keyboards.menus import admin_menu_kb, withdraw_actions_kb, fin_settings_kb
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
    if len(parts) < 4:
        await callback.answer(make_admin_invalid_request_data_text())
        return

    _, action, user_id_str, amount_str = parts[:4]
    try:
        user_id = int(user_id_str)
    except ValueError:
        await callback.answer(make_admin_invalid_user_id_text())
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
