"""
Эндпоинт: балансы по валютам (ledger).
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import get_db
from src.schemas.wallet import BalancesResponse
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
