"""
Эндпоинт: балансы по валютам (ledger), список пополнений пользователя.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.models import PaymentInvoice, User
from src.schemas.wallet import BalancesResponse, InvoiceListItem, InvoicesListResponse
from src.services.wallet_service import get_balances

router = APIRouter(prefix="/v1/wallet", tags=["wallet"])


@router.get("/balances", response_model=BalancesResponse)
async def get_wallet_balances(
    telegram_id: int = Query(..., description="Telegram ID пользователя"),
    db: AsyncSession = Depends(get_db),
):
    """Баланс USDT и USDC (сумма COMPLETED транзакций)."""
    bal = await get_balances(db, telegram_id)
    return BalancesResponse(USDT=bal["USDT"], USDC=bal["USDC"])


@router.get("/invoices", response_model=InvoicesListResponse)
async def get_my_invoices(
    telegram_id: int = Query(..., description="Telegram ID пользователя"),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Список пополнений пользователя (NOWPayments), последние первые."""
    result = await db.execute(
        select(User.id).where(User.telegram_id == telegram_id)
    )
    user_id = result.scalar_one_or_none()
    if not user_id:
        return InvoicesListResponse(items=[])

    result = await db.execute(
        select(PaymentInvoice)
        .where(PaymentInvoice.user_id == user_id)
        .order_by(desc(PaymentInvoice.created_at))
        .limit(limit)
    )
    invoices = list(result.scalars().all())
    items = [
        InvoiceListItem(
            id=inv.id,
            order_id=inv.order_id,
            amount=inv.price_amount,
            asset="USDT",
            pay_currency=inv.pay_currency,
            network=inv.network,
            status=inv.status,
            created_at=inv.created_at,
            paid_at=inv.completed_at,
            balance_credited=inv.is_balance_applied,
        )
        for inv in invoices
    ]
    return InvoicesListResponse(items=items)
