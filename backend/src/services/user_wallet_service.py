"""
Сохранённые кошельки пользователя: список, создание, удаление.
"""
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.user import User
from src.models.user_wallet import UserWallet


async def get_user_wallets(db: AsyncSession, telegram_id: int) -> List[dict]:
    """Список кошельков пользователя по telegram_id."""
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        return []
    wallets_result = await db.execute(select(UserWallet).where(UserWallet.user_id == user.id).order_by(UserWallet.id))
    rows = wallets_result.scalars().all()
    return [{"id": w.id, "name": w.name, "currency": w.currency, "address": w.address} for w in rows]


async def create_user_wallet(
    db: AsyncSession,
    telegram_id: int,
    name: str,
    currency: str,
    address: str,
) -> Optional[dict]:
    """Добавить кошелёк. Возвращает созданный кошелёк или None если пользователь не найден."""
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        return None
    w = UserWallet(user_id=user.id, name=name.strip(), currency=currency.strip().upper(), address=address.strip())
    db.add(w)
    await db.flush()
    return {"id": w.id, "name": w.name, "currency": w.currency, "address": w.address}


async def delete_user_wallet(db: AsyncSession, telegram_id: int, wallet_id: int) -> bool:
    """Удалить кошелёк по id. Возвращает True если удалён, False если не найден или не принадлежит пользователю."""
    result = await db.execute(select(User).where(User.telegram_id == telegram_id))
    user = result.scalar_one_or_none()
    if not user:
        return False
    w_result = await db.execute(select(UserWallet).where(UserWallet.id == wallet_id, UserWallet.user_id == user.id))
    w = w_result.scalar_one_or_none()
    if not w:
        return False
    await db.delete(w)
    await db.flush()
    return True
