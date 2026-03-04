"""
Проверка прав админа для API: заголовок X-ADMIN-KEY и опционально telegram_id.
"""
from typing import Optional

from fastapi import Header, HTTPException, status

from src.core.config import get_settings


def require_admin_key(
    x_admin_key: Optional[str] = Header(None, alias="X-ADMIN-KEY"),
    authorization: Optional[str] = Header(None),
) -> None:
    """
    Проверяет, что запрос пришёл с известным ключом админа.
    Поддерживаются заголовки: X-ADMIN-KEY или Authorization: Bearer <key>.
    """
    settings = get_settings()
    key = x_admin_key or (authorization.replace("Bearer ", "").strip() if authorization else None)
    if not key or key != settings.admin_api_key:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid or missing admin key",
        )


def is_admin_telegram_id(telegram_id: int) -> bool:
    """Проверяет, входит ли telegram_id в список админов."""
    return telegram_id in get_settings().admin_telegram_ids
