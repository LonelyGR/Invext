"""
Раздел «Сделка»: отображение открытой сделки, кнопка «Участвовать», ввод суммы.
Инвестиции — списание баланса USDT через /api/invest.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from aiogram import Router, F
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from src.api_client.client import api
from src.keyboards.menus import back_kb
from src.services.fresh_data import get_invest_dashboard
from src.utils.effects import send_effect_message, EFFECT_CELEBRATION
from src.utils.locks import with_double_click_protection, release_double_click_lock
from src.texts import (
    make_invest_main_text_with_deal,
    make_invest_main_text_no_deal,
    make_invest_deals_split_text,
    make_invest_enter_amount_text,
    make_invest_success_text,
    make_invest_deals_dashboard_text,
)
import logging

router = Router(name="invest")
logger = logging.getLogger(__name__)


class InvestStates(StatesGroup):
    entering_amount = State()


def _invest_deal_kb(with_participate: bool, fixed_amount: Decimal | None = None) -> InlineKeyboardMarkup:
    """Клавиатура раздела Сделка: при открытой сделке — Участвовать + Назад, иначе только Назад."""
    rows = []
    if with_participate:
        btn_text = "✅ Участвовать"
        if fixed_amount is not None:
            btn_text = f"✅ Участвовать ({fixed_amount} USD)"
        rows.append([InlineKeyboardButton(text=btn_text, callback_data="invest_participate")])
    rows.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_payout_at(payout_at_iso: str | None) -> str:
    if not payout_at_iso:
        return "не назначена"
    try:
        dt_obj = datetime.fromisoformat(payout_at_iso.replace("Z", "+00:00"))
        return f"{dt_obj.strftime('%d.%m')} после 15:00"
    except Exception:
        return payout_at_iso


def _make_deal_lines(items: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in items[:3]:
        deal_number = item.get("deal_number")
        amount_raw = item.get("amount_usdt")
        try:
            amount = f"{float(amount_raw):.2f}"
        except (TypeError, ValueError):
            amount = str(amount_raw or "0")

        status_raw = str(item.get("status") or "")
        status_map = {
            "active": "🟢 Участвуете",
            "in_progress_payout": "⏳ Ожидается выплата",
            "completed": "✅ Выплачено",
        }
        status = status_map.get(status_raw, "ℹ️ Обработка")
        payout_at = _format_payout_at(item.get("payout_at"))
        lines.append(
            f"• #{deal_number}: {amount} USDT • {status} • Выплата: {payout_at}"
        )
    return lines


def _format_date_short(iso_str: str | None) -> str:
    if not iso_str:
        return ""
    try:
        dt_obj = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        return dt_obj.strftime("%d.%m")
    except Exception:
        return str(iso_str)[:10]


def _build_in_work_lines(active_items: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in active_items[:1]:
        deal_number = item.get("deal_number")
        amount_raw = item.get("amount_usdt")
        try:
            amount = f"{float(amount_raw):.2f}"
        except (TypeError, ValueError):
            amount = str(amount_raw or "0.00")
        payout_at = _format_payout_at(item.get("payout_at"))
        lines.append(f"• Сделка #{deal_number} — <b>{amount} USDT</b>\n⏳ Выплата: {payout_at}")
    return lines


def _build_history_lines(completed_items: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in completed_items[:3]:
        deal_number = item.get("deal_number")
        amount_raw = item.get("amount_usdt")
        try:
            amount = f"{float(amount_raw):.2f}"
        except (TypeError, ValueError):
            amount = str(amount_raw or "0.00")
        d = _format_date_short(item.get("payout_at"))
        date_part = f" {d}" if d else ""
        lines.append(f"#{deal_number} — <b>{amount} USDT</b> ✔️{date_part}")
    return lines


def _extract_invest_mode(settings: dict) -> tuple[str, Decimal, Decimal]:
    """
    Возвращает:
    - mode: "fixed" | "range"
    - min_value
    - max_value
    """
    min_raw = settings.get("min_invest_usdt", "0")
    max_raw = settings.get("max_invest_usdt", "0")
    min_value = Decimal(str(min_raw).replace(",", "."))
    max_value = Decimal(str(max_raw).replace(",", "."))
    mode = "fixed" if min_value == max_value else "range"
    return mode, min_value, max_value


@router.message(F.text == "📈 Сделка")
async def invest_section(message: Message, state: FSMContext):
    telegram_id = message.from_user.id
    try:
        dash = await get_invest_dashboard(telegram_id)
        balances = dash["balances"]
        active = dash["active"]
        my_deals = dash["my_deals"]
        settings = dash["settings"]
    except Exception as e:
        await message.answer(f"Ошибка: {e}")
        return

    usdt = float(balances.get("USDT", 0) or 0)

    if active.get("active") and active.get("deal_number"):
        deal_number = active["deal_number"]
        mode, min_invest, max_invest = _extract_invest_mode(settings)
        if mode == "fixed":
            participate_amount = min_invest
        else:
            participate_amount = None
        in_work_lines = _build_in_work_lines(my_deals.get("active_deals", []))
        history_lines = _build_history_lines(my_deals.get("completed_deals", []))
        text = make_invest_deals_dashboard_text(
            active_deal_number=deal_number,
            balance_usdt=usdt,
            participate_amount_usdt=participate_amount,
            in_work_lines=in_work_lines,
            history_lines=history_lines,
        )
        await message.answer(text, reply_markup=_invest_deal_kb(with_participate=True, fixed_amount=participate_amount))
    else:
        in_work_lines = _build_in_work_lines(my_deals.get("active_deals", []))
        history_lines = _build_history_lines(my_deals.get("completed_deals", []))
        text = make_invest_deals_dashboard_text(
            active_deal_number=None,
            balance_usdt=usdt,
            participate_amount_usdt=None,
            in_work_lines=in_work_lines,
            history_lines=history_lines,
        )
        await state.clear()
        await message.answer(text, reply_markup=_invest_deal_kb(with_participate=False))


@router.callback_query(F.data == "invest_participate")
async def invest_participate(callback: CallbackQuery, state: FSMContext):
    """Пользователь нажал «Участвовать» — просим ввести сумму с подсказкой минимума."""
    telegram_id = callback.from_user.id
    try:
        active = await api.get_active_deal()
        settings = await api.get_system_settings()
        if not active.get("active"):
            await state.clear()
            await callback.message.edit_text(
                "⏳ Сбор на сделку уже закрыт.\n\nОжидайте следующего открытия.",
                reply_markup=_invest_deal_kb(with_participate=False),
            )
            await callback.answer()
            return
        if settings.get("allow_investments") is False:
            await state.clear()
            await callback.message.edit_text(
                "⚠️ Участие в сделках временно недоступно по техническим причинам.\n\nПопробуйте позже.",
                reply_markup=_invest_deal_kb(with_participate=False),
            )
            await callback.answer()
            return

        mode, min_invest, max_invest = _extract_invest_mode(settings)
    except Exception:
        mode, min_invest, max_invest = "range", None, None

    if mode == "fixed" and min_invest is not None:
        if not await with_double_click_protection(callback, "invest"):
            return
        try:
            try:
                result = await api.invest(telegram_id, min_invest)
            except Exception as e:
                err = str(e)
                if hasattr(e, "response") and getattr(e, "response", None) is not None:
                    try:
                        body = e.response.json()
                        if isinstance(body, dict) and "detail" in body:
                            err = body["detail"] if isinstance(body["detail"], str) else str(body["detail"])
                    except Exception:
                        pass
                await callback.message.edit_text(
                    f"Ошибка инвестирования: {err}",
                    reply_markup=_invest_deal_kb(with_participate=False),
                )
                await state.clear()
                await callback.answer()
                return

            new_balance = result.get("balance_usdt")
            invested = result.get("invested_amount_usdt")
            payout_hint = _format_payout_at(result.get("payout_at"))
            success_text = make_invest_success_text(invested, new_balance, payout_hint=payout_hint)
            await send_effect_message(
                callback.message.bot,
                callback.message.chat.id,
                success_text,
                effect_id=EFFECT_CELEBRATION,
                reply_markup=_invest_deal_kb(with_participate=False),
            )
            await state.clear()
            await callback.answer()
            return
        finally:
            await release_double_click_lock(telegram_id, "invest")

    await state.set_state(InvestStates.entering_amount)

    hint = f"Минимальная сумма: {min_invest} USDT" if min_invest is not None else "Введите сумму инвестиций."
    await callback.message.edit_text(
        make_invest_enter_amount_text(hint),
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")]]
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "open_invest")
async def open_invest_from_reminder(callback: CallbackQuery, state: FSMContext):
    """
    Обработчик кнопки «📈 Участвовать» из напоминаний бэкенда.
    callback.message.from_user — это бот, а не пользователь,
    поэтому отправляем новое сообщение напрямую пользователю.
    """
    telegram_id = callback.from_user.id
    try:
        dash = await get_invest_dashboard(telegram_id)
        balances = dash["balances"]
        active = dash["active"]
        my_deals = dash["my_deals"]
        settings = dash["settings"]
    except Exception as e:
        await callback.answer(f"Ошибка: {e}", show_alert=True)
        return

    usdt = float(balances.get("USDT", 0) or 0)

    if active.get("active") and active.get("deal_number"):
        deal_number = active["deal_number"]
        mode, min_invest, max_invest = _extract_invest_mode(settings)
        if mode == "fixed":
            participate_amount = min_invest
        else:
            participate_amount = None
        in_work_lines = _build_in_work_lines(my_deals.get("active_deals", []))
        history_lines = _build_history_lines(my_deals.get("completed_deals", []))
        text = make_invest_deals_dashboard_text(
            active_deal_number=deal_number,
            balance_usdt=usdt,
            participate_amount_usdt=participate_amount,
            in_work_lines=in_work_lines,
            history_lines=history_lines,
        )
        await callback.message.answer(
            text,
            reply_markup=_invest_deal_kb(with_participate=True, fixed_amount=participate_amount),
        )
    else:
        in_work_lines = _build_in_work_lines(my_deals.get("active_deals", []))
        history_lines = _build_history_lines(my_deals.get("completed_deals", []))
        text = make_invest_deals_dashboard_text(
            active_deal_number=None,
            balance_usdt=usdt,
            participate_amount_usdt=None,
            in_work_lines=in_work_lines,
            history_lines=history_lines,
        )
        await callback.message.answer(text, reply_markup=_invest_deal_kb(with_participate=False))
    await callback.answer()


@router.message(InvestStates.entering_amount)
async def invest_amount_entered(message: Message, state: FSMContext):
    telegram_id = message.from_user.id
    if not await with_double_click_protection(message, "invest"):
        return
    try:
        raw = (message.text or "").replace(",", ".").strip()

        try:
            amount = Decimal(raw)
        except (InvalidOperation, AttributeError):
            await message.answer("Введите сумму в формате числа, например: 50 или 75.5")
            return

        if amount <= 0:
            await message.answer("Сумма должна быть больше нуля.")
            return

        try:
            result = await api.invest(telegram_id, amount)
        except Exception as e:
            err = str(e)
            if hasattr(e, "response") and getattr(e, "response", None) is not None:
                try:
                    body = e.response.json()
                    if isinstance(body, dict) and "detail" in body:
                        err = body["detail"] if isinstance(body["detail"], str) else str(body["detail"])
                except Exception:
                    pass

            logger.error("invest failed for user %s: %s", telegram_id, err)
            await message.answer(f"Ошибка инвестирования: {err}")
            await state.clear()
            return

        new_balance = result.get("balance_usdt")
        invested = result.get("invested_amount_usdt")
        payout_hint = _format_payout_at(result.get("payout_at"))

        success_text = make_invest_success_text(invested, new_balance, payout_hint=payout_hint)
        await send_effect_message(
            message.bot,
            message.chat.id,
            success_text,
            effect_id=EFFECT_CELEBRATION,
            reply_markup=_invest_deal_kb(with_participate=False),
        )
        await state.clear()
        logger.info("user %s invested %s USDT into current deal", telegram_id, invested)
    finally:
        await release_double_click_lock(telegram_id, "invest")
