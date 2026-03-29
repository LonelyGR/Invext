"""
Единый слой получения актуальных пользовательских данных для Telegram-бота.

Критичные значения (баланс, сделки, реферальные метрики) всегда читаются из backend
непосредственно перед формированием UI.
"""
from __future__ import annotations

from typing import Any

from src.api_client.client import api


async def get_user_data(telegram_id: int) -> tuple[dict[str, Any], dict[str, Any]]:
    me = await api.get_me(telegram_id)
    balances = await api.get_balances(telegram_id)
    return me or {}, balances or {"USDT": 0}


async def get_invest_dashboard(telegram_id: int) -> dict[str, Any]:
    balances = await api.get_balances(telegram_id)
    active = await api.get_active_deal()
    my_deals = await api.get_my_deals(telegram_id)
    pending_payout = await api.get_pending_payout_info(telegram_id)
    settings = await api.get_system_settings()
    return {
        "balances": balances or {"USDT": 0},
        "active": active or {"active": False},
        "my_deals": my_deals or {"active_deals": [], "completed_deals": []},
        "pending_payout": pending_payout or {"pending": False},
        "settings": settings or {},
    }
