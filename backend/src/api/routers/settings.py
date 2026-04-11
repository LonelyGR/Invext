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
        "allow_deposits": bool(row.allow_deposits),
        "allow_investments": bool(row.allow_investments),
        "allow_withdrawals": bool(getattr(row, "allow_withdrawals", True)),
        "allow_welcome_bonus": bool(getattr(row, "allow_welcome_bonus", True)),
        "welcome_bonus_amount_usdt": str(
            getattr(row, "welcome_bonus_amount_usdt", None) or "100"
        ),
        "welcome_bonus_for_new_users": bool(getattr(row, "welcome_bonus_for_new_users", True)),
        "welcome_bonus_for_zero_balance": bool(
            getattr(row, "welcome_bonus_for_zero_balance", True)
        ),
        "welcome_bonus_new_user_days": int(getattr(row, "welcome_bonus_new_user_days", 30)),
        "support_contact": getattr(row, "support_contact", None),
        "deal_schedule_json": getattr(row, "deal_schedule_json", None),
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
    allowed_fields = {
        "min_deposit_usdt",
        "max_deposit_usdt",
        "min_withdraw_usdt",
        "max_withdraw_usdt",
        "min_invest_usdt",
        "max_invest_usdt",
        "deal_amount_usdt",
        "allow_deposits",
        "allow_investments",
        "allow_withdrawals",
        "allow_welcome_bonus",
        "welcome_bonus_amount_usdt",
        "welcome_bonus_for_new_users",
        "welcome_bonus_for_zero_balance",
        "welcome_bonus_new_user_days",
        "support_contact",
        "deal_schedule_json",
    }
    if field not in allowed_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="unknown field",
        )

    async with db.begin():
        result = await db.execute(select(SystemSettings).limit(1).with_for_update())
        row = result.scalar_one()

        if field in {
            "allow_deposits",
            "allow_investments",
            "allow_withdrawals",
            "allow_welcome_bonus",
            "welcome_bonus_for_new_users",
            "welcome_bonus_for_zero_balance",
        }:
            value_raw = payload.get("value")
            if isinstance(value_raw, bool):
                bool_value = value_raw
            else:
                value_norm = str(value_raw).strip().lower()
                if value_norm in {"1", "true", "yes", "on"}:
                    bool_value = True
                elif value_norm in {"0", "false", "no", "off"}:
                    bool_value = False
                else:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="value must be boolean",
                    )
            if field == "allow_deposits":
                row.allow_deposits = bool_value
            elif field == "allow_investments":
                row.allow_investments = bool_value
            elif field == "allow_withdrawals":
                row.allow_withdrawals = bool_value
            elif field == "allow_welcome_bonus":
                row.allow_welcome_bonus = bool_value
            elif field == "welcome_bonus_for_new_users":
                row.welcome_bonus_for_new_users = bool_value
            else:
                row.welcome_bonus_for_zero_balance = bool_value
        elif field == "welcome_bonus_new_user_days":
            vr = payload.get("value")
            try:
                iv = int(vr)
            except (TypeError, ValueError):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="value must be integer",
                )
            if iv < 1 or iv > 3650:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="welcome_bonus_new_user_days must be 1..3650",
                )
            row.welcome_bonus_new_user_days = iv
        elif field == "support_contact":
            row.support_contact = (str(payload.get("value") or "").strip()[:255] or None)
        elif field == "deal_schedule_json":
            raw = str(payload.get("value") or "").strip()
            row.deal_schedule_json = raw or None
        else:
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

            # min и max могут совпадать (фиксированная сумма).
            if field == "min_deposit_usdt" and value > row.max_deposit_usdt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Минимальный депозит не может быть больше максимального",
                )
            if field == "max_deposit_usdt" and value < row.min_deposit_usdt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Максимальный депозит не может быть меньше минимального",
                )
            if field == "min_withdraw_usdt" and value > row.max_withdraw_usdt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Минимальный вывод не может быть больше максимального",
                )
            if field == "max_withdraw_usdt" and value < row.min_withdraw_usdt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Максимальный вывод не может быть меньше минимального",
                )
            if field == "min_invest_usdt" and value > row.max_invest_usdt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Минимальная инвестиция не может быть больше максимальной",
                )
            if field == "max_invest_usdt" and value < row.min_invest_usdt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Максимальная инвестиция не может быть меньше минимальной",
                )

            setattr(row, field, value)

    invalidate_system_settings_cache()
    return {"ok": True}

