"""Схемы для инвестиций (списание с баланса USDT по ledger)."""
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
