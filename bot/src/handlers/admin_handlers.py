"""
Админка: /admin — только для ADMIN_TELEGRAM_IDS. Список pending заявок, Approve/Reject.
"""
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery

from src.config.settings import ADMIN_TELEGRAM_IDS
from src.api_client.client import api
from src.keyboards.menus import admin_menu_kb, withdraw_actions_kb

router = Router(name="admin")


def is_admin(telegram_id: int) -> bool:
    return telegram_id in ADMIN_TELEGRAM_IDS


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
