from decimal import Decimal, InvalidOperation
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security import require_admin_key
from src.db.session import get_db
from src.models.system_settings import SystemSettings
from src.services.settings_service import invalidate_system_settings_cache


router = APIRouter(
    prefix="/v1/admin/system-settings",
    tags=["admin-settings"],
    dependencies=[Depends(require_admin_key)],
)


@router.get("")
async def get_system_settings_admin(
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    result = await db.execute(select(SystemSettings).limit(1))
    row = result.scalar_one()
    return {
        "min_deposit_usdt": str(row.min_deposit_usdt),
        "max_deposit_usdt": str(row.max_deposit_usdt),
        "min_withdraw_usdt": str(row.min_withdraw_usdt),
        "max_withdraw_usdt": str(row.max_withdraw_usdt),
        "min_invest_usdt": str(row.min_invest_usdt),
        "max_invest_usdt": str(row.max_invest_usdt),
        "deal_amount_usdt": str(row.deal_amount_usdt),
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.patch("")
async def update_system_setting_field(
    payload: Dict[str, Any],
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    field = (payload.get("field") or "").strip()
    raw_value = (str(payload.get("value") or "")).replace(",", ".").strip()
    if not field:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="field is required",
        )
    try:
        value = Decimal(raw_value)
    except InvalidOperation:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="value must be a number",
        )
    if value <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="value must be greater than 0",
        )

    allowed_fields = {
        "min_deposit_usdt",
        "max_deposit_usdt",
        "min_withdraw_usdt",
        "max_withdraw_usdt",
        "min_invest_usdt",
        "max_invest_usdt",
        "deal_amount_usdt",
    }
    if field not in allowed_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unknown field",
        )

    async with db.begin():
        result = await db.execute(select(SystemSettings).limit(1).with_for_update())
        row = result.scalar_one()

        # Валидация min/max для соответствующих пар.
        if field == "min_deposit_usdt" and value >= row.max_deposit_usdt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Минимальный депозит должен быть меньше максимального",
            )
        if field == "max_deposit_usdt" and value <= row.min_deposit_usdt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Максимальный депозит должен быть больше минимального",
            )
        if field == "min_withdraw_usdt" and value >= row.max_withdraw_usdt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Минимальный вывод должен быть меньше максимального",
            )
        if field == "max_withdraw_usdt" and value <= row.min_withdraw_usdt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Максимальный вывод должен быть больше минимального",
            )
        if field == "min_invest_usdt" and value >= row.max_invest_usdt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Минимальная инвестиция должна быть меньше максимальной",
            )
        if field == "max_invest_usdt" and value <= row.min_invest_usdt:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Максимальная инвестиция должна быть больше минимальной",
            )

        setattr(row, field, value)

    invalidate_system_settings_cache()
    return {"ok": True}

