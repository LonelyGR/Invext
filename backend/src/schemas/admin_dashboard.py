from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, computed_field

from src.services.withdraw_service import withdraw_fee_and_net


class LoginRequest(BaseModel):
    token: str
    otp_code: Optional[str] = None


class DashboardStats(BaseModel):
    users_count: int
    total_ledger_balance_usdt: Decimal

    active_deal_number: Optional[int] = None
    active_deal_percent: Optional[Decimal] = None
    active_deal_invested_usdt: Optional[Decimal] = None
    active_deal_closes_at: Optional[datetime] = None

    pending_withdrawals_count: int


class DealRow(BaseModel):
    id: int
    number: int
    title: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    status: str
    profit_percent: Optional[Decimal] = None
    min_participation_usdt: Optional[Decimal] = None
    max_participation_usdt: Optional[Decimal] = None
    max_participants: Optional[int] = None
    risk_level: Optional[str] = None
    risk_note: Optional[str] = None
    referral_processed: bool = False
    close_notification_sent: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    # Legacy
    percent: Optional[Decimal] = None
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None


class DealUpdateRequest(BaseModel):
    percent: Optional[Decimal] = None  # legacy
    profit_percent: Optional[Decimal] = None
    title: Optional[str] = None
    start_at: Optional[datetime] = None
    end_at: Optional[datetime] = None
    min_participation_usdt: Optional[Decimal] = None
    max_participation_usdt: Optional[Decimal] = None
    max_participants: Optional[int] = None
    risk_level: Optional[str] = None
    risk_note: Optional[str] = None


class DealStatusResponse(BaseModel):
    """Текущая активная сделка для блока «Статус сделки» в админке."""
    active_deal: Optional[DealRow] = None


class SendDealNotificationsResponse(BaseModel):
    sent_count: int


class UserRow(BaseModel):
    id: int
    telegram_id: int
    username: Optional[str]
    balance_usdt: Decimal
    ledger_balance_usdt: Decimal
    invested_now_usdt: Decimal
    is_blocked: bool = False
    blocked_reason: Optional[str] = None
    created_at: datetime


class ReferralTreeRow(BaseModel):
    user_id: int
    telegram_id: int
    username: Optional[str]
    balance_usdt: Decimal
    level: int
    created_at: datetime


class PaginatedReferralTree(BaseModel):
    items: List[ReferralTreeRow]
    total: int
    page: int
    page_size: int
    summary_by_level: Dict[int, int]


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


class LedgerAdjustRequest(BaseModel):
    """Ручная корректировка баланса через леджер (только из админки)."""

    amount_usdt: Decimal
    comment: Optional[str] = None


class LedgerAdjustResponse(BaseModel):
    user_id: int
    new_balance_usdt: Decimal


class UserInvestment(BaseModel):
    deal_id: int
    deal_number: int
    deal_status: str
    amount: Decimal
    profit_amount: Optional[Decimal]
    status: Optional[str] = None
    payout_at: Optional[datetime] = None
    created_at: datetime


class UserWithdrawRequest(BaseModel):
    id: int
    amount: Decimal
    currency: str
    address: str
    status: str
    created_at: datetime
    decided_at: Optional[datetime]

    @computed_field
    def fee_amount(self) -> Decimal:
        fee, _ = withdraw_fee_and_net(self.amount)
        return fee

    @computed_field
    def net_amount(self) -> Decimal:
        _, net = withdraw_fee_and_net(self.amount)
        return net


class UserActionItem(BaseModel):
    ts: datetime
    source: str
    title: str
    amount: Optional[Decimal] = None


class UserDetail(BaseModel):
    user: UserRow
    investments: List[UserInvestment]
    withdrawals: List[UserWithdrawRequest]
    referrer: Optional[UserRow] = None
    referrals_count: int = 0
    referrals_preview: List[UserRow] = []
    recent_actions: List[UserActionItem] = []


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


class DepositRow(BaseModel):
    """Строка списка пополнений (PaymentInvoice, NOWPayments)."""
    id: int
    order_id: str
    external_invoice_id: Optional[str] = None
    user_id: int
    telegram_id: int
    username: Optional[str] = None
    amount: Decimal
    asset: str  # display: USDT
    pay_currency: str = "usdtbsc"
    network: Optional[str] = None
    provider: str = "nowpayments"
    status: str
    created_at: datetime
    paid_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    balance_credited: bool


class DepositDetail(BaseModel):
    """Детали одного пополнения."""
    id: int
    order_id: str
    external_invoice_id: Optional[str] = None
    invoice_url: Optional[str] = None
    user_id: int
    telegram_id: int
    username: Optional[str] = None
    amount: Decimal
    asset: str
    pay_currency: str = "usdtbsc"
    network: Optional[str] = None
    provider: str = "nowpayments"
    status: str
    created_at: datetime
    paid_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    balance_credited: bool
    expected_amount: Optional[Decimal] = None
    actually_paid_amount: Optional[Decimal] = None
    estimated_fee_amount: Optional[Decimal] = None
    raw_webhook_payloads: Optional[List[dict]] = None


class PaginatedDeposits(BaseModel):
    items: List[DepositRow]
    total: int
    page: int
    page_size: int


class BroadcastRow(BaseModel):
    id: int
    text_html: str
    image_url: Optional[str] = None
    status: str
    audience_segment: str = "all"
    total_recipients: int
    sent_count: int
    failed_count: int
    created_at: datetime
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    last_error: Optional[str] = None


class PaginatedBroadcasts(BaseModel):
    items: List[BroadcastRow]
    total: int
    page: int
    page_size: int

