"""Клиент DSH web API (локальный 127.0.0.1:3080).

Эндпоинты эвристические — уточняются в docs/ON_SITE.md.
Токен из web.log, авто-повтор при 401.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from .config import get_settings
from .dsh_token import get_dsh_token, invalidate_dsh_token
from .logging import get_logger

log = get_logger(__name__)


class DSHClient:
    @property
    def base(self) -> str:
        return get_settings().dsh_web_base.rstrip("/")

    def _headers(self, force_token: bool = False) -> dict[str, str]:
        h = {
            "Accept": "application/json",
            "Host": f"{get_settings().dsh_web_host}:{get_settings().dsh_web_port}",
            "Origin": self.base,
            "sec-fetch-site": "same-origin",
        }
        token = get_dsh_token(force=force_token)
        if token:
            h["Authorization"] = f"Bearer {token}"
            h["Cookie"] = f"token={token}"
        return h

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        timeout: float = 30.0,
    ) -> httpx.Response:
        url = self.base + path
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            for attempt in range(2):
                headers = self._headers(force_token=(attempt > 0))
                r = await client.request(method, url, headers=headers, json=json_body)
                if r.status_code == 401 and attempt == 0:
                    invalidate_dsh_token()
                    continue
                return r
        raise RuntimeError("dsh request failed")

    async def health(self) -> bool:
        for path in ("/health", "/api/health", "/"):
            try:
                r = await self._request("GET", path, timeout=5.0)
                if r.status_code < 500:
                    return True
            except Exception:
                continue
        return False

    async def list_sessions(self) -> list[dict]:
        for path in (
            "/api/sessions",
            "/api/v1/sessions",
            "/api/agents",
            "/api/jobs",
        ):
            try:
                r = await self._request("GET", path)
                if r.status_code != 200:
                    continue
                data = r.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    items = (
                        data.get("sessions")
                        or data.get("agents")
                        or data.get("jobs")
                        or data.get("data")
                        or []
                    )
                    if items:
                        return items
            except Exception as e:
                log.debug("dsh_list_fail", path=path, error=str(e))
        return []

    async def get_messages(self, session_id: str) -> list[dict]:
        for path in (
            f"/api/sessions/{session_id}/messages",
            f"/api/sessions/{session_id}/history",
            f"/api/v1/sessions/{session_id}/messages",
        ):
            try:
                r = await self._request("GET", path)
                if r.status_code != 200:
                    continue
                data = r.json()
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    return data.get("messages") or data.get("history") or data.get("data") or []
            except Exception:
                continue
        return []

    async def post_action(
        self, session_id: str, action: str, payload: dict
    ) -> dict[str, Any]:
        path_map = {
            "send": f"/api/sessions/{session_id}/message",
            "interrupt": f"/api/sessions/{session_id}/interrupt",
            "abort": f"/api/sessions/{session_id}/abort",
            "approve": f"/api/sessions/{session_id}/approve",
            "deny": f"/api/sessions/{session_id}/deny",
            "change_model": f"/api/sessions/{session_id}/model",
            "delete": f"/api/sessions/{session_id}",
        }
        path = path_map.get(action)
        if not path:
            return {"ok": False, "error": f"unknown action {action}"}
        method = "DELETE" if action == "delete" else "POST"
        try:
            r = await self._request(method, path, json_body=payload or None)
            return {
                "ok": r.status_code < 400,
                "status": r.status_code,
                "body": r.text[:500],
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}


_dsh: Optional[DSHClient] = None


def get_dsh_client() -> DSHClient:
    global _dsh
    if _dsh is None:
        _dsh = DSHClient()
    return _dsh
