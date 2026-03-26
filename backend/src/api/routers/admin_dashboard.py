from __future__ import annotations

import csv
import asyncio
import datetime as dt
import io
import base64
import hashlib
import hmac
import json
import re
import secrets
import struct
import uuid
from urllib.parse import urlparse
from decimal import Decimal
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status, Query, UploadFile, File, Form
from fastapi.responses import PlainTextResponse, FileResponse
from sqlalchemy import and_, desc, func, or_, select, String, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.admin_auth import (
    JWT_COOKIE_NAME,
    create_admin_jwt,
    get_admin_context,
    require_admin_role,
    log_admin_action,
    validate_admin_token,
)
from src.db.session import get_db
from src.models import (
    AdminToken,
    User,
    UserWallet,
    WalletTransaction,
    Invoice,
    LedgerTransaction,
    Deal,
    DealInvestment,
    DealParticipation,
    ReferralReward,
    WithdrawRequest,
    AdminLog,
    PaymentInvoice,
    PaymentWebhookEvent,
    SystemSettings,
    SystemSettingsVersion,
    BroadcastMessage,
    BroadcastDelivery,
    AdminLoginEvent,
)
from src.schemas.admin_dashboard import (
    AdminLogItem,
    DashboardStats,
    DealRow,
    DealStatusResponse,
    DealUpdateRequest,
    DepositDetail,
    DepositRow,
    LedgerAdjustRequest,
    LedgerAdjustResponse,
    LedgerItem,
    LedgerList,
    LoginRequest,
    PaginatedAdminLogs,
    PaginatedBroadcasts,
    PaginatedDeposits,
    PaginatedUsers,
    PaginatedReferralTree,
    SendDealNotificationsResponse,
    UserActionItem,
    UserDetail,
    UserInvestment,
    UserRow,
    UserWithdrawRequest,
    BroadcastRow,
)
from src.services.ledger_service import (
    LEDGER_TYPE_DEPOSIT,
    LEDGER_TYPE_DEPOSIT_BLOCKCHAIN,
    LEDGER_TYPE_INVEST,
    LEDGER_TYPE_INVEST_RETURN,
    LEDGER_TYPE_PROFIT,
    LEDGER_TYPE_WITHDRAW,
    LEDGER_TYPE_REFERRAL_BONUS,
    clear_user_ledger_entries,
    get_balance_usdt,
)
from src.services.deal_service import (
    collection_end_local_for_start,
    get_active_deal,
    get_active_deal_legacy,
    open_new_deal,
    process_pending_payouts,
)
from src.services.notification_service import broadcast_deal_opened, send_telegram_message, send_telegram_photo
from src.core.config import get_settings
from src.services.settings_service import invalidate_system_settings_cache
from src.services.broadcast_service import enqueue_broadcast, retry_failed_deliveries
from src.models.broadcast_message import BROADCAST_STATUS_IN_PROGRESS


BROADCAST_IMAGES_DIR = Path(__file__).resolve().parents[4] / "storage" / "broadcast_images"
ALLOWED_BROADCAST_TAGS = ("b", "strong", "i", "em", "u", "s", "code", "pre", "a", "br")


router = APIRouter(prefix="/database/api", tags=["admin-dashboard"])
SYSTEM_SETTINGS_FIELDS = (
    "min_deposit_usdt",
    "max_deposit_usdt",
    "min_withdraw_usdt",
    "max_withdraw_usdt",
    "min_invest_usdt",
    "max_invest_usdt",
    "allow_deposits",
    "allow_investments",
    "allow_withdrawals",
    "support_contact",
)
SYSTEM_SETTINGS_DEFAULTS = {
    "min_deposit_usdt": "10",
    "max_deposit_usdt": "100000",
    "min_withdraw_usdt": "10",
    "max_withdraw_usdt": "100000",
    "min_invest_usdt": "50",
    "max_invest_usdt": "100000",
    "allow_deposits": True,
    "allow_investments": True,
    "allow_withdrawals": True,
    "support_contact": "",
}
MAINTENANCE_RESET_LOCK = asyncio.Lock()
MAINTENANCE_TABLES = [
    ("Пользователи", User.__table__.name),
    ("Сделки", Deal.__table__.name),
    ("Инвестиции (legacy)", DealInvestment.__table__.name),
    ("Участия в сделках", DealParticipation.__table__.name),
    ("Реферальные начисления", ReferralReward.__table__.name),
    ("Платежи", PaymentInvoice.__table__.name),
    ("Вебхуки платежей", PaymentWebhookEvent.__table__.name),
    ("Счета (legacy)", Invoice.__table__.name),
    ("Выводы", WithdrawRequest.__table__.name),
    ("Ledger", LedgerTransaction.__table__.name),
    ("Кошельки", UserWallet.__table__.name),
    ("Wallet tx (legacy)", WalletTransaction.__table__.name),
    ("Логи админов", AdminLog.__table__.name),
    ("Рассылки", BroadcastMessage.__table__.name),
    ("Доставки рассылок", BroadcastDelivery.__table__.name),
]
MAINTENANCE_LOG_TABLES = [
    ("Логи админов", AdminLog.__table__.name),
    ("Лог входов", AdminLoginEvent.__table__.name),
]
MAINTENANCE_BROADCAST_TABLES = [
    ("Рассылки", BroadcastMessage.__table__.name),
    ("Доставки рассылок", BroadcastDelivery.__table__.name),
]
MAINTENANCE_DEAL_TABLES = [
    ("Реферальные начисления", ReferralReward.__table__.name),
    ("Участия в сделках", DealParticipation.__table__.name),
    ("Инвестиции (legacy)", DealInvestment.__table__.name),
    ("Сделки", Deal.__table__.name),
]
MAINTENANCE_PAYMENT_TABLES = [
    ("Вебхуки платежей", PaymentWebhookEvent.__table__.name),
    ("Платежи", PaymentInvoice.__table__.name),
    ("Счета (legacy)", Invoice.__table__.name),
]


def _totp_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _verify_totp(secret_b32: str, code: str, *, window: int = 1, interval: int = 30) -> bool:
    raw_code = (code or "").strip().replace(" ", "")
    if not raw_code.isdigit() or len(raw_code) not in {6, 7, 8}:
        return False
    sec = secret_b32.strip().upper()
    pad = "=" * ((8 - len(sec) % 8) % 8)
    try:
        key = base64.b32decode(sec + pad, casefold=True)
    except Exception:
        return False
    now = int(dt.datetime.now(dt.timezone.utc).timestamp())
    counter = now // interval
    for off in range(-window, window + 1):
        msg = struct.pack(">Q", counter + off)
        digest = hmac.new(key, msg, hashlib.sha1).digest()
        o = digest[-1] & 0x0F
        val = ((digest[o] & 0x7F) << 24) | ((digest[o + 1] & 0xFF) << 16) | ((digest[o + 2] & 0xFF) << 8) | (digest[o + 3] & 0xFF)
        otp = str(val % 10**6).zfill(6)
        if otp == raw_code:
            return True
    return False


def _sanitize_broadcast_html(text: str) -> str:
    cleaned = (text or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Текст сообщения не может быть пустым")
    # Быстрая валидация: допускаем только безопасный набор Telegram HTML-тегов.
    tags = re.findall(r"</?([a-zA-Z0-9]+)(?:\s+[^>]*)?>", cleaned)
    for tag in tags:
        if tag.lower() not in ALLOWED_BROADCAST_TAGS:
            raise HTTPException(status_code=400, detail=f"Неподдерживаемый HTML-тег: {tag}")
    return cleaned


def _detect_environment(settings) -> str:
    env_raw = str(getattr(settings, "app_env", "") or "").strip().upper()
    if env_raw:
        return env_raw
    db_url = str(getattr(settings, "database_url", "") or "").lower()
    if "prod" in db_url or "production" in db_url:
        return "PRODUCTION"
    if "stage" in db_url or "staging" in db_url:
        return "STAGING"
    return "TEST"


def _database_host_name(database_url: str) -> str:
    try:
        parsed = urlparse(database_url)
        host = parsed.hostname or "unknown-host"
        db_name = (parsed.path or "/").lstrip("/") or "unknown-db"
        return f"{host}/{db_name}"
    except Exception:
        return "unknown-db"


async def _maintenance_preview(db: AsyncSession, keep_settings: bool) -> dict:
    items = []
    total_rows = 0
    for title, table_name in MAINTENANCE_TABLES:
        count_q = await db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))
        rows_count = int(count_q.scalar() or 0)
        items.append({"title": title, "table": table_name, "rows": rows_count})
        total_rows += rows_count
    cleared_tables = [name for _, name in MAINTENANCE_TABLES]
    if not keep_settings:
        cleared_tables.append(SystemSettings.__table__.name)
    return {
        "items": items,
        "total_rows": total_rows,
        "tables_cleared": cleared_tables,
        "will_keep": [
            "Схема БД",
            "Системные конфиги",
            "Финансовые настройки" if keep_settings else "—",
        ],
    }


async def _collect_referral_tree_ids(db: AsyncSession, root_user_id: int, max_levels: int = 10) -> tuple[list[int], dict[int, int]]:
    """
    Собирает всю реферальную ветку до max_levels уровней:
    - all_ids: все уникальные id потомков (уровни 1..N)
    - levels: карта user_id -> уровень в дереве
    """
    visited: set[int] = {root_user_id}
    current_level_ids: list[int] = [root_user_id]
    all_ids: list[int] = []
    levels: dict[int, int] = {}
    for level in range(1, max_levels + 1):
        if not current_level_ids:
            break
        rows = await db.execute(select(User.id).where(User.referrer_id.in_(current_level_ids)))
        raw_ids = [int(r[0]) for r in rows.all()]
        dedup_ids = list(dict.fromkeys(raw_ids))
        level_ids = [uid for uid in dedup_ids if uid not in visited]
        if not level_ids:
            current_level_ids = []
            continue
        for uid in level_ids:
            levels[uid] = level
        all_ids.extend(level_ids)
        visited.update(level_ids)
        current_level_ids = level_ids
    return all_ids, levels


def _settings_snapshot(row: SystemSettings) -> dict:
    return {
        "min_deposit_usdt": str(row.min_deposit_usdt),
        "max_deposit_usdt": str(row.max_deposit_usdt),
        "min_withdraw_usdt": str(row.min_withdraw_usdt),
        "max_withdraw_usdt": str(row.max_withdraw_usdt),
        "min_invest_usdt": str(row.min_invest_usdt),
        "max_invest_usdt": str(row.max_invest_usdt),
        "allow_deposits": bool(row.allow_deposits),
        "allow_investments": bool(row.allow_investments),
        "allow_withdrawals": bool(getattr(row, "allow_withdrawals", True)),
        "support_contact": str(getattr(row, "support_contact", "") or ""),
    }


def _coerce_bool(value_raw: object) -> bool:
    if isinstance(value_raw, bool):
        return value_raw
    value_norm = str(value_raw).strip().lower()
    if value_norm in {"1", "true", "yes", "on"}:
        return True
    if value_norm in {"0", "false", "no", "off"}:
        return False
    raise HTTPException(status_code=400, detail="value must be boolean")


def _validate_full_settings_payload(payload: dict) -> dict:
    parsed: dict = {}
    for field in SYSTEM_SETTINGS_FIELDS:
        if field not in payload:
            raise HTTPException(status_code=400, detail=f"Missing field: {field}")
        if field in {"allow_deposits", "allow_investments", "allow_withdrawals"}:
            parsed[field] = _coerce_bool(payload.get(field))
            continue
        if field == "support_contact":
            parsed[field] = str(payload.get(field) or "").strip()[:255]
            continue
        raw = str(payload.get(field, "")).replace(",", ".").strip()
        try:
            value = Decimal(raw)
        except Exception:
            raise HTTPException(status_code=400, detail=f"{field} must be a number")
        if value <= 0:
            raise HTTPException(status_code=400, detail=f"{field} must be greater than 0")
        parsed[field] = value

    if parsed["min_deposit_usdt"] > parsed["max_deposit_usdt"]:
        raise HTTPException(status_code=400, detail="Минимальный депозит не может быть больше максимального")
    if parsed["min_withdraw_usdt"] > parsed["max_withdraw_usdt"]:
        raise HTTPException(status_code=400, detail="Минимальный вывод не может быть больше максимального")
    if parsed["min_invest_usdt"] > parsed["max_invest_usdt"]:
        raise HTTPException(status_code=400, detail="Минимальная инвестиция не может быть больше максимальной")
    return parsed


def _broadcast_row_to_schema(row: BroadcastMessage) -> BroadcastRow:
    image_url = f"/database/api/broadcasts/{row.id}/image" if row.image_path else None
    return BroadcastRow(
        id=row.id,
        text_html=row.text_html,
        image_url=image_url,
        status=row.status,
        audience_segment=row.audience_segment or "all",
        total_recipients=row.total_recipients,
        sent_count=row.sent_count,
        failed_count=row.failed_count,
        created_at=row.created_at,
        scheduled_at=row.scheduled_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
        last_error=row.last_error,
    )


@router.post("/login")
async def admin_login(
    request: Request,
    body: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    """Логин по одноразовому токену admin_tokens.token."""
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    try:
        token = await validate_admin_token(db, body.token.strip())
    except HTTPException as e:
        db.add(
            AdminLoginEvent(
                admin_token_id=None,
                success=False,
                ip_address=ip_address,
                user_agent=user_agent,
                reason=str(e.detail),
            )
        )
        await db.flush()
        raise

    settings_row = (await db.execute(select(SystemSettings).limit(1))).scalar_one_or_none()
    if settings_row is not None and bool(getattr(settings_row, "admin_2fa_enabled", False)):
        if not _verify_totp(str(settings_row.admin_2fa_secret or ""), body.otp_code or ""):
            db.add(
                AdminLoginEvent(
                    admin_token_id=token.id,
                    success=False,
                    ip_address=ip_address,
                    user_agent=user_agent,
                    reason="Invalid OTP code",
                )
            )
            await db.flush()
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid OTP code")

    # Можно пометить токен как использованный (по желанию).
    if not token.is_used:
        token.is_used = True
        await db.flush()

    jwt_token = create_admin_jwt(token)
    # HttpOnly cookie на 24 часа.
    response.set_cookie(
        key=JWT_COOKIE_NAME,
        value=jwt_token,
        httponly=True,
        secure=False,  # в проде лучше True
        samesite="Lax",
        path="/database",
        max_age=60 * 60 * 24,
    )

    # Логируем вход.
    await log_admin_action(
        db=db,
        admin_token_id=token.id,
        action_type="LOGIN",
        entity_type="ADMIN",
        entity_id=token.created_by,
    )
    db.add(
        AdminLoginEvent(
            admin_token_id=token.id,
            success=True,
            ip_address=ip_address,
            user_agent=user_agent,
            reason=None,
        )
    )
    await db.flush()

    return {"ok": True}


@router.get("/security/login-events")
async def list_login_events(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    success: Optional[bool] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    query = select(AdminLoginEvent)
    count_q = select(func.count(AdminLoginEvent.id))
    if success is not None:
        query = query.where(AdminLoginEvent.success == success)
        count_q = count_q.where(AdminLoginEvent.success == success)
    total = int((await db.execute(count_q)).scalar() or 0)
    rows = (
        await db.execute(
            query
            .order_by(desc(AdminLoginEvent.created_at))
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_LOGIN_EVENTS",
        entity_type="SECURITY",
        entity_id=0,
    )
    return {
        "items": [
            {
                "id": r.id,
                "admin_token_id": r.admin_token_id,
                "success": bool(r.success),
                "ip_address": r.ip_address,
                "user_agent": r.user_agent,
                "reason": r.reason,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/security/2fa/status")
async def get_admin_2fa_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    row = (await db.execute(select(SystemSettings).limit(1))).scalar_one_or_none()
    enabled = bool(getattr(row, "admin_2fa_enabled", False)) if row else False
    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_2FA_STATUS",
        entity_type="SECURITY",
        entity_id=0,
    )
    return {"enabled": enabled}


@router.post("/security/2fa/setup")
async def setup_admin_2fa(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, created_by = await get_admin_context(request)
    require_admin_role(request)
    async with db.begin():
        row = (await db.execute(select(SystemSettings).limit(1).with_for_update())).scalar_one()
        secret = _totp_secret()
        row.admin_2fa_secret = secret
        row.admin_2fa_enabled = False
        await db.flush()
    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="SETUP_2FA",
        entity_type="SECURITY",
        entity_id=0,
    )
    issuer = "Invext%20Admin"
    label = f"admin_{created_by}"
    return {
        "secret": secret,
        "otpauth_url": f"otpauth://totp/{issuer}:{label}?secret={secret}&issuer={issuer}&digits=6&period=30",
    }


@router.post("/security/2fa/enable")
async def enable_admin_2fa(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    code = (body.get("otp_code") or "").strip()
    async with db.begin():
        row = (await db.execute(select(SystemSettings).limit(1).with_for_update())).scalar_one()
        secret = str(getattr(row, "admin_2fa_secret", "") or "")
        if not secret:
            raise HTTPException(status_code=400, detail="2FA secret is not initialized")
        if not _verify_totp(secret, code):
            raise HTTPException(status_code=400, detail="Invalid OTP code")
        row.admin_2fa_enabled = True
        await db.flush()
    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="ENABLE_2FA",
        entity_type="SECURITY",
        entity_id=0,
    )
    return {"ok": True, "enabled": True}


@router.post("/security/2fa/disable")
async def disable_admin_2fa(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    code = (body.get("otp_code") or "").strip()
    async with db.begin():
        row = (await db.execute(select(SystemSettings).limit(1).with_for_update())).scalar_one()
        if not bool(getattr(row, "admin_2fa_enabled", False)):
            return {"ok": True, "enabled": False}
        secret = str(getattr(row, "admin_2fa_secret", "") or "")
        if not _verify_totp(secret, code):
            raise HTTPException(status_code=400, detail="Invalid OTP code")
        row.admin_2fa_enabled = False
        row.admin_2fa_secret = None
        await db.flush()
    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="DISABLE_2FA",
        entity_type="SECURITY",
        entity_id=0,
    )
    return {"ok": True, "enabled": False}


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)

    # Кол-во пользователей.
    users_count_result = await db.execute(select(func.count(User.id)))
    users_count = int(users_count_result.scalar() or 0)

    # Общий баланс по ledger.
    deposits_profit_result = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            LedgerTransaction.type.in_((
                LEDGER_TYPE_DEPOSIT, LEDGER_TYPE_DEPOSIT_BLOCKCHAIN,
                LEDGER_TYPE_INVEST_RETURN,
                LEDGER_TYPE_PROFIT, LEDGER_TYPE_REFERRAL_BONUS,
            ))
        )
    )
    invest_withdraw_result = await db.execute(
        select(func.coalesce(func.sum(LedgerTransaction.amount_usdt), 0)).where(
            LedgerTransaction.type.in_((LEDGER_TYPE_INVEST, LEDGER_TYPE_WITHDRAW))
        )
    )
    credits = deposits_profit_result.scalar() or Decimal("0")
    debits = invest_withdraw_result.scalar() or Decimal("0")
    total_balance = credits - debits

    # Активная сделка (новая логика: active + окно, или legacy: open).
    active_deal = await get_active_deal(db) or await get_active_deal_legacy(db)
    active_deal_number = None
    active_deal_percent: Optional[Decimal] = None
    active_deal_invested: Optional[Decimal] = None
    active_deal_closes_at = None
    if active_deal:
        active_deal_number = active_deal.number
        active_deal_percent = active_deal.profit_percent or active_deal.percent
        active_deal_closes_at = active_deal.end_at or active_deal.closed_at

        invested_p = await db.execute(
            select(func.coalesce(func.sum(DealParticipation.amount), 0)).where(
                DealParticipation.deal_id == active_deal.id,
            )
        )
        invested_i = await db.execute(
            select(func.coalesce(func.sum(DealInvestment.amount), 0)).where(
                DealInvestment.deal_id == active_deal.id,
                DealInvestment.status == "active",
            )
        )
        active_deal_invested = (invested_p.scalar() or Decimal("0")) + (invested_i.scalar() or Decimal("0"))

    # Pending выводы.
    pending_withdrawals_result = await db.execute(
        select(func.count(WithdrawRequest.id)).where(WithdrawRequest.status == "PENDING")
    )
    pending_withdrawals_count = int(pending_withdrawals_result.scalar() or 0)

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_DASHBOARD",
        entity_type="DASHBOARD",
        entity_id=0,
    )

    return DashboardStats(
        users_count=users_count,
        total_ledger_balance_usdt=total_balance,
        active_deal_number=active_deal_number,
        active_deal_percent=active_deal_percent,
        active_deal_invested_usdt=active_deal_invested,
        active_deal_closes_at=active_deal_closes_at,
        pending_withdrawals_count=pending_withdrawals_count,
    )


@router.get("/dashboard/extended")
async def get_dashboard_extended(
    request: Request,
    period_days: int = Query(7, ge=1, le=30),
    db: AsyncSession = Depends(get_db),
):
    """Расширенные метрики для дашборда админки без изменения базового контракта /dashboard."""
    admin_token_id, _ = await get_admin_context(request)
    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=period_days)

    dep_users_subq = (
        select(PaymentInvoice.user_id)
        .where(
            PaymentInvoice.created_at >= since,
            PaymentInvoice.status.in_(("finished", "paid")),
        )
        .distinct()
        .subquery()
    )
    inv_users_p = (
        select(DealParticipation.user_id.label("user_id"))
        .where(DealParticipation.created_at >= since)
    )
    inv_users_i = (
        select(DealInvestment.user_id.label("user_id"))
        .where(DealInvestment.created_at >= since)
    )
    inv_users_subq = inv_users_p.union(inv_users_i).subquery()

    dep_users_count_result = await db.execute(select(func.count()).select_from(dep_users_subq))
    dep_users_count = int(dep_users_count_result.scalar() or 0)

    converted_count_result = await db.execute(
        select(func.count())
        .select_from(inv_users_subq)
        .where(inv_users_subq.c.user_id.in_(select(dep_users_subq.c.user_id)))
    )
    converted_count = int(converted_count_result.scalar() or 0)
    conversion_pct = (
        (Decimal(converted_count) / Decimal(dep_users_count) * Decimal("100"))
        if dep_users_count > 0
        else Decimal("0")
    )

    avg_deposit_result = await db.execute(
        select(func.avg(PaymentInvoice.amount)).where(
            PaymentInvoice.created_at >= since,
            PaymentInvoice.status.in_(("finished", "paid")),
        )
    )
    avg_deposit = avg_deposit_result.scalar() or Decimal("0")

    top_balances_result = await db.execute(
        select(User.id, User.telegram_id, User.username, User.balance_usdt)
        .order_by(desc(User.balance_usdt))
        .limit(5)
    )
    top_balances = [
        {
            "user_id": uid,
            "telegram_id": tg,
            "username": username,
            "balance_usdt": str(balance or Decimal("0")),
        }
        for uid, tg, username, balance in top_balances_result.all()
    ]

    ref_counts_result = await db.execute(
        select(User.referrer_id, func.count(User.id))
        .where(User.referrer_id.is_not(None))
        .group_by(User.referrer_id)
        .order_by(desc(func.count(User.id)))
        .limit(25)
    )
    ref_rewards_result = await db.execute(
        select(ReferralReward.to_user_id, func.coalesce(func.sum(ReferralReward.amount), 0))
        .where(ReferralReward.status == "paid")
        .group_by(ReferralReward.to_user_id)
    )
    rewards_map = {int(uid): Decimal(total or 0) for uid, total in ref_rewards_result.all()}
    refs_map = {int(uid): int(cnt or 0) for uid, cnt in ref_counts_result.all() if uid is not None}
    top_ref_ids = list(set(list(refs_map.keys()) + list(rewards_map.keys())))
    top_referrers = []
    if top_ref_ids:
        ref_users_result = await db.execute(
            select(User.id, User.telegram_id, User.username).where(User.id.in_(top_ref_ids))
        )
        info = {int(uid): (tg, username) for uid, tg, username in ref_users_result.all()}
        rows = []
        for uid in top_ref_ids:
            tg, username = info.get(uid, (0, None))
            rows.append(
                {
                    "user_id": uid,
                    "telegram_id": tg,
                    "username": username,
                    "referrals_count": refs_map.get(uid, 0),
                    "referral_income_usdt": str(rewards_map.get(uid, Decimal("0"))),
                }
            )
        rows.sort(
            key=lambda r: (
                int(r["referrals_count"]),
                Decimal(str(r["referral_income_usdt"])),
            ),
            reverse=True,
        )
        top_referrers = rows[:5]

    # DAU (24h): уникальные пользователи с активностью по ключевым сущностям.
    dau_since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=24)
    dau_users = set()
    dau_dep = await db.execute(
        select(PaymentInvoice.user_id).where(PaymentInvoice.created_at >= dau_since)
    )
    dau_users.update(int(uid) for (uid,) in dau_dep.all() if uid is not None)
    dau_led = await db.execute(
        select(LedgerTransaction.user_id).where(LedgerTransaction.created_at >= dau_since)
    )
    dau_users.update(int(uid) for (uid,) in dau_led.all() if uid is not None)
    dau_part = await db.execute(
        select(DealParticipation.user_id).where(DealParticipation.created_at >= dau_since)
    )
    dau_users.update(int(uid) for (uid,) in dau_part.all() if uid is not None)
    dau_inv = await db.execute(
        select(DealInvestment.user_id).where(DealInvestment.created_at >= dau_since)
    )
    dau_users.update(int(uid) for (uid,) in dau_inv.all() if uid is not None)
    dau_24h = len(dau_users)

    # Аномалии (простые сигналы, без изменения бизнес-логики).
    pending_withdrawals_result = await db.execute(
        select(func.count(WithdrawRequest.id)).where(WithdrawRequest.status == "PENDING")
    )
    pending_withdrawals_count = int(pending_withdrawals_result.scalar() or 0)
    created_deposits_result = await db.execute(
        select(func.count(PaymentInvoice.id)).where(PaymentInvoice.created_at >= since)
    )
    created_deposits_count = int(created_deposits_result.scalar() or 0)
    paid_deposits_result = await db.execute(
        select(func.count(PaymentInvoice.id)).where(
            PaymentInvoice.created_at >= since,
            PaymentInvoice.status.in_(("finished", "paid")),
        )
    )
    paid_deposits_count = int(paid_deposits_result.scalar() or 0)
    failed_broadcasts_result = await db.execute(
        select(func.count(BroadcastMessage.id)).where(
            BroadcastMessage.created_at >= dau_since,
            BroadcastMessage.status == "ERROR",
        )
    )
    failed_broadcasts_24h = int(failed_broadcasts_result.scalar() or 0)

    anomaly_alerts = []
    if pending_withdrawals_count >= 30:
        anomaly_alerts.append({
            "type": "WITHDRAWAL_BACKLOG",
            "severity": "high",
            "message": f"Очередь выводов высокая: {pending_withdrawals_count} pending",
        })
    if created_deposits_count >= 20:
        success_rate = (Decimal(paid_deposits_count) / Decimal(created_deposits_count) * Decimal("100")) if created_deposits_count > 0 else Decimal("0")
        if success_rate < Decimal("50"):
            anomaly_alerts.append({
                "type": "LOW_DEPOSIT_SUCCESS",
                "severity": "medium",
                "message": f"Низкий процент успешных депозитов: {success_rate.quantize(Decimal('0.1'))}%",
            })
    if dep_users_count >= 20 and conversion_pct < Decimal("5"):
        anomaly_alerts.append({
            "type": "LOW_CONVERSION",
            "severity": "medium",
            "message": f"Низкая конверсия депозит→инвестиция: {conversion_pct.quantize(Decimal('0.1'))}%",
        })
    if failed_broadcasts_24h > 0:
        anomaly_alerts.append({
            "type": "BROADCAST_FAILURES",
            "severity": "medium",
            "message": f"Ошибки рассылок за 24ч: {failed_broadcasts_24h}",
        })

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_DASHBOARD_EXTENDED",
        entity_type="DASHBOARD",
        entity_id=period_days,
    )

    return {
        "period_days": period_days,
        "deposit_users_count": dep_users_count,
        "converted_users_count": converted_count,
        "deposit_to_invest_conversion_pct": str(conversion_pct.quantize(Decimal("0.01"))),
        "average_deposit_usdt": str(Decimal(avg_deposit).quantize(Decimal("0.01")) if avg_deposit else Decimal("0.00")),
        "top_users_by_balance": top_balances,
        "top_referrers": top_referrers,
        "dau_24h": dau_24h,
        "anomaly_alerts": anomaly_alerts,
    }


@router.get("/search/global")
async def global_search(
    request: Request,
    q: str = Query(..., min_length=1),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    needle = q.strip()
    if not needle:
        return {"users": [], "deals": [], "ledger": []}

    like = f"%{needle}%"
    users_result = await db.execute(
        select(User.id, User.telegram_id, User.username)
        .where(
            or_(
                User.username.ilike(like),
                func.cast(User.telegram_id, String).ilike(like),
            )
        )
        .order_by(desc(User.created_at))
        .limit(8)
    )
    users = [
        {"id": uid, "telegram_id": tg, "username": username}
        for uid, tg, username in users_result.all()
    ]

    deals_result = await db.execute(
        select(Deal.id, Deal.number, Deal.status)
        .where(
            or_(
                func.cast(Deal.number, String).ilike(like),
                Deal.title.ilike(like),
            )
        )
        .order_by(desc(Deal.updated_at))
        .limit(8)
    )
    deals = [
        {"id": did, "number": number, "status": status}
        for did, number, status in deals_result.all()
    ]

    ledger_result = await db.execute(
        select(
            LedgerTransaction.id,
            LedgerTransaction.user_id,
            LedgerTransaction.type,
            LedgerTransaction.amount_usdt,
            LedgerTransaction.created_at,
        )
        .where(
            or_(
                LedgerTransaction.type.ilike(like),
                func.cast(LedgerTransaction.user_id, String).ilike(like),
            )
        )
        .order_by(desc(LedgerTransaction.created_at))
        .limit(8)
    )
    ledger = [
        {
            "id": tx_id,
            "user_id": user_id,
            "type": tx_type,
            "amount_usdt": str(amount_usdt),
            "created_at": created_at.isoformat() if created_at else None,
        }
        for tx_id, user_id, tx_type, amount_usdt, created_at in ledger_result.all()
    ]

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="GLOBAL_SEARCH",
        entity_type="SEARCH",
        entity_id=0,
    )
    return {"users": users, "deals": deals, "ledger": ledger}


@router.get("/users", response_model=PaginatedUsers)
async def list_users(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = Query(None),
    activity_filter: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    filters = []
    if search:
        s = f"%{search.strip()}%"
        filters.append(
            or_(
                User.username.ilike(s),
                func.cast(User.telegram_id, String).ilike(s),
            )
        )
    if activity_filter == "with_balance":
        filters.append(User.balance_usdt > 0)
    elif activity_filter == "with_referrals":
        filters.append(
            User.id.in_(
                select(User.referrer_id).where(User.referrer_id.is_not(None))
            )
        )

    total_result = await db.execute(
        select(func.count(User.id)).where(*filters)
    )
    total = int(total_result.scalar() or 0)

    query = (
        select(User)
        .where(*filters)
        .order_by(desc(User.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    users = list(result.scalars().all())

    items = []
    for u in users:
        ledger_balance = await get_balance_usdt(db, u.id)

        # Текущие активные участия (deal_participations в active + deal_investments в open/closed).
        invested_p = await db.execute(
            select(func.coalesce(func.sum(DealParticipation.amount), 0))
            .join(Deal, DealParticipation.deal_id == Deal.id)
            .where(
                DealParticipation.user_id == u.id,
                Deal.status == "active",
            )
        )
        invested_i = await db.execute(
            select(func.coalesce(func.sum(DealInvestment.amount), 0))
            .join(Deal, DealInvestment.deal_id == Deal.id)
            .where(
                DealInvestment.user_id == u.id,
                DealInvestment.status == "active",
                Deal.status.in_(("open", "closed")),
            )
        )
        invested_now = (invested_p.scalar() or Decimal("0")) + (invested_i.scalar() or Decimal("0"))

        items.append(
            UserRow(
                id=u.id,
                telegram_id=u.telegram_id,
                username=u.username,
                balance_usdt=u.balance_usdt,
                ledger_balance_usdt=ledger_balance,
                invested_now_usdt=invested_now,
                is_blocked=bool(getattr(u, "is_blocked", False)),
                blocked_reason=getattr(u, "blocked_reason", None),
                created_at=u.created_at,
            )
        )

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_USERS",
        entity_type="USER_LIST",
        entity_id=0,
    )

    return PaginatedUsers(items=items, total=total, page=page, page_size=page_size)


@router.post("/users/bulk-ledger-credit")
async def bulk_ledger_credit_all_users(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Зачислить одинаковую сумму USDT на баланс (ledger DEPOSIT) всем пользователям.
    Использует ту же модель, что и ручная корректировка в боте (ADMIN_MANUAL).
    Требует confirm=\"BULK_CREDIT\".
    """
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)

    confirm = str(body.get("confirm", "")).strip().upper()
    if confirm != "BULK_CREDIT":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Подтвердите операцию: передайте confirm="BULK_CREDIT"',
        )

    raw_amt = body.get("amount_usdt")
    try:
        amount = Decimal(str(raw_amt).replace(",", ".").strip())
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Некорректная сумма")
    if amount <= 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сумма должна быть больше 0",
        )
    if amount > Decimal("1000000"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сумма слишком велика",
        )

    comment = (body.get("comment") or "").strip() or "Массовое начисление с админки"

    result = await db.execute(select(User.id))
    user_ids = [row[0] for row in result.all()]

    for uid in user_ids:
        tx = LedgerTransaction(
            user_id=uid,
            type=LEDGER_TYPE_DEPOSIT,
            amount_usdt=amount,
            provider="ADMIN_MANUAL",
            metadata_json={
                "comment": comment,
                "bulk_credit": True,
            },
        )
        db.add(tx)
    await db.flush()

    for uid in user_ids:
        u = await db.get(User, uid)
        if u:
            u.balance_usdt = await get_balance_usdt(db, uid)

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="BULK_LEDGER_CREDIT",
        entity_type="SYSTEM",
        entity_id=0,
    )

    total_credited = amount * Decimal(len(user_ids))
    return {
        "ok": True,
        "users_affected": len(user_ids),
        "amount_usdt": str(amount),
        "total_usdt_credited": str(total_credited),
    }


@router.post("/users/bulk-ledger-reset")
async def bulk_ledger_reset_all_users(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Обнулить баланс всем пользователям (очистка их ledger-записей).
    Никакие другие сущности не удаляются.
    Требует confirm="RESET_ALL_BALANCES".
    """
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)

    confirm = str(body.get("confirm", "")).strip().upper()
    if confirm != "RESET_ALL_BALANCES":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Подтвердите операцию: передайте confirm="RESET_ALL_BALANCES"',
        )

    user_ids_result = await db.execute(select(User.id))
    user_ids = [row[0] for row in user_ids_result.all()]
    deleted_total = 0
    for uid in user_ids:
        deleted_total += await clear_user_ledger_entries(db, user_id=uid)
        u = await db.get(User, uid)
        if u:
            u.balance_usdt = Decimal("0")
    await db.flush()

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="BULK_LEDGER_RESET",
        entity_type="SYSTEM",
        entity_id=0,
    )

    return {
        "ok": True,
        "users_affected": len(user_ids),
        "deleted_ledger_rows": deleted_total,
        "new_balance_usdt": "0",
    }


@router.get("/users/{user_id}/ledger", response_model=LedgerList)
async def user_ledger(
    request: Request,
    user_id: int,
    type: Optional[str] = Query(None, description="Фильтр по типу операции"),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    # Базовый запрос: выбираем только нужные поля, без legacy-полей блокчейна.
    query = select(
        LedgerTransaction.created_at,
        LedgerTransaction.type,
        LedgerTransaction.amount_usdt,
        LedgerTransaction.metadata_json,
    ).where(LedgerTransaction.user_id == user_id)

    if type:
        query = query.where(LedgerTransaction.type == type)

    # Фильтры по дате (если переданы ISO-строки).
    if date_from:
        try:
            dt_from = dt.datetime.fromisoformat(date_from)
            query = query.where(LedgerTransaction.created_at >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from")
    if date_to:
        try:
            dt_to = dt.datetime.fromisoformat(date_to)
            query = query.where(LedgerTransaction.created_at <= dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to")

    query = query.order_by(desc(LedgerTransaction.created_at))
    result = await db.execute(query)
    rows = result.all()

    items = []
    for created_at, tx_type, amount_usdt, meta in rows:
        deal_id = None
        comment = None
        if isinstance(meta, dict):
            # deal_id для сделочных операций и реферальных бонусов
            if "deal_id" in meta:
                try:
                    deal_id = int(meta.get("deal_id"))
                except (TypeError, ValueError):
                    deal_id = None

            if tx_type == LEDGER_TYPE_INVEST_RETURN:
                comment = "Возврат тела инвестиции"

            elif tx_type == LEDGER_TYPE_REFERRAL_BONUS:
                source = meta.get("source")
                from_user_id = meta.get("from_user_id")
                level = meta.get("level")
                parts = []
                if source == "deposit":
                    parts.append("Бонус с депозита реферала")
                elif source == "investment":
                    parts.append("Бонус с инвестиции реферала")
                else:
                    parts.append("Реферальный бонус")
                if from_user_id is not None:
                    parts.append(f"user_id={from_user_id}")
                if level is not None:
                    parts.append(f"уровень {level}")
                comment = " | ".join(parts)

        items.append(
            LedgerItem(
                created_at=created_at,
                type=tx_type,
                amount_usdt=amount_usdt,
                deal_id=deal_id,
                comment=comment,
            )
        )

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_LEDGER",
        entity_type="USER",
        entity_id=user_id,
    )

    return LedgerList(items=items)


@router.get(
    "/ledger/{user_id}/export",
    response_class=PlainTextResponse,
)
async def export_ledger_csv(
    request: Request,
    user_id: int,
    format: str = Query("csv", description="csv or xls"),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    result = await db.execute(
        select(
            LedgerTransaction.created_at,
            LedgerTransaction.type,
            LedgerTransaction.amount_usdt,
        )
        .where(LedgerTransaction.user_id == user_id)
        .order_by(LedgerTransaction.created_at.asc())
    )
    rows = list(result.all())

    output = io.StringIO()
    is_xls = format.lower() == "xls"
    if is_xls:
        output.write("date\ttype\tamount_usdt\tcomment\tdeal_id\n")
        for created_at, tx_type, amount_usdt in rows:
            output.write(f"{created_at.isoformat()}\t{tx_type}\t{amount_usdt}\t\t\n")
    else:
        writer = csv.writer(output)
        writer.writerow(["date", "type", "amount_usdt", "comment", "deal_id"])
        for created_at, tx_type, amount_usdt in rows:
            writer.writerow(
                [
                    created_at.isoformat(),
                    tx_type,
                    str(amount_usdt),
                    "",
                    "",
                ]
            )

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="EXPORT_LEDGER",
        entity_type="USER",
        entity_id=user_id,
    )

    filename_ext = "xls" if is_xls else "csv"
    media_type = "application/vnd.ms-excel" if is_xls else "text/csv"
    return PlainTextResponse(
        content=output.getvalue(),
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=ledger_{user_id}.{filename_ext}"},
    )


@router.get("/deposits", response_model=PaginatedDeposits)
async def list_deposits(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status_filter: Optional[str] = Query(None, description="waiting, finished, failed, expired, partially_paid"),
    provider_filter: Optional[str] = Query(None, description="nowpayments"),
    user_id_filter: Optional[int] = Query(None),
    order_id_search: Optional[str] = Query(None),
    external_id_search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    amount_min: Optional[Decimal] = Query(None),
    amount_max: Optional[Decimal] = Query(None),
    currency_filter: Optional[str] = Query(None, description="pay_currency filter"),
    sort: str = Query("created_at_desc", description="created_at_desc, created_at_asc, amount_desc, amount_asc, status"),
    db: AsyncSession = Depends(get_db),
):
    """Список пополнений (PaymentInvoice, NOWPayments) с фильтрацией и поиском."""
    admin_token_id, _ = await get_admin_context(request)

    query = (
        select(PaymentInvoice, User.telegram_id, User.username)
        .join(User, PaymentInvoice.user_id == User.id)
    )
    count_stmt = select(func.count(PaymentInvoice.id)).join(User, PaymentInvoice.user_id == User.id)

    if status_filter:
        query = query.where(PaymentInvoice.status == status_filter.strip().lower())
        count_stmt = count_stmt.where(PaymentInvoice.status == status_filter.strip().lower())
    if provider_filter:
        query = query.where(PaymentInvoice.provider == provider_filter.strip().lower())
        count_stmt = count_stmt.where(PaymentInvoice.provider == provider_filter.strip().lower())
    if user_id_filter is not None:
        query = query.where(PaymentInvoice.user_id == user_id_filter)
        count_stmt = count_stmt.where(PaymentInvoice.user_id == user_id_filter)
    if order_id_search and order_id_search.strip():
        query = query.where(PaymentInvoice.order_id.ilike(f"%{order_id_search.strip()}%"))
        count_stmt = count_stmt.where(PaymentInvoice.order_id.ilike(f"%{order_id_search.strip()}%"))
    if external_id_search and external_id_search.strip():
        query = query.where(PaymentInvoice.external_invoice_id.ilike(f"%{external_id_search.strip()}%"))
        count_stmt = count_stmt.where(PaymentInvoice.external_invoice_id.ilike(f"%{external_id_search.strip()}%"))
    if date_from:
        try:
            t_from = dt.datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            query = query.where(PaymentInvoice.created_at >= t_from)
            count_stmt = count_stmt.where(PaymentInvoice.created_at >= t_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from")
    if date_to:
        try:
            t_to = dt.datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            query = query.where(PaymentInvoice.created_at <= t_to)
            count_stmt = count_stmt.where(PaymentInvoice.created_at <= t_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to")
    if amount_min is not None:
        query = query.where(PaymentInvoice.price_amount >= amount_min)
        count_stmt = count_stmt.where(PaymentInvoice.price_amount >= amount_min)
    if amount_max is not None:
        query = query.where(PaymentInvoice.price_amount <= amount_max)
        count_stmt = count_stmt.where(PaymentInvoice.price_amount <= amount_max)
    if currency_filter:
        c = currency_filter.strip().lower()
        query = query.where(PaymentInvoice.pay_currency == c)
        count_stmt = count_stmt.where(PaymentInvoice.pay_currency == c)

    total_result = await db.execute(count_stmt)
    total = int(total_result.scalar() or 0)

    if sort == "created_at_asc":
        query = query.order_by(PaymentInvoice.created_at.asc())
    elif sort == "amount_desc":
        query = query.order_by(PaymentInvoice.price_amount.desc())
    elif sort == "amount_asc":
        query = query.order_by(PaymentInvoice.price_amount.asc())
    elif sort == "status":
        query = query.order_by(PaymentInvoice.status.asc(), PaymentInvoice.created_at.desc())
    else:
        query = query.order_by(desc(PaymentInvoice.created_at))

    query = query.offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    rows = result.all()

    items = [
        DepositRow(
            id=inv.id,
            order_id=inv.order_id,
            external_invoice_id=inv.external_invoice_id,
            user_id=inv.user_id,
            telegram_id=tg_id,
            username=username,
            amount=inv.price_amount,
            asset="USDT",
            pay_currency=inv.pay_currency,
            network=inv.network,
            provider=inv.provider,
            status=inv.status,
            created_at=inv.created_at,
            paid_at=inv.completed_at,
            completed_at=inv.completed_at,
            balance_credited=inv.is_balance_applied,
        )
        for inv, tg_id, username in rows
    ]

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_DEPOSITS",
        entity_type="DEPOSIT_LIST",
        entity_id=0,
    )

    return PaginatedDeposits(items=items, total=total, page=page, page_size=page_size)


@router.get("/deposits/{deposit_id}", response_model=DepositDetail)
async def get_deposit_detail(
    request: Request,
    deposit_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Детали одного пополнения (PaymentInvoice) и raw webhook payloads."""
    admin_token_id, _ = await get_admin_context(request)

    result = await db.execute(
        select(PaymentInvoice, User.telegram_id, User.username)
        .join(User, PaymentInvoice.user_id == User.id)
        .where(PaymentInvoice.id == deposit_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Deposit not found")

    inv, tg_id, username = row

    webhook_events_result = await db.execute(
        select(PaymentWebhookEvent.payload_json)
        .where(PaymentWebhookEvent.order_id == inv.order_id)
        .order_by(PaymentWebhookEvent.created_at.asc())
    )
    raw_payloads = [r[0] for r in webhook_events_result.all()]
    estimated_fee_amount: Optional[Decimal] = None
    if inv.actually_paid_amount is not None and inv.expected_amount is not None:
        # Для NOWPayments обычно комиссию можно оценить как разницу между фактически
        # полученным и ожидаемым провайдером платежом (если отличается).
        delta = (inv.actually_paid_amount or Decimal("0")) - (inv.expected_amount or Decimal("0"))
        if delta != 0:
            estimated_fee_amount = delta

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_DEPOSIT",
        entity_type="PAYMENT_INVOICE",
        entity_id=deposit_id,
    )

    return DepositDetail(
        id=inv.id,
        order_id=inv.order_id,
        external_invoice_id=inv.external_invoice_id,
        invoice_url=inv.invoice_url,
        user_id=inv.user_id,
        telegram_id=tg_id,
        username=username,
        amount=inv.price_amount,
        asset="USDT",
        pay_currency=inv.pay_currency,
        network=inv.network,
        provider=inv.provider,
        status=inv.status,
        created_at=inv.created_at,
        paid_at=inv.completed_at,
        completed_at=inv.completed_at,
        balance_credited=inv.is_balance_applied,
        expected_amount=inv.expected_amount,
        actually_paid_amount=inv.actually_paid_amount,
        estimated_fee_amount=estimated_fee_amount,
        raw_webhook_payloads=raw_payloads if raw_payloads else None,
    )


@router.get("/deals", response_model=list[DealRow])
async def list_deals(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Список сделок: номер, статус, profit_percent, даты окна."""
    admin_token_id, _ = await get_admin_context(request)

    result = await db.execute(
        select(Deal).order_by(desc(Deal.updated_at))
    )
    deals = result.scalars().all()

    items = [
        DealRow(
            id=d.id,
            number=d.number,
            title=d.title,
            start_at=d.start_at,
            end_at=d.end_at,
            status=d.status,
            profit_percent=d.profit_percent,
            min_participation_usdt=d.min_participation_usdt,
            max_participation_usdt=d.max_participation_usdt,
            max_participants=d.max_participants,
            risk_level=d.risk_level,
            risk_note=d.risk_note,
            referral_processed=d.referral_processed,
            close_notification_sent=d.close_notification_sent,
            created_at=getattr(d, "created_at", None),
            updated_at=getattr(d, "updated_at", None),
            percent=d.percent,
            opened_at=d.opened_at,
            closed_at=d.closed_at,
            finished_at=d.finished_at,
        )
        for d in deals
    ]

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_DEALS",
        entity_type="DEAL_LIST",
        entity_id=0,
    )

    return items


@router.patch("/deals/{deal_id}", response_model=DealRow)
async def update_deal_percent(
    request: Request,
    deal_id: int,
    body: DealUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Обновить сделку: profit_percent, title, start_at, end_at (для draft/active)."""
    admin_token_id, _ = await get_admin_context(request)

    async with db.begin():
        result = await db.execute(
            select(Deal).where(Deal.id == deal_id).with_for_update()
        )
        deal = result.scalar_one_or_none()
        if not deal:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deal not found")

        if deal.status not in ("draft", "active", "open", "closed"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Можно менять только для сделок в статусе draft/active/open/closed",
            )

        if body.profit_percent is not None:
            deal.profit_percent = body.profit_percent
        if body.percent is not None:
            deal.percent = body.percent
        if body.title is not None:
            deal.title = body.title
        if body.start_at is not None:
            deal.start_at = body.start_at
        if body.end_at is not None:
            deal.end_at = body.end_at
        if body.min_participation_usdt is not None:
            deal.min_participation_usdt = body.min_participation_usdt
        if body.max_participation_usdt is not None:
            deal.max_participation_usdt = body.max_participation_usdt
        if body.max_participants is not None:
            if body.max_participants <= 0:
                raise HTTPException(status_code=400, detail="max_participants must be greater than 0")
            deal.max_participants = body.max_participants
        if body.risk_level is not None:
            level = str(body.risk_level or "").strip().lower()
            if level not in {"", "low", "medium", "high"}:
                raise HTTPException(status_code=400, detail="risk_level must be low/medium/high")
            deal.risk_level = level or None
        if body.risk_note is not None:
            deal.risk_note = str(body.risk_note or "").strip()[:255] or None
        if (
            deal.min_participation_usdt is not None
            and deal.max_participation_usdt is not None
            and deal.min_participation_usdt > deal.max_participation_usdt
        ):
            raise HTTPException(status_code=400, detail="min_participation_usdt cannot exceed max_participation_usdt")

        # Формируем DTO внутри транзакции, чтобы не дергать БД после её завершения
        deal_row = DealRow(
            id=deal.id,
            number=deal.number,
            title=deal.title,
            start_at=deal.start_at,
            end_at=deal.end_at,
            status=deal.status,
            profit_percent=deal.profit_percent,
            min_participation_usdt=deal.min_participation_usdt,
            max_participation_usdt=deal.max_participation_usdt,
            max_participants=deal.max_participants,
            risk_level=deal.risk_level,
            risk_note=deal.risk_note,
            referral_processed=deal.referral_processed,
            close_notification_sent=deal.close_notification_sent,
            created_at=getattr(deal, "created_at", None),
            updated_at=getattr(deal, "updated_at", None),
            percent=deal.percent,
            opened_at=deal.opened_at,
            closed_at=deal.closed_at,
            finished_at=deal.finished_at,
        )

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="UPDATE_DEAL",
        entity_type="DEAL",
        entity_id=deal_id,
    )

    return deal_row


@router.post("/deals/open-now", response_model=DealRow)
async def open_deal_now(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Создать и сразу открыть новую активную сделку вручную.
    Окно как в планировщике Europe/Chisinau:
    - обычный день: до следующего дня 12:00
    - если открыта в пятницу: до понедельника 12:00
    При открытии рассылается уведомление пользователям.
    """
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)

    # Обработать отложенные выплаты перед открытием новой сделки.
    await process_pending_payouts(db)

    active = await get_active_deal(db)
    if active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Уже есть активная сделка #{active.number}",
        )

    now_utc = dt.datetime.now(dt.timezone.utc)
    from zoneinfo import ZoneInfo  # локальный импорт, чтобы не тянуть наверх

    schedule_tz = ZoneInfo("Europe/Chisinau")
    now_local = now_utc.astimezone(schedule_tz)
    if now_local.weekday() in (5, 6):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="В субботу и воскресенье открытие нового сбора отключено. Дождитесь понедельника.",
        )
    start_local = now_local
    close_local = collection_end_local_for_start(start_local)
    start_at = start_local.astimezone(dt.timezone.utc)
    end_at = close_local.astimezone(dt.timezone.utc)

    deal = await open_new_deal(db, start_at=start_at, end_at=end_at)

    # Рассылка всем пользователям об открытии сделки.
    users_result = await db.execute(
        select(User.telegram_id).where(User.telegram_id.isnot(None))
    )
    telegram_ids = [r[0] for r in users_result.all() if r[0]]
    await broadcast_deal_opened(
        telegram_ids,
        deal.number,
        close_at=deal.end_at,
    )

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="OPEN_DEAL_MANUAL",
        entity_type="DEAL",
        entity_id=deal.id,
    )

    return DealRow(
        id=deal.id,
        number=deal.number,
        title=deal.title,
        start_at=deal.start_at,
        end_at=deal.end_at,
        status=deal.status,
        profit_percent=deal.profit_percent,
        min_participation_usdt=deal.min_participation_usdt,
        max_participation_usdt=deal.max_participation_usdt,
        max_participants=deal.max_participants,
        risk_level=deal.risk_level,
        risk_note=deal.risk_note,
        referral_processed=deal.referral_processed,
        close_notification_sent=deal.close_notification_sent,
        created_at=getattr(deal, "created_at", None),
        updated_at=getattr(deal, "updated_at", None),
        percent=deal.percent,
        opened_at=deal.opened_at,
        closed_at=deal.closed_at,
        finished_at=deal.finished_at,
    )


@router.post("/deals/force-close")
async def force_close_deal(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Создать запрос на досрочное закрытие активной сделки.
    Фактическое закрытие выполняется после подтверждения админом в Telegram-боте.
    """
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)

    active = await get_active_deal(db)
    if not active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нет активной сделки для досрочного закрытия.",
        )

    settings = get_settings()
    admin_ids = settings.admin_telegram_ids
    if not admin_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ADMIN_TELEGRAM_IDS is not configured",
        )

    text = (
        "⚠️ Запрос досрочного закрытия сделки\n\n"
        f"Сделка: #{active.number}\n"
        f"Статус: {active.status}\n"
        f"Окно: {(active.start_at or '—')} — {(active.end_at or '—')}\n\n"
        "Подтвердите или отклоните досрочное закрытие."
    )

    reply_markup = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Закрыть досрочно",
                    "callback_data": "deal_fc:approve",
                },
                {
                    "text": "❌ Отклонить",
                    "callback_data": "deal_fc:reject",
                },
            ]
        ]
    }

    for admin_tid in admin_ids:
        await send_telegram_message(admin_tid, text, reply_markup=reply_markup)

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="DEAL_FORCE_CLOSE_REQUEST",
        entity_type="DEAL",
        entity_id=active.id,
    )

    return {"requested": True}


@router.get("/deals/{deal_id}/stats")
async def get_deal_stats(
    request: Request,
    deal_id: int,
    db: AsyncSession = Depends(get_db),
):
    await get_admin_context(request)
    deal = await db.get(Deal, deal_id)
    if not deal:
        raise HTTPException(status_code=404, detail="Deal not found")
    agg = await db.execute(
        select(
            func.count(DealParticipation.id),
            func.coalesce(func.sum(DealParticipation.amount), 0),
            func.coalesce(func.avg(DealParticipation.amount), 0),
        ).where(DealParticipation.deal_id == deal_id)
    )
    participants_count, total_invested, avg_ticket = agg.one()
    profit_percent = deal.profit_percent if deal.profit_percent is not None else deal.percent
    estimated_profit = Decimal(total_invested or 0) * Decimal(profit_percent or 0) / Decimal("100")
    risk_alerts: list[str] = []
    if (deal.risk_level or "").lower() == "high":
        risk_alerts.append("HIGH_RISK_LEVEL")
    if deal.end_at is not None:
        mins_left = (deal.end_at - dt.datetime.now(dt.timezone.utc)).total_seconds() / 60
        if mins_left <= 60 and int(participants_count or 0) < 3:
            risk_alerts.append("LOW_PARTICIPANTS_NEAR_CLOSE")
    if Decimal(total_invested or 0) <= Decimal("0"):
        risk_alerts.append("NO_PARTICIPANTS")
    return {
        "deal_id": deal.id,
        "participants_count": int(participants_count or 0),
        "total_invested_usdt": str(Decimal(total_invested or 0)),
        "avg_ticket_usdt": str(Decimal(avg_ticket or 0)),
        "profit_percent": str(Decimal(profit_percent or 0)),
        "estimated_profit_usdt": str(estimated_profit),
        "risk_alerts": risk_alerts,
        "risk_level": deal.risk_level,
        "risk_note": deal.risk_note,
    }


@router.post("/deals/{deal_id}/clone", response_model=DealRow)
async def clone_deal(
    request: Request,
    deal_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    src = await db.get(Deal, deal_id)
    if not src:
        raise HTTPException(status_code=404, detail="Deal not found")
    async with db.begin():
        cloned = await open_new_deal(
            db,
            title=f"{src.title or f'Сделка #{src.number}'} (clone)",
            start_at=None,
            end_at=None,
            profit_percent=src.profit_percent if src.profit_percent is not None else src.percent,
        )
        cloned.min_participation_usdt = src.min_participation_usdt
        cloned.max_participation_usdt = src.max_participation_usdt
        cloned.max_participants = src.max_participants
        cloned.risk_level = src.risk_level
        cloned.risk_note = src.risk_note
    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="CLONE_DEAL",
        entity_type="DEAL",
        entity_id=cloned.id,
    )
    return DealRow(
        id=cloned.id,
        number=cloned.number,
        title=cloned.title,
        start_at=cloned.start_at,
        end_at=cloned.end_at,
        status=cloned.status,
        profit_percent=cloned.profit_percent,
        min_participation_usdt=cloned.min_participation_usdt,
        max_participation_usdt=cloned.max_participation_usdt,
        max_participants=cloned.max_participants,
        risk_level=cloned.risk_level,
        risk_note=cloned.risk_note,
        referral_processed=cloned.referral_processed,
        close_notification_sent=cloned.close_notification_sent,
        created_at=getattr(cloned, "created_at", None),
        updated_at=getattr(cloned, "updated_at", None),
        percent=cloned.percent,
        opened_at=cloned.opened_at,
        closed_at=cloned.closed_at,
        finished_at=cloned.finished_at,
    )


@router.get("/deals/status", response_model=DealStatusResponse)
async def get_deal_status(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Статус текущей активной сделки для блока «Статус сделки» в админке."""
    await get_admin_context(request)

    active = await get_active_deal(db)
    if not active:
        return DealStatusResponse(active_deal=None)

    return DealStatusResponse(
        active_deal=DealRow(
            id=active.id,
            number=active.number,
            title=active.title,
            start_at=active.start_at,
            end_at=active.end_at,
            status=active.status,
            profit_percent=active.profit_percent,
            min_participation_usdt=active.min_participation_usdt,
            max_participation_usdt=active.max_participation_usdt,
            max_participants=active.max_participants,
            risk_level=active.risk_level,
            risk_note=active.risk_note,
            referral_processed=active.referral_processed,
            close_notification_sent=active.close_notification_sent,
            created_at=getattr(active, "created_at", None),
            updated_at=getattr(active, "updated_at", None),
            percent=active.percent,
            opened_at=active.opened_at,
            closed_at=active.closed_at,
            finished_at=active.finished_at,
        )
    )


@router.post("/deals/send-notifications", response_model=SendDealNotificationsResponse)
async def send_deal_notifications(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Принудительно отправить уведомление об открытии текущей активной сделки всем пользователям."""
    admin_token_id, _ = await get_admin_context(request)

    active = await get_active_deal(db)
    if not active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Нет активной сделки. Уведомление об открытии можно отправить только при активной сделке.",
        )

    users_result = await db.execute(
        select(User.telegram_id).where(User.telegram_id.isnot(None))
    )
    telegram_ids = [r[0] for r in users_result.all() if r[0]]

    await broadcast_deal_opened(
        telegram_ids,
        active.number,
        close_at=active.end_at,
    )

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="SEND_DEAL_NOTIFICATIONS",
        entity_type="DEAL",
        entity_id=active.id,
    )

    return SendDealNotificationsResponse(sent_count=len(telegram_ids))


@router.get("/users/{user_id}", response_model=UserDetail)
async def get_user_detail(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    user_result = await db.execute(select(User).where(User.id == user_id))
    u = user_result.scalar_one_or_none()
    if not u:
        raise HTTPException(status_code=404, detail="User not found")

    ledger_balance = await get_balance_usdt(db, u.id)

    investments = []
    part_result = await db.execute(
        select(DealParticipation, Deal)
        .join(Deal, DealParticipation.deal_id == Deal.id)
        .where(DealParticipation.user_id == u.id)
        .order_by(desc(DealParticipation.created_at))
    )
    for p, deal in part_result.all():
        investments.append(
            UserInvestment(
                deal_id=deal.id,
                deal_number=deal.number,
                deal_status=deal.status,
                amount=p.amount,
                profit_amount=p.profit_amount,
                status=p.status,
                payout_at=p.payout_at,
                created_at=p.created_at,
            )
        )
    inv_result = await db.execute(
        select(DealInvestment, Deal)
        .join(Deal, DealInvestment.deal_id == Deal.id)
        .where(DealInvestment.user_id == u.id)
        .order_by(desc(DealInvestment.created_at))
    )
    for inv, deal in inv_result.all():
        investments.append(
            UserInvestment(
                deal_id=deal.id,
                deal_number=deal.number,
                deal_status=deal.status,
                amount=inv.amount,
                profit_amount=inv.profit_amount,
                created_at=inv.created_at,
            )
        )
    investments.sort(key=lambda x: x.created_at, reverse=True)

    withdraw_result = await db.execute(
        select(WithdrawRequest)
        .where(WithdrawRequest.user_id == u.id)
        .order_by(desc(WithdrawRequest.created_at))
    )
    withdraws = list(withdraw_result.scalars().all())

    withdrawals = [
        UserWithdrawRequest(
            id=w.id,
            amount=w.amount,
            currency=w.currency,
            address=w.address,
            status=w.status,
            created_at=w.created_at,
            decided_at=w.decided_at,
        )
        for w in withdraws
    ]

    referrer_row = None
    if u.referrer_id:
        referrer = await db.get(User, u.referrer_id)
        if referrer:
            referrer_ledger = await get_balance_usdt(db, referrer.id)
            referrer_row = UserRow(
                id=referrer.id,
                telegram_id=referrer.telegram_id,
                username=referrer.username,
                balance_usdt=referrer.balance_usdt,
                ledger_balance_usdt=referrer_ledger,
                invested_now_usdt=Decimal("0"),
                is_blocked=bool(getattr(referrer, "is_blocked", False)),
                blocked_reason=getattr(referrer, "blocked_reason", None),
                created_at=referrer.created_at,
            )

    referral_tree_ids, _ = await _collect_referral_tree_ids(db, u.id, max_levels=10)
    referrals_count = len(referral_tree_ids)
    referrals_preview_users: list[User] = []
    if referral_tree_ids:
        referrals_result = await db.execute(
            select(User)
            .where(User.id.in_(referral_tree_ids))
            .order_by(desc(User.created_at))
            .limit(5)
        )
        referrals_preview_users = list(referrals_result.scalars().all())
    referrals_preview = []
    for r in referrals_preview_users:
        referrals_preview.append(
            UserRow(
                id=r.id,
                telegram_id=r.telegram_id,
                username=r.username,
                balance_usdt=r.balance_usdt,
                ledger_balance_usdt=await get_balance_usdt(db, r.id),
                invested_now_usdt=Decimal("0"),
                is_blocked=bool(getattr(r, "is_blocked", False)),
                blocked_reason=getattr(r, "blocked_reason", None),
                created_at=r.created_at,
            )
        )

    recent_actions: list[UserActionItem] = []
    for tx in (await db.execute(
        select(LedgerTransaction)
        .where(LedgerTransaction.user_id == u.id)
        .order_by(desc(LedgerTransaction.created_at))
        .limit(12)
    )).scalars().all():
        recent_actions.append(
            UserActionItem(
                ts=tx.created_at,
                source="ledger",
                title=f"{tx.type}",
                amount=tx.amount_usdt,
            )
        )
    for w in withdraws[:8]:
        recent_actions.append(
            UserActionItem(
                ts=w.created_at,
                source="withdraw",
                title=f"WITHDRAW {w.status}",
                amount=w.amount,
            )
        )
    for i in investments[:8]:
        recent_actions.append(
            UserActionItem(
                ts=i.created_at,
                source="invest",
                title=f"DEAL #{i.deal_number} {i.deal_status}",
                amount=i.amount,
            )
        )
    recent_actions.sort(key=lambda x: x.ts, reverse=True)
    recent_actions = recent_actions[:20]

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_USER",
        entity_type="USER",
        entity_id=user_id,
    )

    return UserDetail(
        user=UserRow(
            id=u.id,
            telegram_id=u.telegram_id,
            username=u.username,
            balance_usdt=u.balance_usdt,
            ledger_balance_usdt=ledger_balance,
            invested_now_usdt=Decimal("0"),  # можно посчитать при необходимости
            is_blocked=bool(getattr(u, "is_blocked", False)),
            blocked_reason=getattr(u, "blocked_reason", None),
            created_at=u.created_at,
        ),
        investments=investments,
        withdrawals=withdrawals,
        referrer=referrer_row,
        referrals_count=referrals_count,
        referrals_preview=referrals_preview,
        recent_actions=recent_actions,
    )


@router.get("/users/{user_id}/referrals", response_model=PaginatedReferralTree)
async def list_user_referrals(
    request: Request,
    user_id: int,
    level: Optional[int] = Query(None, ge=1, le=10, description="Фильтр по уровню L1..L10"),
    q: Optional[str] = Query(None, description="Поиск по username"),
    sort: str = Query("newest", description="newest|oldest|balance"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    root = await db.get(User, user_id)
    if not root:
        raise HTTPException(status_code=404, detail="User not found")

    referral_tree_ids, levels_map = await _collect_referral_tree_ids(db, user_id, max_levels=10)

    # Summary по уровням для всего дерева (без учёта фильтров q/level).
    summary_by_level: dict[int, int] = {i: 0 for i in range(1, 11)}
    for lv in levels_map.values():
        if 1 <= lv <= 10:
            summary_by_level[lv] += 1

    if not referral_tree_ids:
        return PaginatedReferralTree(
            items=[],
            total=0,
            page=page,
            page_size=page_size,
            summary_by_level=summary_by_level,
        )

    filtered_ids = referral_tree_ids
    if level is not None:
        filtered_ids = [uid for uid in referral_tree_ids if levels_map.get(uid) == level]
    if not filtered_ids:
        return PaginatedReferralTree(
            items=[],
            total=0,
            page=page,
            page_size=page_size,
            summary_by_level=summary_by_level,
        )

    username_search = (q or "").strip()
    conditions = [User.id.in_(filtered_ids)]
    if username_search:
        conditions.append(User.username.ilike(f"%{username_search}%"))

    total_q = select(func.count()).select_from(User).where(*conditions)
    total = int((await db.execute(total_q)).scalar() or 0)

    query = select(User).where(*conditions)
    if sort == "newest":
        query = query.order_by(desc(User.created_at))
    elif sort == "oldest":
        query = query.order_by(User.created_at)
    elif sort == "balance":
        query = query.order_by(desc(func.coalesce(User.balance_usdt, 0)))
    else:
        raise HTTPException(status_code=400, detail="Invalid sort. Use newest|oldest|balance")

    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = (await db.execute(query)).scalars().all()

    items = [
        {
            "user_id": r.id,
            "telegram_id": r.telegram_id,
            "username": r.username,
            "balance_usdt": r.balance_usdt,
            "level": levels_map.get(r.id, 0),
            "created_at": r.created_at,
        }
        for r in rows
    ]

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_REFERRALS",
        entity_type="USER",
        entity_id=user_id,
    )

    return PaginatedReferralTree(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        summary_by_level=summary_by_level,
    )


@router.get("/withdrawals")
async def list_withdrawals(
    request: Request,
    status_filter: Optional[str] = Query(None, alias="status"),
    amount_min: Optional[Decimal] = Query(None),
    amount_max: Optional[Decimal] = Query(None),
    currency_filter: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    query = select(WithdrawRequest, User).join(User, WithdrawRequest.user_id == User.id)
    if status_filter:
        query = query.where(WithdrawRequest.status == status_filter)
    if amount_min is not None:
        query = query.where(WithdrawRequest.amount >= amount_min)
    if amount_max is not None:
        query = query.where(WithdrawRequest.amount <= amount_max)
    if currency_filter:
        query = query.where(WithdrawRequest.currency == currency_filter.upper())
    query = query.order_by(desc(WithdrawRequest.created_at))
    result = await db.execute(query)
    rows = result.all()

    items = [
        {
            "id": req.id,
            "user_id": req.user_id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "amount": str(req.amount),
            "currency": req.currency,
            "address": req.address,
            "status": req.status,
            "created_at": req.created_at.isoformat(),
        }
        for req, user in rows
    ]

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_WITHDRAWALS",
        entity_type="WITHDRAW",
        entity_id=0,
    )

    return {"items": items}


@router.get("/withdrawals/{withdrawal_id}")
async def get_withdrawal_detail(
    request: Request,
    withdrawal_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    result = await db.execute(
        select(WithdrawRequest, User)
        .join(User, WithdrawRequest.user_id == User.id)
        .where(WithdrawRequest.id == withdrawal_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Withdrawal not found")
    req, user = row

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_WITHDRAWAL",
        entity_type="WITHDRAW",
        entity_id=withdrawal_id,
    )
    return {
        "id": req.id,
        "user_id": req.user_id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "amount": str(req.amount),
        "currency": req.currency,
        "address": req.address,
        "status": req.status,
        "created_at": req.created_at.isoformat() if req.created_at else None,
        "decided_at": req.decided_at.isoformat() if req.decided_at else None,
    }


@router.post("/users/{user_id}/ledger-adjust", response_model=LedgerAdjustResponse)
async def user_ledger_adjust(
    request: Request,
    user_id: int,
    body: LedgerAdjustRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Создать запрос на ручную корректировку баланса пользователя.
    Фактическое изменение баланса выполняется после подтверждения админом в боте.
    """
    if body.amount_usdt == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Amount must be non-zero")

    admin_token_id, admin_telegram_id = await get_admin_context(request)
    require_admin_role(request)

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    settings = get_settings()
    admin_ids = settings.admin_telegram_ids
    if not admin_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="ADMIN_TELEGRAM_IDS is not configured",
        )

    amount = body.amount_usdt
    amount_str = str(amount)
    comment = body.comment or ""
    request_tag = uuid.uuid4().hex[:10]

    text = (
        "⚠️ Запрос ручной корректировки баланса\n\n"
        f"user_id: {user.id}\n"
        f"telegram_id: {user.telegram_id}\n"
        f"Сумма: {amount_str} USDT\n"
        f"Запрос: {request_tag}\n"
        f"Комментарий: {comment or '—'}\n\n"
        "Подтвердите или отклоните корректировку."
    )

    # callback_data ограничено ~64 байт, поэтому кодируем только нужный минимум.
    callback_base = f"{user.id}:{amount_str}:{request_tag}"
    reply_markup = {
        "inline_keyboard": [
            [
                {
                    "text": "✅ Принять",
                    "callback_data": f"ledger_adj:approve:{callback_base}",
                },
                {
                    "text": "❌ Отклонить",
                    "callback_data": f"ledger_adj:reject:{callback_base}",
                },
            ]
        ]
    }

    sent_to = 0
    for admin_tid in admin_ids:
        if await send_telegram_message(admin_tid, text, reply_markup=reply_markup):
            sent_to += 1

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="LEDGER_MANUAL_ADJUST_REQUEST",
        entity_type="USER",
        entity_id=user.id,
    )

    # Для совместимости с фронтом возвращаем новое поле, но баланс пока не меняем.
    return LedgerAdjustResponse(user_id=user_id, new_balance_usdt=user.balance_usdt)


@router.post("/users/{user_id}/block")
async def set_user_block_state(
    request: Request,
    user_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    is_blocked = bool(body.get("is_blocked", True))
    reason = (body.get("reason") or "").strip() or None
    user.is_blocked = is_blocked
    user.blocked_reason = reason if is_blocked else None
    await db.flush()

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="BLOCK_USER" if is_blocked else "UNBLOCK_USER",
        entity_type="USER",
        entity_id=user_id,
    )
    return {
        "ok": True,
        "user_id": user_id,
        "is_blocked": bool(user.is_blocked),
        "blocked_reason": user.blocked_reason,
    }


@router.post("/users/{user_id}/ledger-reset")
async def reset_user_balance_only(
    request: Request,
    user_id: int,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Сбросить только баланс пользователя (очистка ledger_transactions для user_id).
    Остальные сущности пользователя не затрагиваются.
    Требует confirm="RESET_BALANCE".
    """
    admin_token_id, _ = await get_admin_context(request)

    confirm = str(body.get("confirm", "")).strip().upper()
    if confirm != "RESET_BALANCE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail='Подтвердите операцию: передайте confirm="RESET_BALANCE"',
        )

    async with db.begin():
        user_result = await db.execute(
            select(User).where(User.id == user_id).with_for_update()
        )
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # Защита финансовой целостности: не сбрасываем ledger при незавершённых участиях.
        active_participation = await db.execute(
            select(DealParticipation.id)
            .where(
                DealParticipation.user_id == user_id,
                DealParticipation.status.in_(("active", "in_progress_payout")),
            )
            .limit(1)
        )
        if active_participation.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя сбросить баланс: у пользователя есть активные/незавершённые участия в сделках",
            )

        active_legacy_investment = await db.execute(
            select(DealInvestment.id)
            .where(
                DealInvestment.user_id == user_id,
                DealInvestment.status == "active",
            )
            .limit(1)
        )
        if active_legacy_investment.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Нельзя сбросить баланс: у пользователя есть активные инвестиции",
            )

        deleted_rows = await clear_user_ledger_entries(db, user_id=user_id)
        user.balance_usdt = Decimal("0")
        await db.flush()

        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="LEDGER_RESET_BALANCE_ONLY",
            entity_type="USER",
            entity_id=user_id,
        )

    return {
        "ok": True,
        "user_id": user_id,
        "deleted_ledger_rows": deleted_rows,
        "new_balance_usdt": "0",
    }


@router.post("/withdrawals/{withdraw_id}/approve")
async def approve_withdrawal(
    request: Request,
    withdraw_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, admin_telegram_id = await get_admin_context(request)

    async with db.begin():
        result = await db.execute(
            select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id).with_for_update()
        )
        req = result.scalar_one_or_none()
        if not req:
            raise HTTPException(status_code=404, detail="Withdraw request not found")
        if req.status != "PENDING":
            # Уже обработано — идемпотентность
            return {"status": req.status}

        user = await db.get(User, req.user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        # Проверяем баланс по леджеру.
        balance = await get_balance_usdt(db, user.id)
        if balance < req.amount:
            raise HTTPException(status_code=400, detail="Недостаточно средств")

        # Создаём ledger WITHDRAW (списание).
        tx = LedgerTransaction(
            user_id=user.id,
            type=LEDGER_TYPE_WITHDRAW,
            amount_usdt=req.amount,
        )
        db.add(tx)

        req.status = "APPROVED"
        # В decided_by храним admin_token_id (int32), а telegram_id админа пишется в AdminLog.
        req.decided_by = admin_token_id
        req.decided_at = dt.datetime.now(dt.timezone.utc)

        # Обновляем кэш баланса.
        new_balance = balance - req.amount
        user.balance_usdt = new_balance

        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="WITHDRAW_APPROVE",
            entity_type="WITHDRAW",
            entity_id=req.id,
        )

    return {"status": "APPROVED"}


@router.post("/withdrawals/{withdraw_id}/reject")
async def reject_withdrawal(
    request: Request,
    withdraw_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, admin_telegram_id = await get_admin_context(request)

    async with db.begin():
        result = await db.execute(
            select(WithdrawRequest).where(WithdrawRequest.id == withdraw_id).with_for_update()
        )
        req = result.scalar_one_or_none()
        if not req:
            raise HTTPException(status_code=404, detail="Withdraw request not found")
        if req.status != "PENDING":
            return {"status": req.status}

        req.status = "REJECTED"
        # В decided_by храним admin_token_id (int32), а telegram_id админа пишется в AdminLog.
        req.decided_by = admin_token_id
        req.decided_at = dt.datetime.now(dt.timezone.utc)

        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="WITHDRAW_REJECT",
            entity_type="WITHDRAW",
            entity_id=req.id,
        )

    return {"status": "REJECTED"}


@router.get("/logs", response_model=PaginatedAdminLogs)
async def list_admin_logs(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    query = select(AdminLog)
    if date_from:
        try:
            dt_from = dt.datetime.fromisoformat(date_from)
            query = query.where(AdminLog.created_at >= dt_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_from")
    if date_to:
        try:
            dt_to = dt.datetime.fromisoformat(date_to)
            query = query.where(AdminLog.created_at <= dt_to)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid date_to")
    if search:
        s = f"%{search.strip()}%"
        query = query.where(
            or_(
                AdminLog.action_type.ilike(s),
                AdminLog.entity_type.ilike(s),
            )
        )

    total_result = await db.execute(
        query.with_only_columns(func.count()).order_by(None)
    )
    total = int(total_result.scalar() or 0)

    query = query.order_by(desc(AdminLog.created_at)).offset((page - 1) * page_size).limit(page_size)
    result = await db.execute(query)
    logs = list(result.scalars().all())

    items = [
        AdminLogItem(
            id=log.id,
            admin_token_id=log.admin_token_id,
            action_type=log.action_type,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            created_at=log.created_at,
        )
        for log in logs
    ]

    return PaginatedAdminLogs(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/system-settings")
async def get_system_settings_admin(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)

    result = await db.execute(select(SystemSettings).limit(1))
    row = result.scalar_one()

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_SYSTEM_SETTINGS",
        entity_type="SYSTEM_SETTINGS",
        entity_id=0,
    )

    snapshot = _settings_snapshot(row)
    snapshot["updated_at"] = row.updated_at.isoformat() if row.updated_at else None
    return snapshot


@router.get("/system-settings/defaults")
async def get_system_settings_defaults(
    request: Request,
):
    await get_admin_context(request)
    return SYSTEM_SETTINGS_DEFAULTS


@router.get("/system-settings/history")
async def get_system_settings_history(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    query = (
        select(SystemSettingsVersion)
        .order_by(desc(SystemSettingsVersion.created_at), desc(SystemSettingsVersion.id))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    total_q = select(func.count(SystemSettingsVersion.id))
    rows = list((await db.execute(query)).scalars().all())
    total = int((await db.execute(total_q)).scalar() or 0)
    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_SYSTEM_SETTINGS_HISTORY",
        entity_type="SYSTEM_SETTINGS",
        entity_id=0,
    )
    return {
        "items": [
            {
                "id": r.id,
                "admin_token_id": r.admin_token_id,
                "source": r.source,
                "snapshot": json.loads(r.snapshot_json),
                "changes": json.loads(r.changes_json),
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.patch("/system-settings")
async def update_system_settings_admin(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)

    field = (str(body.get("field", "")).strip() if body.get("field") is not None else "")
    raw_value = str(body.get("value", "")).replace(",", ".").strip()

    if not field:
        raise HTTPException(status_code=400, detail="field is required")
    allowed_fields = set(SYSTEM_SETTINGS_FIELDS)
    if field not in allowed_fields:
        raise HTTPException(status_code=400, detail="unknown field")

    async with db.begin():
        result = await db.execute(select(SystemSettings).limit(1).with_for_update())
        row = result.scalar_one()

        before = _settings_snapshot(row)
        if field in {"allow_deposits", "allow_investments", "allow_withdrawals"}:
            bool_value = _coerce_bool(body.get("value"))
            if field == "allow_deposits":
                row.allow_deposits = bool_value
            elif field == "allow_investments":
                row.allow_investments = bool_value
            else:
                row.allow_withdrawals = bool_value
        elif field == "support_contact":
            row.support_contact = (str(body.get("value") or "").strip()[:255] or None)
        else:
            try:
                value = Decimal(raw_value)
            except Exception:
                raise HTTPException(status_code=400, detail="value must be a number")
            if value <= 0:
                raise HTTPException(status_code=400, detail="value must be greater than 0")

            # min и max могут совпадать (фиксированная сумма, напр. 50 и 50).
            if field == "min_deposit_usdt" and value > row.max_deposit_usdt:
                raise HTTPException(status_code=400, detail="Минимальный депозит не может быть больше максимального")
            if field == "max_deposit_usdt" and value < row.min_deposit_usdt:
                raise HTTPException(status_code=400, detail="Максимальный депозит не может быть меньше минимального")
            if field == "min_withdraw_usdt" and value > row.max_withdraw_usdt:
                raise HTTPException(status_code=400, detail="Минимальный вывод не может быть больше максимального")
            if field == "max_withdraw_usdt" and value < row.min_withdraw_usdt:
                raise HTTPException(status_code=400, detail="Максимальный вывод не может быть меньше минимального")
            if field == "min_invest_usdt" and value > row.max_invest_usdt:
                raise HTTPException(status_code=400, detail="Минимальная инвестиция не может быть больше максимальной")
            if field == "max_invest_usdt" and value < row.min_invest_usdt:
                raise HTTPException(status_code=400, detail="Максимальная инвестиция не может быть меньше минимальной")

            setattr(row, field, value)

        after = _settings_snapshot(row)
        changes = {k: {"before": before[k], "after": after[k]} for k in SYSTEM_SETTINGS_FIELDS if str(before[k]) != str(after[k])}
        if changes:
            db.add(
                SystemSettingsVersion(
                    admin_token_id=admin_token_id,
                    source="single-field",
                    snapshot_json=json.dumps(after, ensure_ascii=False),
                    changes_json=json.dumps(changes, ensure_ascii=False),
                )
            )

        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="UPDATE_SYSTEM_SETTINGS",
            entity_type="SYSTEM_SETTINGS",
            entity_id=row.id,
        )

    invalidate_system_settings_cache()
    return {"ok": True}


@router.put("/system-settings/bulk")
async def update_system_settings_bulk(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    parsed = _validate_full_settings_payload(body)
    async with db.begin():
        row = (await db.execute(select(SystemSettings).limit(1).with_for_update())).scalar_one()
        before = _settings_snapshot(row)
        for field in SYSTEM_SETTINGS_FIELDS:
            setattr(row, field, parsed[field])
        after = _settings_snapshot(row)
        changes = {k: {"before": before[k], "after": after[k]} for k in SYSTEM_SETTINGS_FIELDS if str(before[k]) != str(after[k])}
        if not changes:
            return {"ok": True, "changed": False}
        db.add(
            SystemSettingsVersion(
                admin_token_id=admin_token_id,
                source="bulk",
                snapshot_json=json.dumps(after, ensure_ascii=False),
                changes_json=json.dumps(changes, ensure_ascii=False),
            )
        )
        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="UPDATE_SYSTEM_SETTINGS_BULK",
            entity_type="SYSTEM_SETTINGS",
            entity_id=row.id,
        )
    invalidate_system_settings_cache()
    return {"ok": True, "changed": True}


@router.post("/system-settings/reset-defaults")
async def reset_system_settings_defaults(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    parsed = _validate_full_settings_payload(SYSTEM_SETTINGS_DEFAULTS)
    async with db.begin():
        row = (await db.execute(select(SystemSettings).limit(1).with_for_update())).scalar_one()
        before = _settings_snapshot(row)
        for field in SYSTEM_SETTINGS_FIELDS:
            setattr(row, field, parsed[field])
        after = _settings_snapshot(row)
        changes = {k: {"before": before[k], "after": after[k]} for k in SYSTEM_SETTINGS_FIELDS if str(before[k]) != str(after[k])}
        if not changes:
            return {"ok": True, "changed": False}
        db.add(
            SystemSettingsVersion(
                admin_token_id=admin_token_id,
                source="reset-defaults",
                snapshot_json=json.dumps(after, ensure_ascii=False),
                changes_json=json.dumps(changes, ensure_ascii=False),
            )
        )
        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="RESET_SYSTEM_SETTINGS_DEFAULTS",
            entity_type="SYSTEM_SETTINGS",
            entity_id=row.id,
        )
    invalidate_system_settings_cache()
    return {"ok": True, "changed": True}


@router.get("/broadcasts", response_model=PaginatedBroadcasts)
async def list_broadcasts(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    total_result = await db.execute(select(func.count(BroadcastMessage.id)))
    total = int(total_result.scalar() or 0)
    result = await db.execute(
        select(BroadcastMessage)
        .order_by(desc(BroadcastMessage.created_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = list(result.scalars().all())

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_BROADCASTS",
        entity_type="BROADCAST",
        entity_id=0,
    )
    return PaginatedBroadcasts(
        items=[_broadcast_row_to_schema(r) for r in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/broadcasts/{broadcast_id}", response_model=BroadcastRow)
async def get_broadcast_detail(
    request: Request,
    broadcast_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    row = await db.get(BroadcastMessage, broadcast_id)
    if not row:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_BROADCAST",
        entity_type="BROADCAST",
        entity_id=broadcast_id,
    )
    return _broadcast_row_to_schema(row)


@router.get("/broadcasts/{broadcast_id}/image")
async def get_broadcast_image(
    request: Request,
    broadcast_id: int,
    db: AsyncSession = Depends(get_db),
):
    await get_admin_context(request)
    row = await db.get(BroadcastMessage, broadcast_id)
    if not row or not row.image_path:
        raise HTTPException(status_code=404, detail="Image not found")
    image_path = Path(row.image_path)
    if not image_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")
    return FileResponse(path=str(image_path))


@router.post("/broadcasts", response_model=BroadcastRow)
async def create_broadcast(
    request: Request,
    text_html: str = Form(...),
    audience_segment: str = Form("all"),
    scheduled_at: str | None = Form(default=None),
    image: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    text_value = _sanitize_broadcast_html(text_html)
    # Telegram caption limit, если отправляем картинку.
    if image is not None and len(text_value) > 1024:
        raise HTTPException(status_code=400, detail="Для сообщения с изображением текст должен быть не длиннее 1024 символов")

    image_path: str | None = None
    if image is not None:
        BROADCAST_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(image.filename or "").suffix.lower()
        if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise HTTPException(status_code=400, detail="Поддерживаются изображения: jpg, jpeg, png, webp")
        file_name = f"{uuid.uuid4().hex}{suffix}"
        target = BROADCAST_IMAGES_DIR / file_name
        content = await image.read()
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="Размер изображения не должен превышать 10MB")
        target.write_bytes(content)
        image_path = str(target)

    # Защита от повторного запуска: пока есть IN_PROGRESS, не создаём новую кампанию.
    in_progress = await db.execute(
        select(BroadcastMessage.id).where(BroadcastMessage.status == BROADCAST_STATUS_IN_PROGRESS).limit(1)
    )
    if in_progress.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="Уже есть активная рассылка в процессе")

    scheduled_at_dt: dt.datetime | None = None
    if scheduled_at:
        try:
            parsed = dt.datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            scheduled_at_dt = parsed.astimezone(dt.timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="Некорректная дата scheduled_at")
        if scheduled_at_dt <= dt.datetime.now(dt.timezone.utc):
            raise HTTPException(status_code=400, detail="Дата отложенной отправки должна быть в будущем")

    allowed_segments = {"all", "with_balance", "with_referrals", "active_24h"}
    segment = (audience_segment or "all").strip().lower()
    if segment not in allowed_segments:
        raise HTTPException(status_code=400, detail="Некорректный audience_segment")

    row = await enqueue_broadcast(
        db,
        text_html=text_value,
        image_path=image_path,
        scheduled_at=scheduled_at_dt,
        audience_segment=segment,
    )
    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="CREATE_BROADCAST",
        entity_type="BROADCAST",
        entity_id=row.id,
    )
    await db.flush()
    return _broadcast_row_to_schema(row)


@router.post("/broadcasts/test-send")
async def test_send_broadcast(
    request: Request,
    telegram_id: int = Form(...),
    text_html: str = Form(...),
    image: UploadFile | None = File(default=None),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    text_value = _sanitize_broadcast_html(text_html)
    if image is not None and len(text_value) > 1024:
        raise HTTPException(status_code=400, detail="Для сообщения с изображением текст должен быть не длиннее 1024 символов")

    tmp_path: Path | None = None
    ok = False
    try:
        if image is not None:
            BROADCAST_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
            suffix = Path(image.filename or "").suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                raise HTTPException(status_code=400, detail="Поддерживаются изображения: jpg, jpeg, png, webp")
            tmp_path = BROADCAST_IMAGES_DIR / f"test_{uuid.uuid4().hex}{suffix}"
            content = await image.read()
            if len(content) > 10 * 1024 * 1024:
                raise HTTPException(status_code=400, detail="Размер изображения не должен превышать 10MB")
            tmp_path.write_bytes(content)
            ok = await send_telegram_photo(
                chat_id=telegram_id,
                photo_path=str(tmp_path),
                caption=text_value,
                parse_mode="HTML",
            )
        else:
            ok = await send_telegram_message(
                chat_id=telegram_id,
                text=text_value,
                parse_mode="HTML",
            )
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:
                pass

    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="TEST_BROADCAST_SEND",
        entity_type="BROADCAST",
        entity_id=telegram_id,
    )
    if not ok:
        raise HTTPException(status_code=400, detail="Тестовая отправка не удалась")
    return {"ok": True}


@router.post("/broadcasts/{broadcast_id}/retry-failed")
async def retry_broadcast_failed(
    request: Request,
    broadcast_id: int,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    row = await db.get(BroadcastMessage, broadcast_id)
    if not row:
        raise HTTPException(status_code=404, detail="Broadcast not found")
    retried = await retry_failed_deliveries(db, broadcast_id=broadcast_id)
    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="RETRY_BROADCAST_FAILED",
        entity_type="BROADCAST",
        entity_id=broadcast_id,
    )
    return {"ok": True, "retried": retried}


@router.post("/maintenance/reset-data")
async def reset_test_data(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Очистить тестовые данные из БД (без удаления схемы).
    По умолчанию сохраняет system_settings.
    """
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)

    confirm = str(body.get("confirm", "")).strip().upper()
    keep_settings = bool(body.get("keep_settings", True))
    dry_run = bool(body.get("dry_run", False))
    if confirm != "RESET":
        raise HTTPException(status_code=400, detail="Подтверждение не пройдено. Передайте confirm=RESET")
    if MAINTENANCE_RESET_LOCK.locked():
        raise HTTPException(status_code=409, detail="Операция очистки уже выполняется. Повторите позже.")
    async with MAINTENANCE_RESET_LOCK:
        preview = await _maintenance_preview(db, keep_settings=keep_settings)
        if dry_run:
            await log_admin_action(
                db=db,
                admin_token_id=admin_token_id,
                action_type="MAINTENANCE_RESET_DRY_RUN",
                entity_type="DATABASE",
                entity_id=0,
            )
            return {
                "ok": True,
                "dry_run": True,
                **preview,
                "keep_settings": keep_settings,
            }

        table_names = list(preview["tables_cleared"])
        table_names_sql = ", ".join(f'"{name}"' for name in table_names)
        await db.execute(text(f"TRUNCATE TABLE {table_names_sql} RESTART IDENTITY CASCADE"))
        await db.flush()

        # После очистки оставляем один служебный лог о выполнении операции.
        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="MAINTENANCE_RESET_DATA",
            entity_type="DATABASE",
            entity_id=0,
        )

        return {
            "ok": True,
            "dry_run": False,
            "tables_cleared": table_names,
            "keep_settings": keep_settings,
            "preview_before_reset": preview,
        }


@router.get("/maintenance/reset-data/summary")
async def get_reset_data_summary(
    request: Request,
    keep_settings: bool = Query(True),
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    settings = get_settings()
    env_name = _detect_environment(settings)
    preview = await _maintenance_preview(db, keep_settings=keep_settings)
    last_backup_q = await db.execute(
        select(func.max(AdminLog.created_at)).where(AdminLog.action_type == "MAINTENANCE_BACKUP_CREATED")
    )
    last_backup_at = last_backup_q.scalar()
    await log_admin_action(
        db=db,
        admin_token_id=admin_token_id,
        action_type="VIEW_MAINTENANCE_SUMMARY",
        entity_type="DATABASE",
        entity_id=0,
    )
    return {
        "environment": env_name,
        "database": _database_host_name(settings.database_url),
        "backup_available": True,
        "last_backup_at": last_backup_at.isoformat() if last_backup_at else None,
        "keep_settings": keep_settings,
        **preview,
    }


@router.post("/maintenance/backup")
async def maintenance_backup_stub(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    if MAINTENANCE_RESET_LOCK.locked():
        raise HTTPException(status_code=409, detail="Сейчас выполняется другая maintenance-операция. Повторите позже.")

    def _safe_value(v):
        if isinstance(v, Decimal):
            return str(v)
        if isinstance(v, dt.datetime):
            return v.isoformat()
        return v

    def _row_to_dict(row):
        return {col.name: _safe_value(getattr(row, col.name)) for col in row.__table__.columns}

    async with MAINTENANCE_RESET_LOCK:
        snapshot_at = dt.datetime.now(dt.timezone.utc)
        payload = {
            "snapshot_at": snapshot_at.isoformat(),
            "environment": _detect_environment(get_settings()),
            "database": _database_host_name(get_settings().database_url),
            "data": {},
        }
        for key, model in [
            ("system_settings", SystemSettings),
            ("users", User),
            ("deals", Deal),
            ("deal_participations", DealParticipation),
            ("payment_invoices", PaymentInvoice),
            ("withdraw_requests", WithdrawRequest),
            ("ledger_transactions", LedgerTransaction),
            ("admin_logs", AdminLog),
            ("admin_login_events", AdminLoginEvent),
            ("broadcast_messages", BroadcastMessage),
            ("broadcast_deliveries", BroadcastDelivery),
        ]:
            rows = list((await db.execute(select(model))).scalars().all())
            payload["data"][key] = [_row_to_dict(r) for r in rows]
        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="MAINTENANCE_BACKUP_CREATED",
            entity_type="DATABASE",
            entity_id=0,
        )
        file_name = f"invext_backup_{snapshot_at.strftime('%Y%m%d_%H%M%S')}.json"
        body = json.dumps(payload, ensure_ascii=False, indent=2)
        return PlainTextResponse(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
        )


@router.post("/maintenance/clear-broadcasts")
async def maintenance_clear_broadcasts(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    confirm = str(body.get("confirm", "")).strip().upper()
    if confirm != "CLEAR_BROADCASTS":
        raise HTTPException(status_code=400, detail='Подтверждение не пройдено. Передайте confirm="CLEAR_BROADCASTS"')
    if MAINTENANCE_RESET_LOCK.locked():
        raise HTTPException(status_code=409, detail="Сейчас выполняется другая maintenance-операция. Повторите позже.")
    async with MAINTENANCE_RESET_LOCK:
        counts = {}
        total = 0
        for title, table_name in MAINTENANCE_BROADCAST_TABLES:
            cnt = int((await db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))).scalar() or 0)
            counts[title] = cnt
            total += cnt
        table_names_sql = ", ".join(f'"{name}"' for _, name in MAINTENANCE_BROADCAST_TABLES)
        await db.execute(text(f"TRUNCATE TABLE {table_names_sql} RESTART IDENTITY CASCADE"))
        await db.flush()
        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="MAINTENANCE_CLEAR_BROADCASTS",
            entity_type="DATABASE",
            entity_id=0,
        )
        return {
            "ok": True,
            "cleared": counts,
            "total_rows_cleared": total,
        }


@router.post("/maintenance/clear-logs")
async def maintenance_clear_logs(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    confirm = str(body.get("confirm", "")).strip().upper()
    if confirm != "CLEAR_LOGS":
        raise HTTPException(status_code=400, detail='Подтверждение не пройдено. Передайте confirm="CLEAR_LOGS"')
    if MAINTENANCE_RESET_LOCK.locked():
        raise HTTPException(status_code=409, detail="Сейчас выполняется другая maintenance-операция. Повторите позже.")

    async with MAINTENANCE_RESET_LOCK:
        counts = {}
        total = 0
        for title, table_name in MAINTENANCE_LOG_TABLES:
            cnt = int((await db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))).scalar() or 0)
            counts[title] = cnt
            total += cnt
        table_names_sql = ", ".join(f'"{name}"' for _, name in MAINTENANCE_LOG_TABLES)
        await db.execute(text(f"TRUNCATE TABLE {table_names_sql} RESTART IDENTITY CASCADE"))
        await db.flush()
        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="MAINTENANCE_CLEAR_LOGS",
            entity_type="DATABASE",
            entity_id=0,
        )
        return {
            "ok": True,
            "cleared": counts,
            "total_rows_cleared": total,
        }


@router.post("/maintenance/clear-deals")
async def maintenance_clear_deals(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    confirm = str(body.get("confirm", "")).strip().upper()
    if confirm != "CLEAR_DEALS":
        raise HTTPException(status_code=400, detail='Подтверждение не пройдено. Передайте confirm="CLEAR_DEALS"')
    if MAINTENANCE_RESET_LOCK.locked():
        raise HTTPException(status_code=409, detail="Сейчас выполняется другая maintenance-операция. Повторите позже.")
    async with MAINTENANCE_RESET_LOCK:
        counts = {}
        total = 0
        for title, table_name in MAINTENANCE_DEAL_TABLES:
            cnt = int((await db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))).scalar() or 0)
            counts[title] = cnt
            total += cnt
        table_names_sql = ", ".join(f'"{name}"' for _, name in MAINTENANCE_DEAL_TABLES)
        await db.execute(text(f"TRUNCATE TABLE {table_names_sql} RESTART IDENTITY CASCADE"))
        await db.flush()
        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="MAINTENANCE_CLEAR_DEALS",
            entity_type="DATABASE",
            entity_id=0,
        )
        return {
            "ok": True,
            "cleared": counts,
            "total_rows_cleared": total,
        }


@router.post("/maintenance/clear-payments")
async def maintenance_clear_payments(
    request: Request,
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    admin_token_id, _ = await get_admin_context(request)
    require_admin_role(request)
    confirm = str(body.get("confirm", "")).strip().upper()
    if confirm != "CLEAR_PAYMENTS":
        raise HTTPException(status_code=400, detail='Подтверждение не пройдено. Передайте confirm="CLEAR_PAYMENTS"')
    if MAINTENANCE_RESET_LOCK.locked():
        raise HTTPException(status_code=409, detail="Сейчас выполняется другая maintenance-операция. Повторите позже.")
    async with MAINTENANCE_RESET_LOCK:
        counts = {}
        total = 0
        for title, table_name in MAINTENANCE_PAYMENT_TABLES:
            cnt = int((await db.execute(text(f'SELECT COUNT(*) FROM "{table_name}"'))).scalar() or 0)
            counts[title] = cnt
            total += cnt
        table_names_sql = ", ".join(f'"{name}"' for _, name in MAINTENANCE_PAYMENT_TABLES)
        await db.execute(text(f"TRUNCATE TABLE {table_names_sql} RESTART IDENTITY CASCADE"))
        await db.flush()
        await log_admin_action(
            db=db,
            admin_token_id=admin_token_id,
            action_type="MAINTENANCE_CLEAR_PAYMENTS",
            entity_type="DATABASE",
            entity_id=0,
        )
        return {
            "ok": True,
            "cleared": counts,
            "total_rows_cleared": total,
        }

