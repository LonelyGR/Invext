"""Схемы для инвестиций (списание с баланса USDT по ledger)."""
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class InvestRequest(BaseModel):
    """Тело POST /api/invest."""

    user_id: int = Field(..., description="telegram_id пользователя")
    amount_usdt: Decimal = Field(
        ...,
        ge=Decimal("1"),
        description="Сумма инвестиций; фактический минимум берётся из SystemSettings.min_invest_usdt",
    )


class InvestResponse(BaseModel):
    """Ответ после успешного списания в инвестиции."""

    invested_amount_usdt: Decimal
    balance_usdt: Decimal
    payout_at: datetime | None = None


class DealParticipationItem(BaseModel):
    deal_number: int
    amount_usdt: Decimal
    status: str
    payout_at: datetime | None = None
    created_at: datetime | None = None


class MyDealsResponse(BaseModel):
    active_deals: list[DealParticipationItem]
    completed_deals: list[DealParticipationItem]


class PendingPayoutInfo(BaseModel):
    """Ожидание выплаты по закрытому сбору (время из deal_schedule_json админки)."""

    pending: bool = False
    deal_number: int | None = None
    payout_at: datetime | None = None
    amount_usdt: Decimal | None = None
