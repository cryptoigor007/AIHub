"""Клиент OpenCode HTTP API: `opencode serve` V1 и V2.

Контракт:
- V1: /session, /event, /global/health
- V2: /api/session, /api/event, /api/info, /api/model, /api/project

Особенность V2: на неизвестные пути сервер отдаёт HTML web-UI с кодом 200,
поэтому JSON-ответы проверяются, а «вкус» API определяется по /api/info.

События SSE: GET /api/event (V2) / GET /event (V1).
Идеи UX/потоков (permissions, questions, children, diff) — из практики
экосистемы OpenCode (в т.ч. grinev/opencode-telegram-bot), реализация своя.
Код сторонних проектов не копируется.
"""

from __future__ import annotations

import time
from typing import Any, Optional

import httpx

from .config import get_settings
from .logging import get_logger

log = get_logger(__name__)

FLAVOR_TTL_SEC = 60.0


def _json_or_none(resp: httpx.Response) -> Any:
    """JSON ответа или None: HTML web-UI V2 (200) данными не считаем."""
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


class OpenCodeClient:
    def __init__(self) -> None:
        self._auth: Optional[tuple[str, str]] = None
        self._flavor = ""
        self._flavor_ts = 0.0
        settings = get_settings()
        user = getattr(settings, "opencode_server_username", None) or ""
        password = getattr(settings, "opencode_server_password", None) or ""
        if user or password:
            self._auth = (user or "opencode", password)

    @property
    def base(self) -> str:
        return get_settings().opencode_base.rstrip("/")

    def _client(self, timeout: float = 15.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=timeout,
            auth=self._auth,
            headers={"Accept": "application/json"},
        )

    def stream_client(self) -> httpx.AsyncClient:
        """Клиент для SSE: без таймаута, с той же авторизацией."""
        return httpx.AsyncClient(
            timeout=None,
            auth=self._auth,
            headers={"Accept": "text/event-stream"},
        )

    async def flavor(self) -> str:
        """'v2', если /api/info отдаёт JSON (opencode 2.x); иначе 'v1'."""
        now = time.time()
        if self._flavor and (now - self._flavor_ts) < FLAVOR_TTL_SEC:
            return self._flavor
        flavor = "v1"
        try:
            async with self._client(4.0) as c:
                data = _json_or_none(await c.get(self.base + "/api/info"))
                if isinstance(data, dict) and data.get("version"):
                    flavor = "v2"
        except Exception:
            pass
        self._flavor, self._flavor_ts = flavor, now
        log.debug("opencode_flavor", flavor=flavor, base=self.base)
        return flavor

    def _session_paths(self, suffix: str = "", *, v2: bool) -> list[str]:
        """V2-путь первым для v2-сервера, V1 — для остальных (плюс fallback)."""
        v2_path = f"/api/session{suffix}"
        v1_path = f"/session{suffix}"
        if v2:
            return [v2_path, v1_path]
        return [v1_path, v2_path]

    async def health(self) -> dict[str, Any]:
        async with self._client(5.0) as c:
            for path in ("/api/info", "/global/health", "/health"):
                try:
                    data = _json_or_none(await c.get(self.base + path))
                except Exception:
                    continue
                if isinstance(data, dict) and data:
                    return data
        return {"healthy": False}

    async def list_sessions(self) -> list[dict]:
        v2 = (await self.flavor()) == "v2"
        paths = self._session_paths("", v2=v2) + ["/sessions"]
        async with self._client() as c:
            for path in paths:
                try:
                    data = _json_or_none(await c.get(self.base + path))
                except Exception:
                    continue
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    out = data.get("sessions") or data.get("data")
                    if isinstance(out, list):
                        return out
        return []

    async def session_status_map(self) -> dict[str, Any]:
        async with self._client() as c:
            try:
                data = _json_or_none(await c.get(self.base + "/session/status"))
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {}

    async def get_session(self, session_id: str) -> Optional[dict]:
        v2 = (await self.flavor()) == "v2"
        async with self._client() as c:
            for path in self._session_paths(f"/{session_id}", v2=v2):
                try:
                    data = _json_or_none(await c.get(self.base + path))
                except Exception:
                    continue
                if isinstance(data, dict):
                    return data
        return None

    async def get_children(self, session_id: str) -> list[dict]:
        async with self._client() as c:
            try:
                data = _json_or_none(
                    await c.get(f"{self.base}/session/{session_id}/children")
                )
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    out = data.get("children") or data.get("sessions") or data.get("data")
                    if isinstance(out, list):
                        return out
            except Exception:
                pass
        return []

    async def list_messages(self, session_id: str) -> list[dict]:
        v2 = (await self.flavor()) == "v2"
        paths = self._session_paths(f"/{session_id}/message", v2=v2)
        paths.append(f"/session/{session_id}/messages")
        async with self._client() as c:
            for path in paths:
                try:
                    data = _json_or_none(await c.get(self.base + path))
                except Exception:
                    continue
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    out = data.get("messages") or data.get("data")
                    if isinstance(out, list):
                        return out
        return []

    async def create_session(
        self, title: Optional[str] = None, parent_id: Optional[str] = None
    ) -> dict:
        v2 = (await self.flavor()) == "v2"
        body: dict[str, Any] = {}
        if title:
            body["title"] = title
        if parent_id and not v2:
            body["parentID"] = parent_id  # V2 create не принимает parentID
        async with self._client() as c:
            for path in self._session_paths("", v2=v2):
                try:
                    r = await c.post(self.base + path, json=body)
                except Exception:
                    continue
                data = _json_or_none(r)
                if isinstance(data, dict):
                    return data
                if r.status_code < 400 and not v2:
                    return {"ok": True, "status": r.status_code}
        raise RuntimeError("create_session failed")

    async def delete_session(self, session_id: str) -> bool:
        v2 = (await self.flavor()) == "v2"
        async with self._client() as c:
            for path in self._session_paths(f"/{session_id}", v2=v2):
                try:
                    r = await c.delete(self.base + path)
                except Exception:
                    continue
                if r.status_code < 400:
                    return True
        return False

    async def rename_session(self, session_id: str, title: str) -> dict:
        v2 = (await self.flavor()) == "v2"
        async with self._client() as c:
            for path in self._session_paths(f"/{session_id}", v2=v2):
                try:
                    r = await c.patch(self.base + path, json={"title": title})
                except Exception:
                    continue
                data = _json_or_none(r)
                if isinstance(data, dict):
                    return data
                if r.status_code < 400 and not v2:
                    return {"ok": True}
        raise RuntimeError("rename_session failed")

    async def prompt(self, session_id: str, text: str, **extra: Any) -> dict:
        """Отправить текстовый промпт в сессию."""
        v2 = (await self.flavor()) == "v2"
        async with self._client(timeout=60.0) as c:
            if v2:
                try:
                    r = await c.post(
                        f"{self.base}/api/session/{session_id}/prompt",
                        json={"text": text, **extra},
                    )
                    data = _json_or_none(r)
                    if isinstance(data, dict):
                        return data
                    if r.status_code < 400:
                        return {"ok": True, "status": r.status_code}
                except Exception:
                    pass
            body: dict[str, Any] = {
                "parts": [{"type": "text", "text": text}],
                **extra,
            }
            # совместимость со старыми телами
            alt_bodies = [
                body,
                {"message": text},
                {"text": text},
                {"prompt": text},
            ]
            for path in (
                f"/session/{session_id}/message",
                f"/session/{session_id}/prompt",
                f"/session/{session_id}/chat",
            ):
                for b in alt_bodies:
                    try:
                        r = await c.post(self.base + path, json=b)
                        if r.status_code < 400:
                            try:
                                return r.json()
                            except Exception:
                                return {"ok": True, "status": r.status_code}
                    except Exception:
                        continue
        return {"ok": False, "error": "prompt failed"}

    async def abort(self, session_id: str) -> dict:
        v2 = (await self.flavor()) == "v2"
        async with self._client() as c:
            if v2:
                try:
                    r = await c.post(f"{self.base}/api/session/{session_id}/interrupt")
                    if r.status_code < 400:
                        return {"ok": True, "status": r.status_code}
                except Exception:
                    pass
            for path in (
                f"/session/{session_id}/abort",
                f"/session/{session_id}/interrupt",
                f"/session/{session_id}/cancel",
            ):
                try:
                    r = await c.post(self.base + path, json={})
                    if r.status_code < 400:
                        return {"ok": True, "status": r.status_code}
                except Exception:
                    continue
        return {"ok": False, "error": "abort failed"}

    async def reply_permission(
        self, session_id: str, permission_id: str, response: str
    ) -> dict:
        """response: once | always | reject"""
        async with self._client() as c:
            for path in (
                f"/session/{session_id}/permissions/{permission_id}",
                f"/permission/{permission_id}",
                f"/session/{session_id}/permission",
            ):
                for body in (
                    {"response": response},
                    {"action": response},
                    {"permissionID": permission_id, "response": response},
                ):
                    try:
                        r = await c.post(self.base + path, json=body)
                        if r.status_code < 400:
                            return {"ok": True}
                    except Exception:
                        continue
        return {"ok": False, "error": "permission reply failed"}

    async def reply_question(
        self, session_id: str, question_id: str, answer: Any
    ) -> dict:
        async with self._client() as c:
            for path in (
                f"/session/{session_id}/question/{question_id}",
                f"/question/{question_id}/reply",
                f"/session/{session_id}/question",
            ):
                for body in (
                    {"answer": answer},
                    {"text": answer} if isinstance(answer, str) else {"answer": answer},
                    {"questionID": question_id, "answer": answer},
                ):
                    try:
                        r = await c.post(self.base + path, json=body)
                        if r.status_code < 400:
                            return {"ok": True}
                    except Exception:
                        continue
        return {"ok": False, "error": "question reply failed"}

    async def list_projects(self) -> list[dict]:
        v2 = (await self.flavor()) == "v2"
        paths = (
            ["/api/project", "/api/projects", "/project", "/projects"]
            if v2
            else ["/project", "/projects", "/api/project", "/api/projects"]
        )
        async with self._client() as c:
            for path in paths:
                try:
                    data = _json_or_none(await c.get(self.base + path))
                except Exception:
                    continue
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    out = data.get("projects") or data.get("data")
                    if isinstance(out, list):
                        return out
        return []

    async def fork_session(
        self, session_id: str, message_id: Optional[str] = None
    ) -> dict:
        v2 = (await self.flavor()) == "v2"
        async with self._client() as c:
            if v2:
                body = {"before": message_id} if message_id else {}
                try:
                    r = await c.post(
                        f"{self.base}/api/session/{session_id}/fork", json=body
                    )
                    data = _json_or_none(r)
                    if isinstance(data, dict):
                        return {"ok": True, "session": data}
                    if r.status_code < 400:
                        return {"ok": True}
                except Exception:
                    pass
            for path in (
                f"/session/{session_id}/fork",
                f"/session/{session_id}/branch",
            ):
                try:
                    r = await c.post(self.base + path, json={"messageID": message_id} if message_id else None)
                    if r.status_code < 400:
                        try:
                            return {"ok": True, "session": r.json()}
                        except Exception:
                            return {"ok": True}
                except Exception:
                    continue
        return {"ok": False, "error": "fork not supported"}

    async def revert_session(self, session_id: str, message_id: str) -> dict:
        async with self._client() as c:
            for path in (
                f"/session/{session_id}/revert",
                f"/session/{session_id}/message/{message_id}/revert",
            ):
                try:
                    r = await c.post(self.base + path, json={"messageID": message_id})
                    if r.status_code < 400:
                        return {"ok": True}
                except Exception:
                    continue
        return {"ok": False, "error": "revert not supported"}

    async def list_models(self) -> list[dict]:
        v2 = (await self.flavor()) == "v2"
        paths = (
            ["/api/model", "/provider", "/model", "/models"]
            if v2
            else ["/provider", "/model", "/models", "/api/models", "/api/model"]
        )
        async with self._client() as c:
            for path in paths:
                try:
                    data = _json_or_none(await c.get(self.base + path))
                except Exception:
                    continue
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    out = (
                        data.get("models")
                        or data.get("providers")
                        or data.get("data")
                    )
                    if isinstance(out, list):
                        return out
        return []

    async def set_model(self, session_id: str, model: Any) -> dict:
        """Сменить модель сессии. V2: POST /api/session/{id}/model, V1: PATCH /session/{id}."""
        v2 = (await self.flavor()) == "v2"
        async with self._client() as c:
            if v2:
                ref: Any = model
                if isinstance(model, str):
                    if "/" in model:
                        provider, _, name = model.partition("/")
                        ref = {"providerID": provider, "id": name}
                    else:
                        ref = {"id": model, "providerID": ""}
                try:
                    r = await c.post(
                        f"{self.base}/api/session/{session_id}/model",
                        json={"model": ref},
                    )
                    if r.status_code < 400:
                        return {"ok": True, "status": r.status_code, "body": r.text[:200]}
                    return {"ok": False, "status": r.status_code, "body": r.text[:200]}
                except Exception as e:
                    return {"ok": False, "error": str(e)}
            try:
                r = await c.patch(
                    f"{self.base}/session/{session_id}", json={"model": model}
                )
                return {
                    "ok": r.status_code < 400,
                    "status": r.status_code,
                    "body": r.text[:300],
                }
            except Exception as e:
                return {"ok": False, "error": str(e)}

    def event_urls(self) -> list[str]:
        """Приоритет SSE-эндпоинтов: V2 /api/event, затем V1 /event."""
        b = self.base
        return [
            f"{b}/api/event",
            f"{b}/event",
            f"{b}/global/event",
        ]


_client: Optional[OpenCodeClient] = None


def get_opencode_client() -> OpenCodeClient:
    global _client
    if _client is None:
        _client = OpenCodeClient()
    return _client
