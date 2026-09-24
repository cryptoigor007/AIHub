"""Request-ID и access-логирование без секретов."""

from __future__ import annotations

import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ..common.logging import get_logger
from ..common.redact import redact_secrets

log = get_logger(__name__)


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        rid = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = rid
        t0 = time.perf_counter()
        response = await call_next(request)
        dt = (time.perf_counter() - t0) * 1000
        response.headers["X-Request-Id"] = rid
        # не логируем body / cookie
        path = redact_secrets(str(request.url.path))
        if path not in ("/health",) and not path.endswith("/ws"):
            log.info(
                "http_request",
                request_id=rid,
                method=request.method,
                path=path,
                status=response.status_code,
                ms=round(dt, 1),
            )
        return response
