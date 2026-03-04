from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel


class LoginRequest(BaseModel):
    token: str


class DashboardStats(BaseModel):
    users_count: int
    total_ledger_balance_usdt: Decimal

    active_deal_number: Optional[int] = None
    active_deal_percent: Optional[Decimal] = None
    active_deal_invested_usdt: Optional[Decimal] = None
    active_deal_closes_at: Optional[datetime] = None

    pending_withdrawals_count: int


class UserRow(BaseModel):
    id: int
    telegram_id: int
    username: Optional[str]
    balance_usdt: Decimal
    ledger_balance_usdt: Decimal
    invested_now_usdt: Decimal
    created_at: datetime


class PaginatedUsers(BaseModel):
    items: List[UserRow]
    total: int
    page: int
    page_size: int


class LedgerItem(BaseModel):
    created_at: datetime
    type: str
    amount_usdt: Decimal
    deal_id: Optional[int] = None
    comment: Optional[str] = None


class LedgerList(BaseModel):
    items: List[LedgerItem]


class UserInvestment(BaseModel):
    deal_id: int
    deal_number: int
    deal_status: str
    amount: Decimal
    profit_amount: Optional[Decimal]
    created_at: datetime


class UserWithdrawRequest(BaseModel):
    id: int
    amount: Decimal
    currency: str
    address: str
    status: str
    created_at: datetime
    decided_at: Optional[datetime]


class UserDetail(BaseModel):
    user: UserRow
    investments: List[UserInvestment]
    withdrawals: List[UserWithdrawRequest]


class AdminLogItem(BaseModel):
    id: int
    admin_token_id: int
    action_type: str
    entity_type: str
    entity_id: int
    created_at: datetime


class PaginatedAdminLogs(BaseModel):
    items: List[AdminLogItem]
    total: int
    page: int
    page_size: int

