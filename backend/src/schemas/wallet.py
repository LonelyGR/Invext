"""
Схемы для балансов (ledger) и сохранённых кошельков пользователя.
"""
from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class UserWalletCreate(BaseModel):
    """Тело POST /v1/wallets — добавление кошелька."""
    name: str = Field(..., min_length=1, max_length=255)
    currency: str = Field(..., min_length=1, max_length=10)
    address: str = Field(..., min_length=1, max_length=512)


class UserWalletItem(BaseModel):
    """Элемент списка кошельков."""
    id: int
    name: str
    currency: str
    address: str


class UserWalletsListResponse(BaseModel):
    """Ответ GET /v1/wallets."""
    wallets: List[UserWalletItem]


class BalancesResponse(BaseModel):
    """Балансы по валютам: сумма COMPLETED транзакций DEPOSIT - WITHDRAW."""
    USDT: Decimal = Decimal("0")
    USDC: Decimal = Decimal("0")

    # Для удобства можно вернуть и как dict
    def to_dict(self) -> Dict[str, Decimal]:
        return {"USDT": self.USDT, "USDC": self.USDC}


class InvoiceListItem(BaseModel):
    """Один инвойс в списке «Мои пополнения» (NOWPayments)."""
    id: int
    order_id: str
    amount: Decimal
    asset: str = "USDT"
    pay_currency: str = "usdtbsc"
    network: Optional[str] = None
    status: str
    created_at: datetime
    paid_at: Optional[datetime] = None
    balance_credited: bool


class InvoicesListResponse(BaseModel):
    """Список пополнений пользователя (NOWPayments)."""
    items: List[InvoiceListItem]
