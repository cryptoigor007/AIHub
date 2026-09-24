"""Прокси к dsh web с переписыванием заголовков."""

from __future__ import annotations

import asyncio
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from fastapi import Request, Response, WebSocket
from starlette.websockets import WebSocketDisconnect
from starlette.background import BackgroundTask

from ..common.config import get_settings
from ..common.dsh_token import get_dsh_token, invalidate_dsh_token
from ..common.logging import get_logger
from .security import rewrite_html_base

log = get_logger(__name__)

# Заголовки, которые не пробрасываем
HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "host",
    "content-length",
}


def _rewrite_request_headers(request: Request, target_base: str) -> dict[str, str]:
    """Переписывает Host, Origin, sec-fetch-site и добавляет токен."""
    settings = get_settings()
    headers: dict[str, str] = {}

    for k, v in request.headers.items():
        lk = k.lower()
        if lk in HOP_BY_HOP or lk == "cookie":
            continue
        headers[k] = v

    # Жёсткое переписывание по ТЗ
    headers["Host"] = f"{settings.dsh_web_host}:{settings.dsh_web_port}"
    headers["Origin"] = target_base
    headers["Referer"] = target_base + "/"

    # sec-fetch-site → same-origin (или удаляем)
    headers["sec-fetch-site"] = "same-origin"
    headers["sec-fetch-mode"] = "cors"
    headers["sec-fetch-dest"] = "empty"

    token = get_dsh_token()
    if token:
        # DSH обычно принимает токен через cookie или Authorization
        # Пробуем оба варианта; cookie предпочтительнее для web
        existing_cookie = request.headers.get("cookie", "")
        # Не пробрасываем aihub_session
        cookie_parts = [
            p for p in existing_cookie.split(";") if "aihub_session" not in p.lower()
        ]
        cookie_parts.append(f"token={token}")
        headers["Cookie"] = "; ".join(c.strip() for c in cookie_parts if c.strip())
        headers["Authorization"] = f"Bearer {token}"

    return headers


async def proxy_http(request: Request, path: str) -> Response:
    """Проксирует HTTP-запрос к dsh web."""
    settings = get_settings()
    base = settings.dsh_web_base
    # path уже без /dsh префикса
    url = urljoin(base + "/", path.lstrip("/"))
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = _rewrite_request_headers(request, base)
    body = await request.body()

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=False) as client:
        for attempt in range(2):
            try:
                resp = await client.request(
                    method=request.method,
                    url=url,
                    headers=headers,
                    content=body if body else None,
                )
            except httpx.ConnectError as e:
                log.error("dsh_proxy_connect_error", error=str(e), url=url)
                return Response(
                    content='{"error":"DSH offline"}',
                    status_code=503,
                    media_type="application/json",
                )
            except Exception as e:
                log.error("dsh_proxy_error", error=str(e), url=url)
                return Response(
                    content='{"error":"proxy error"}',
                    status_code=502,
                    media_type="application/json",
                )

            if resp.status_code == 401 and attempt == 0:
                log.info("dsh_401_retry", url=url)
                invalidate_dsh_token()
                token = get_dsh_token(force=True)
                if token:
                    headers["Cookie"] = f"token={token}"
                    headers["Authorization"] = f"Bearer {token}"
                    continue
            break

    # Собираем ответ
    out_headers = {
        k: v
        for k, v in resp.headers.items()
        if k.lower() not in HOP_BY_HOP and k.lower() != "set-cookie"
    }
    # Location: localhost → relative proxy path
    loc = out_headers.get("location") or out_headers.get("Location")
    if loc and ("127.0.0.1:3080" in loc or "localhost:3080" in loc):
        settings = get_settings()
        prefix = settings.secret_path.rstrip("/") + "/dsh"
        for host in (
            "https://127.0.0.1:3080",
            "http://127.0.0.1:3080",
            "https://localhost:3080",
            "http://localhost:3080",
            "//127.0.0.1:3080",
            "//localhost:3080",
        ):
            loc = loc.replace(host, prefix)
        out_headers["location"] = loc

    # Пробрасываем set-cookie от DSH, но не конфликтуем с aihub_session
    raw_cookies = resp.headers.get_list("set-cookie") if hasattr(resp.headers, "get_list") else []
    if not raw_cookies:
        sc = resp.headers.get("set-cookie")
        if sc:
            raw_cookies = [sc]

    content = resp.content
    ctype = (resp.headers.get("content-type") or "").lower()
    if "text/html" in ctype:
        settings = get_settings()
        secret = settings.secret_path.rstrip("/")
        prefix = f"{secret}/dsh"
        # если есть X-Forwarded или public — лучше relative; для WebApp достаточно path prefix
        content = rewrite_html_base(content, prefix)

    response = Response(
        content=content,
        status_code=resp.status_code,
        headers=out_headers,
        media_type=resp.headers.get("content-type"),
    )
    for c in raw_cookies:
        if "aihub_session" not in c.lower():
            response.headers.append("set-cookie", c)

    return response


async def proxy_websocket(websocket: WebSocket, path: str) -> None:
    """Проксирует WebSocket к dsh web."""
    settings = get_settings()
    base = settings.dsh_web_base
    # ws://...
    parsed = urlparse(base)
    ws_scheme = "ws" if parsed.scheme == "http" else "wss"
    target = f"{ws_scheme}://{settings.dsh_web_host}:{settings.dsh_web_port}/{path.lstrip('/')}"
    if websocket.url.query:
        target = f"{target}?{websocket.url.query}"

    token = get_dsh_token()
    extra_headers: dict[str, str] = {
        "Host": f"{settings.dsh_web_host}:{settings.dsh_web_port}",
        "Origin": base,
    }
    if token:
        extra_headers["Cookie"] = f"token={token}"
        extra_headers["Authorization"] = f"Bearer {token}"

    await websocket.accept()

    try:
        import websockets
        from websockets.asyncio.client import connect as ws_connect

        async with ws_connect(target, additional_headers=extra_headers) as upstream:
            async def client_to_upstream() -> None:
                try:
                    while True:
                        msg = await websocket.receive()
                        if msg["type"] == "websocket.disconnect":
                            break
                        if "text" in msg:
                            await upstream.send(msg["text"])
                        elif "bytes" in msg:
                            await upstream.send(msg["bytes"])
                except WebSocketDisconnect:
                    pass
                except Exception as e:
                    log.debug("ws_client_error", error=str(e))

            async def upstream_to_client() -> None:
                try:
                    async for message in upstream:
                        if isinstance(message, str):
                            await websocket.send_text(message)
                        else:
                            await websocket.send_bytes(message)
                except Exception as e:
                    log.debug("ws_upstream_error", error=str(e))

            await asyncio.gather(client_to_upstream(), upstream_to_client())
    except Exception as e:
        log.error("ws_proxy_error", error=str(e), target=target)
        try:
            await websocket.close(code=1011)
        except Exception:
            pass
