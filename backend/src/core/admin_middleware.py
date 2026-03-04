from __future__ import annotations

from typing import Callable, Awaitable

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from src.core.admin_auth import JWT_COOKIE_NAME, decode_admin_jwt
from src.core.config import get_settings


async def admin_jwt_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    """
    Проверка JWT и ограничения по IP для /database/api/*.
    /database/api/login пропускается без проверки.
    """
    path = request.url.path
    if path.startswith("/database/api") and not path.startswith("/database/api/login"):
        # Ограничение по IP, если настроено.
        settings = get_settings()
        if settings.admin_allowed_ips:
            allowed = {ip.strip() for ip in settings.admin_allowed_ips.split(",") if ip.strip()}
            client_ip = request.client.host if request.client else ""
            if client_ip not in allowed:
                return JSONResponse(
                    status_code=403,
                    content={"detail": "IP not allowed"},
                )

        # Проверка JWT в cookie.
        cookie = request.cookies.get(JWT_COOKIE_NAME)
        if not cookie:
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )
        # Бросает 401 при ошибке/просрочке.
        try:
            admin_token_id, created_by = decode_admin_jwt(cookie)
            # Сохраняем контекст для последующего использования в роутерах.
            request.state.admin_token_id = admin_token_id
            request.state.admin_created_by = created_by
        except Exception:
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated"},
            )

    response = await call_next(request)
    return response

