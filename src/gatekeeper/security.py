"""Заголовки безопасности и вспомогательные утилиты."""

from __future__ import annotations

import re
from typing import Callable

try:
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.requests import Request
    from starlette.responses import Response
except ImportError:  # unit-тесты без starlette
    BaseHTTPMiddleware = object  # type: ignore
    Request = object  # type: ignore
    Response = object  # type: ignore


class SecurityHeadersMiddleware(BaseHTTPMiddleware):  # type: ignore[misc]
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        # Не ставим CSP жёстко — DSH UI тянет свои ресурсы через proxy
        return response



# re-export
from ..common.redact import redact_secrets  # noqa: E402



def rewrite_html_base(html: bytes, public_prefix: str) -> bytes:
    """Подмена абсолютных ссылок localhost/127.0.0.1:3080 → public_prefix (/p/xxx/dsh).

    Покрывает http(s), ws(s), protocol-relative //, типичные атрибуты href/src/action.
    """
    try:
        text = html.decode("utf-8")
    except UnicodeDecodeError:
        return html

    prefix = public_prefix.rstrip("/")
    # Порядок важен: сначала более специфичные (ws/http + host), потом protocol-relative
    hosts = ("127.0.0.1:3080", "localhost:3080", "127.0.0.1:3080/", "localhost:3080/")
    pairs: list[tuple[str, str]] = []
    for host in ("127.0.0.1:3080", "localhost:3080"):
        pairs.extend(
            [
                (f"https://{host}", prefix),
                (f"http://{host}", prefix),
                (f"wss://{host}", prefix),  # browser will use same origin scheme via relative
                (f"ws://{host}", prefix),
                (f"//{host}", prefix),
            ]
        )
    for a, b in pairs:
        text = text.replace(a, b)

    # JSON-escaped variants occasionally embedded in inline scripts
    for host in ("127.0.0.1:3080", "localhost:3080"):
        text = text.replace(f"http:\\/\\/{host}", prefix.replace("/", "\\/"))
        text = text.replace(f"ws:\\/\\/{host}", prefix.replace("/", "\\/"))

    return text.encode("utf-8")
