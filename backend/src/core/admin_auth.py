from __future__ import annotations

import datetime as dt
from typing import Optional, Tuple

import jwt
from fastapi import HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import get_settings
from src.db.session import get_db
from src.models import AdminToken, AdminLog


JWT_ALGORITHM = "HS256"
JWT_COOKIE_NAME = "admin_jwt"
JWT_TTL_HOURS = 24


async def validate_admin_token(
    db: AsyncSession,
    token_str: str,
) -> AdminToken:
    """Проверка одноразового токена из таблицы admin_tokens."""
    now = dt.datetime.now(dt.timezone.utc)
    result = await db.execute(
        select(AdminToken).where(AdminToken.token == token_str)
    )
    token = result.scalar_one_or_none()
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )
    if token.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )
    return token


def create_admin_jwt(admin_token: AdminToken) -> str:
    """Создать JWT для админ-дэшборда сроком на 24 часа."""
    settings = get_settings()
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(admin_token.id),
        "created_by": admin_token.created_by,
        "role": getattr(admin_token, "role", "admin"),
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(hours=JWT_TTL_HOURS)).timestamp()),
    }
    return jwt.encode(payload, settings.admin_jwt_secret, algorithm=JWT_ALGORITHM)


def decode_admin_jwt(token: str) -> Tuple[int, int, str]:
    """Вернуть (admin_token_id, created_by_telegram_id, role) из JWT или 401."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.admin_jwt_secret,
            algorithms=[JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )
    admin_token_id = int(payload.get("sub"))
    created_by = int(payload.get("created_by"))
    role = str(payload.get("role") or "admin")
    return admin_token_id, created_by, role


async def get_admin_context(
    request: Request,
) -> Tuple[int, int]:
    """Вернуть (admin_token_id, created_by_telegram_id) из контекста, установленного middleware."""
    admin_token_id = getattr(request.state, "admin_token_id", None)
    created_by = getattr(request.state, "admin_created_by", None)
    if admin_token_id is None or created_by is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return int(admin_token_id), int(created_by)


def get_admin_role(request: Request) -> str:
    role = getattr(request.state, "admin_role", None)
    return str(role or "admin")


def require_admin_role(request: Request) -> None:
    if get_admin_role(request) != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав: требуется роль admin",
        )


async def log_admin_action(
    db: AsyncSession,
    admin_token_id: int,
    action_type: str,
    entity_type: str,
    entity_id: int,
) -> None:
    log = AdminLog(
        admin_token_id=admin_token_id,
        action_type=action_type,
        entity_type=entity_type,
        entity_id=entity_id,
    )
    db.add(log)
    await db.flush()

