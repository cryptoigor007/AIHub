"""Сервис агрегатора: DSH (poll) + OpenCode (HTTP + SSE /events), единый WS."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

from ..common.config import get_settings
from ..common.circuit import dsh_circuit, opencode_circuit
from ..common.logging import get_logger
from ..common.models import (
    AgentState,
    AgentStatus,
    EventType,
    SystemType,
    Tokens,
)

log = get_logger(__name__)

STATUS_MAP = {
    "running": AgentStatus.RUNNING,
    "active": AgentStatus.RUNNING,
    "in_progress": AgentStatus.RUNNING,
    "busy": AgentStatus.RUNNING,
    "working": AgentStatus.RUNNING,
    "waiting": AgentStatus.WAITING,
    "pending": AgentStatus.WAITING,
    "idle": AgentStatus.WAITING,
    "paused": AgentStatus.WAITING,
    "completed": AgentStatus.COMPLETED,
    "done": AgentStatus.COMPLETED,
    "success": AgentStatus.COMPLETED,
    "failed": AgentStatus.FAILED,
    "error": AgentStatus.FAILED,
    "aborted": AgentStatus.FAILED,
    "cancelled": AgentStatus.FAILED,
}


class AggregatorService:
    def __init__(self, notifier: Any = None) -> None:
        self._agents: dict[str, AgentState] = {}
        self._subscribers: list[asyncio.Queue] = []
        self._lock = asyncio.Lock()
        self._tasks: list[asyncio.Task] = []
        self._running = False
        self.dsh_online = False
        self.opencode_online = False
        self._notifier = notifier
        self._last_notify: dict[str, float] = {}
        # Кэш истории по agent_id (последние сообщения)
        self._history: dict[str, list[dict]] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._load_snapshot()
        self._tasks = [
            asyncio.create_task(self._poll_dsh_loop(), name="poll_dsh"),
            asyncio.create_task(self._poll_opencode_loop(), name="poll_opencode"),
            asyncio.create_task(self._opencode_sse_loop(), name="opencode_sse"),
            asyncio.create_task(self._snapshot_loop(), name="snapshot"),
            asyncio.create_task(self._cleanup_loop(), name="cleanup"),
        ]
        log.info("aggregator_service_started")

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
        self._tasks.clear()
        self._save_snapshot()
        log.info("aggregator_service_stopped")

    def _snapshot_path(self) -> Path:
        return get_settings().data_dir / "state.json"

    def _load_snapshot(self) -> None:
        path = self._snapshot_path()
        if not path.exists():
            return
        try:
            text = path.read_text(encoding="utf-8").strip()
            if not text:
                return  # пустой файл после ensure_dirs — не ошибка
            data = json.loads(text)
            for item in data.get("agents", []):
                try:
                    agent = AgentState.model_validate(item)
                    self._agents[agent.id] = agent
                except Exception:
                    continue
            log.info("snapshot_loaded", count=len(self._agents))
        except Exception as e:
            log.warning("snapshot_load_error", error=str(e))

    def _save_snapshot(self) -> None:
        path = self._snapshot_path()
        try:
            payload = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "agents": [a.to_dict() for a in self._agents.values()],
            }
            text = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(path)  # atomic on same filesystem
        except Exception as e:
            log.warning("snapshot_save_error", error=str(e))


    async def _cleanup_loop(self) -> None:
        """Убирает из памяти completed/failed старше 24ч (снимок на диск сохраняет)."""
        while self._running:
            await asyncio.sleep(600)
            cutoff = datetime.now(timezone.utc).timestamp() - 86400
            async with self._lock:
                drop = []
                for aid, a in self._agents.items():
                    if a.status in (AgentStatus.COMPLETED, AgentStatus.FAILED):
                        ts = a.updated_at.timestamp() if a.updated_at else 0
                        if ts and ts < cutoff:
                            drop.append(aid)
                for aid in drop:
                    self._agents.pop(aid, None)
                    self._history.pop(aid, None)
            if drop:
                log.info("cleanup_stale_agents", count=len(drop))

    async def _snapshot_loop(self) -> None:
        while self._running:
            await asyncio.sleep(30)
            self._save_snapshot()

    # ─── DSH ───────────────────────────────────────────────

    async def _poll_dsh_loop(self) -> None:
        while self._running:
            if dsh_circuit.is_open:
                await self._set_dsh_online(False)
                await asyncio.sleep(5)
                continue
            try:
                await self._poll_dsh()
                dsh_circuit.record_success()
            except Exception as e:
                log.debug("poll_dsh_error", error=str(e))
                dsh_circuit.record_failure()
                await self._set_dsh_online(False)
            await asyncio.sleep(3)

    async def _poll_dsh(self) -> None:
        from ..common.dsh_client import get_dsh_client
        client = get_dsh_client()
        online = await client.health()
        if online:
            try:
                items = await client.list_sessions()
                for raw in items:
                    if isinstance(raw, dict):
                        await self._upsert_from_raw(raw, SystemType.DSH, endpoint="/api/sessions")
            except Exception as e:
                log.debug("dsh_list_error", error=str(e))
        await self._set_dsh_online(online)

    async def _set_dsh_online(self, online: bool) -> None:
        if self.dsh_online == online:
            return
        self.dsh_online = online
        await self._broadcast(
            {
                "type": EventType.SYSTEM_ONLINE.value
                if online
                else EventType.SYSTEM_OFFLINE.value,
                "system": SystemType.DSH.value,
            }
        )

    # ─── OpenCode HTTP poll ────────────────────────────────

    async def _poll_opencode_loop(self) -> None:
        while self._running:
            if opencode_circuit.is_open:
                await self._set_opencode_online(False)
                await asyncio.sleep(5)
                continue
            try:
                await self._poll_opencode()
                opencode_circuit.record_success()
            except Exception as e:
                log.debug("poll_opencode_error", error=str(e))
                opencode_circuit.record_failure()
                await self._set_opencode_online(False)
            await asyncio.sleep(5)

    async def _poll_opencode(self) -> None:
        from ..common.opencode_client import get_opencode_client
        client = get_opencode_client()
        health = await client.health()
        online = bool(health.get("healthy") or health.get("version"))
        if not online:
            # fallback: list sessions
            try:
                sessions = await client.list_sessions()
                online = True
                status_map = await client.session_status_map()
                for raw in sessions:
                    if not isinstance(raw, dict):
                        continue
                    sid = str(raw.get("id") or "")
                    if sid and sid in status_map:
                        st = status_map[sid]
                        if isinstance(st, dict):
                            raw = {**raw, "status": st.get("status") or st.get("state") or raw.get("status")}
                        elif isinstance(st, str):
                            raw = {**raw, "status": st}
                    await self._upsert_from_raw(raw, SystemType.OPENCODE, endpoint="/session")
                    # children / subagents
                    try:
                        kids = await client.get_children(sid)
                        for kid in kids:
                            if isinstance(kid, dict):
                                kid = {**kid, "parent": sid, "parent_id": sid}
                                await self._upsert_from_raw(kid, SystemType.OPENCODE, endpoint="/children")
                    except Exception:
                        pass
            except Exception:
                online = False
        else:
            try:
                sessions = await client.list_sessions()
                status_map = await client.session_status_map()
                for raw in sessions:
                    if not isinstance(raw, dict):
                        continue
                    sid = str(raw.get("id") or "")
                    if sid and sid in status_map:
                        st = status_map[sid]
                        if isinstance(st, dict):
                            raw = {**raw, "status": st.get("status") or raw.get("status")}
                        elif isinstance(st, str):
                            raw = {**raw, "status": st}
                    # map idle/active → our statuses
                    st_raw = str(raw.get("status") or "").lower()
                    if st_raw == "idle":
                        raw["status"] = "waiting" if raw.get("pending") else "completed"
                    elif st_raw == "active":
                        raw["status"] = "running"
                    await self._upsert_from_raw(raw, SystemType.OPENCODE, endpoint="/session")
                    if sid:
                        try:
                            kids = await client.get_children(sid)
                            for kid in kids:
                                if isinstance(kid, dict):
                                    kid = {**kid, "parent_id": sid, "parent": sid}
                                    await self._upsert_from_raw(kid, SystemType.OPENCODE, endpoint="/children")
                        except Exception:
                            pass
            except Exception as e:
                log.debug("opencode_list_error", error=str(e))
        await self._set_opencode_online(online)

    async def _set_opencode_online(self, online: bool) -> None:
        if self.opencode_online == online:
            return
        self.opencode_online = online
        await self._broadcast(
            {
                "type": EventType.SYSTEM_ONLINE.value
                if online
                else EventType.SYSTEM_OFFLINE.value,
                "system": SystemType.OPENCODE.value,
            }
        )

    # ─── OpenCode SSE ──────────────────────────────────────

    async def _opencode_sse_loop(self) -> None:
        """Подписка на SSE (V2 /api/event, V1 /event). Реконнект с backoff."""
        settings = get_settings()
        from ..common.opencode_client import get_opencode_client

        oc = get_opencode_client()
        urls = oc.event_urls()
        backoff = 2.0
        while self._running:
            connected = False
            for url in urls:
                try:
                    async with oc.stream_client() as client:
                        async with client.stream("GET", url) as resp:
                            content_type = (resp.headers.get("content-type") or "").lower()
                            # V2 на неизвестные пути отдаёт HTML 200 — это не SSE
                            if resp.status_code != 200 or "text/event-stream" not in content_type:
                                continue
                            connected = True
                            backoff = 2.0
                            await self._set_opencode_online(True)
                            log.info("opencode_sse_connected", url=url)
                            buffer = ""
                            async for chunk in resp.aiter_text():
                                if not self._running:
                                    return
                                buffer += chunk
                                while "\n\n" in buffer:
                                    block, buffer = buffer.split("\n\n", 1)
                                    await self._handle_sse_block(block)
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    log.debug("opencode_sse_path_failed", url=url, error=str(e))
                    continue
                if connected:
                    break
            if not connected:
                await self._set_opencode_online(False)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 1.5, 30.0)

    async def _handle_sse_block(self, block: str) -> None:
        event_type = "message"
        data_lines: list[str] = []
        for line in block.splitlines():
            if line.startswith("event:"):
                event_type = line[6:].strip()
            elif line.startswith("data:"):
                data_lines.append(line[5:].strip())
        if not data_lines:
            return
        raw = "\n".join(data_lines)
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        await self._ingest_sse_event(event_type, payload)

    async def _ingest_sse_event(self, event_type: str, payload: Any) -> None:
        """Нормализация SSE OpenCode (session.*, message.*, permission.*, question.*)."""
        # Официальный формат: { "type": "session.status", "properties": {...} }
        if isinstance(payload, dict) and "properties" in payload and "type" in payload:
            event_type = str(payload.get("type") or event_type)
            payload = payload.get("properties") or {}
        if isinstance(payload, dict) and payload.get("type") and not payload.get("id"):
            # type at top level with nested props
            if "properties" in payload:
                event_type = str(payload.get("type") or event_type)
                payload = payload.get("properties") or {}

        if not isinstance(payload, dict):
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        await self._upsert_from_raw(item, SystemType.OPENCODE)
            return

        et = (event_type or "").lower()
        # server.* — служебные
        if et.startswith("server."):
            return

        # status mapping
        status_hint = None
        if "idle" in et or et.endswith(".idle"):
            status_hint = "completed"
        elif "error" in et:
            status_hint = "failed"
        elif "status" in et:
            st = str(payload.get("status") or "").lower()
            if st == "active":
                status_hint = "running"
            elif st == "idle":
                status_hint = "waiting"
            elif st == "error":
                status_hint = "failed"
        elif "permission" in et or "question" in et:
            status_hint = "waiting"
        elif any(x in et for x in ("message", "part", "tool", "updated", "created")):
            status_hint = "running"

        inner = payload.get("session") or payload.get("data") or payload.get("agent") or payload
        if isinstance(inner, dict):
            if status_hint and "status" not in inner:
                inner["status"] = status_hint
            # sessionID → id
            if not inner.get("id"):
                sid = payload.get("sessionID") or payload.get("session_id") or inner.get("sessionID")
                if sid:
                    inner["id"] = sid
            # diff / files
            if "diff" in et or payload.get("diff") or payload.get("files"):
                files = payload.get("diff") or payload.get("files") or payload.get("changed")
                inner.setdefault("meta", {})
                if isinstance(inner.get("meta"), dict):
                    pass
                inner["changed_files"] = files
            # permission / question ids
            if "permission" in et:
                inner["pending_permission"] = payload.get("id") or payload.get("permissionID")
                inner["permission_info"] = payload
            if "question" in et:
                inner["pending_question"] = payload.get("id") or payload.get("questionID")
                inner["question_info"] = payload
            await self._upsert_from_raw(inner, SystemType.OPENCODE)

            # История сообщений
            msg = payload.get("message") or payload.get("part") or inner.get("message")
            sid = str(inner.get("id") or inner.get("sessionID") or inner.get("session_id") or "")
            if msg and sid:
                aid = f"opencode:{sid}"
                hist = self._history.setdefault(aid, [])
                hist.append({"ts": datetime.now(timezone.utc).isoformat(), "message": msg})
                if len(hist) > 100:
                    self._history[aid] = hist[-100:]

    # ─── Нормализация ──────────────────────────────────────

    async def _ingest_list(self, data: Any, system: SystemType, endpoint: str) -> None:
        items: list = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = (
                data.get("sessions")
                or data.get("agents")
                or data.get("jobs")
                or data.get("data")
                or data.get("items")
                or []
            )
            # одиночный объект
            if not items and ("id" in data or "sessionID" in data):
                items = [data]
        for raw in items:
            if isinstance(raw, dict):
                await self._upsert_from_raw(raw, system, endpoint=endpoint)

    async def _upsert_from_raw(
        self, raw: dict, system: SystemType, endpoint: str = ""
    ) -> None:
        prefix = system.value
        aid_raw = str(
            raw.get("id")
            or raw.get("session_id")
            or raw.get("sessionID")
            or raw.get("job_id")
            or raw.get("jobId")
            or ""
        )
        if not aid_raw:
            return
        aid = f"{prefix}:{aid_raw}"

        status_raw = str(
            raw.get("status") or raw.get("state") or raw.get("phase") or "unknown"
        ).lower()
        status = STATUS_MAP.get(status_raw, AgentStatus.UNKNOWN)

        parent = raw.get("parent_id") or raw.get("parent") or raw.get("parentId")
        parent_id = f"{prefix}:{parent}" if parent else None

        usage = raw.get("usage") or raw.get("tokens") or {}
        tokens = None
        if isinstance(usage, dict) and usage:
            tokens = Tokens(
                input=int(usage.get("input") or usage.get("prompt") or usage.get("input_tokens") or 0),
                output=int(usage.get("output") or usage.get("completion") or usage.get("output_tokens") or 0),
                total=int(usage.get("total") or usage.get("total_tokens") or 0),
            )
        elif "input_tokens" in raw or "tokens" in raw:
            t = raw.get("tokens") if isinstance(raw.get("tokens"), dict) else {}
            tokens = Tokens(
                input=int(raw.get("input_tokens") or t.get("input", 0) or 0),
                output=int(raw.get("output_tokens") or t.get("output", 0) or 0),
                total=int(raw.get("total_tokens") or t.get("total", 0) or 0),
            )

        cost = raw.get("cost")
        if cost is None and isinstance(usage, dict):
            cost = usage.get("cost")

        title = str(
            raw.get("title")
            or raw.get("name")
            or raw.get("prompt", "")[:80]
            or raw.get("directory")
            or aid_raw
        )
        project = (
            raw.get("project")
            or raw.get("cwd")
            or raw.get("directory")
            or raw.get("path")
            or raw.get("workdir")
        )
        last_step = (
            raw.get("last_step")
            or raw.get("current_action")
            or raw.get("step")
            or raw.get("lastMessage")
            or raw.get("current")
            or raw.get("tool")
        )

        agent = AgentState(
            id=aid,
            system=system,
            parent_id=parent_id,
            title=title,
            project=str(project) if project else None,
            status=status,
            last_step=str(last_step) if last_step else None,
            tokens=tokens,
            cost=float(cost) if cost is not None else None,
            started_at=_parse_dt(raw.get("started_at") or raw.get("created_at") or raw.get("created")),
            updated_at=datetime.now(timezone.utc),
            meta={
                "endpoint": endpoint,
                "raw_keys": list(raw.keys())[:30],
                "model": raw.get("model") or raw.get("modelID") or raw.get("model_id"),
                "variant": raw.get("variant"),
                "context": raw.get("context") or raw.get("usage"),
                "changed_files": raw.get("changed_files") or raw.get("diff") or raw.get("files"),
                "pending_permission": raw.get("pending_permission"),
                "pending_question": raw.get("pending_question"),
                "permission_info": raw.get("permission_info"),
                "question_info": raw.get("question_info"),
            },
        )
        await self._upsert(agent)

    async def _upsert(self, agent: AgentState) -> None:
        async with self._lock:
            old = self._agents.get(agent.id)
            self._agents[agent.id] = agent

        if self._notifier and old and old.status != agent.status:
            if agent.status == AgentStatus.COMPLETED:
                await self._maybe_notify("completed", agent)
            elif agent.status == AgentStatus.FAILED:
                await self._maybe_notify("failed", agent)
            elif agent.status == AgentStatus.WAITING:
                await self._maybe_notify("waiting", agent)

        # FTS индекс
        try:
            from ..common.fts import get_fts
            get_fts().upsert(
                agent.id,
                title=agent.title or "",
                project=agent.project or "",
                last_step=agent.last_step or "",
                body=" ".join(
                    str(h.get("message", ""))[:200]
                    for h in self._history.get(agent.id, [])[-10:]
                ),
            )
        except Exception:
            pass

        await self._broadcast(
            {"type": EventType.STATE_UPDATE.value, "agent": agent.to_dict()}
        )

    async def _maybe_notify(self, kind: str, agent: AgentState) -> None:
        import time

        key = f"{kind}:{agent.id}"
        now = time.time()
        if now - self._last_notify.get(key, 0) < 60:
            return
        self._last_notify[key] = now
        if self._notifier:
            await self._notifier.notify_agent(kind, agent)

    async def _broadcast(self, event: dict) -> None:
        event.setdefault("ts", datetime.now(timezone.utc).isoformat())
        dead = []
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except (asyncio.QueueFull, Exception):
                dead.append(q)
        for q in dead:
            if q in self._subscribers:
                self._subscribers.remove(q)

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        if q in self._subscribers:
            self._subscribers.remove(q)

    def get_agents(
        self,
        system: Optional[str] = None,
        status: Optional[str] = None,
        active_only: bool = False,
    ) -> list[AgentState]:
        result = list(self._agents.values())
        if system:
            result = [a for a in result if a.system.value == system]
        if status:
            result = [a for a in result if a.status.value == status]
        if active_only:
            result = [
                a
                for a in result
                if a.status in (AgentStatus.RUNNING, AgentStatus.WAITING)
            ]
        result.sort(key=lambda a: a.updated_at, reverse=True)
        return result

    def get_agent(self, agent_id: str) -> Optional[AgentState]:
        return self._agents.get(agent_id)

    def get_history(self, agent_id: str) -> list[dict]:
        return list(self._history.get(agent_id, []))

    def get_snapshot(self) -> dict:
        return {
            "type": EventType.SNAPSHOT.value,
            "agents": [a.to_dict() for a in self.get_agents()],
            "dsh_online": self.dsh_online,
            "opencode_online": self.opencode_online,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

    def list_sessions(self, query: Optional[str] = None) -> list[dict]:
        agents = self.search(query) if query else self.get_agents()
        groups: dict[str, list] = {}
        for a in agents:
            key = a.project or "(без проекта)"
            groups.setdefault(key, []).append(a.to_dict())
        return [{"project": k, "sessions": v} for k, v in sorted(groups.items())]

    def search(self, query: str) -> list[AgentState]:
        """FTS + fallback по title/project."""
        if not query:
            return self.get_agents()
        ids = []
        try:
            from ..common.fts import get_fts
            ids = get_fts().search(query)
        except Exception:
            ids = []
        if ids:
            result = [self._agents[i] for i in ids if i in self._agents]
            if result:
                return result
        q = query.lower()
        return [
            a
            for a in self.get_agents()
            if q in (a.title or "").lower()
            or q in (a.project or "").lower()
            or q in a.id.lower()
        ]

    async def fetch_remote_history(self, agent_id: str) -> list[dict]:
        """История с upstream; кэш + нормализация."""
        agent = self.get_agent(agent_id)
        cached = self.get_history(agent_id)
        if not agent:
            return cached
        raw_id = agent_id.split(":", 1)[-1]
        items: list = []
        try:
            if agent.system == SystemType.DSH:
                from ..common.dsh_client import get_dsh_client
                items = await get_dsh_client().get_messages(raw_id)
            else:
                from ..common.opencode_client import get_opencode_client
                items = await get_opencode_client().list_messages(raw_id)
        except Exception as e:
            log.debug("history_fetch_error", error=str(e), agent_id=agent_id)
            return cached

        hist = []
        for it in items:
            if not isinstance(it, dict):
                hist.append({"message": str(it)[:500]})
                continue
            content = (
                it.get("content")
                or it.get("text")
                or it.get("message")
                or it.get("part")
            )
            if isinstance(content, list):
                # parts array
                texts = []
                for p in content:
                    if isinstance(p, dict):
                        texts.append(str(p.get("text") or p.get("content") or ""))
                    else:
                        texts.append(str(p))
                content = "\n".join(t for t in texts if t)
            hist.append(
                {
                    "ts": it.get("created_at") or it.get("time") or it.get("ts"),
                    "role": it.get("role") or it.get("type"),
                    "message": (content if content is not None else str(it)[:300]),
                }
            )
        if hist:
            self._history[agent_id] = hist[-100:]
            return hist
        return cached

    async def perform_action(

        self, agent_id: str, action: str, payload: dict
    ) -> dict:
        agent = self.get_agent(agent_id)
        if not agent:
            return {"ok": False, "error": "Агент не найден"}

        # Дорогие действия — вызывающая сторона должна подтвердить (UI),
        # здесь помечаем requires_confirm для аудита
        expensive = action in ("change_model", "new_session", "delete", "rollback", "bulk")
        if expensive and not payload.get("_confirmed"):
            return {
                "ok": False,
                "error": "requires_confirm",
                "message": _confirm_message(action, agent, payload),
            }

        if agent.system == SystemType.DSH:
            return await self._action_dsh(agent, action, payload)
        return await self._action_opencode(agent, action, payload)

    async def _action_dsh(self, agent: AgentState, action: str, payload: dict) -> dict:
        from ..common.dsh_client import get_dsh_client
        client = get_dsh_client()
        raw_id = agent.id.replace("dsh:", "", 1)
        body = {k: v for k, v in payload.items() if not k.startswith("_")}
        if action == "new_session":
            # best-effort create
            try:
                r = await client._request("POST", "/api/sessions", json_body=body)
                return {"ok": r.status_code < 400, "status": r.status_code, "body": r.text[:500]}
            except Exception as e:
                return {"ok": False, "error": str(e)}
        return await client.post_action(raw_id, action, body)

    async def _action_opencode(
        self, agent: AgentState, action: str, payload: dict
    ) -> dict:
        from ..common.opencode_client import get_opencode_client
        client = get_opencode_client()
        raw_id = agent.id.replace("opencode:", "", 1)
        body = {k: v for k, v in payload.items() if not k.startswith("_")}

        try:
            if action == "send":
                text = body.get("message") or body.get("text") or body.get("prompt") or ""
                return await client.prompt(raw_id, str(text))
            if action in ("interrupt", "abort"):
                return await client.abort(raw_id)
            if action == "delete":
                ok = await client.delete_session(raw_id)
                return {"ok": ok}
            if action == "new_session":
                data = await client.create_session(
                    title=body.get("title"), parent_id=body.get("parentID")
                )
                return {"ok": True, "session": data}
            if action == "rename":
                data = await client.rename_session(raw_id, str(body.get("title") or ""))
                return {"ok": True, "session": data}
            if action == "approve":
                # permission once
                pid = body.get("permission_id") or body.get("permissionID") or agent.meta.get("pending_permission")
                if not pid:
                    return {"ok": False, "error": "нет permission_id"}
                return await client.reply_permission(raw_id, str(pid), body.get("response", "once"))
            if action == "deny":
                pid = body.get("permission_id") or body.get("permissionID") or agent.meta.get("pending_permission")
                if not pid:
                    return {"ok": False, "error": "нет permission_id"}
                return await client.reply_permission(raw_id, str(pid), "reject")
            if action == "permission_always":
                pid = body.get("permission_id") or agent.meta.get("pending_permission")
                if not pid:
                    return {"ok": False, "error": "нет permission_id"}
                return await client.reply_permission(raw_id, str(pid), "always")
            if action == "answer_question":
                qid = body.get("question_id") or agent.meta.get("pending_question")
                if not qid:
                    return {"ok": False, "error": "нет question_id"}
                return await client.reply_question(
                    raw_id, str(qid), body.get("answer") or body.get("text")
                )
            if action == "change_model":
                return await client.set_model(raw_id, body.get("model"))
            if action == "fork":
                return await client.fork_session(raw_id, body.get("message_id") or body.get("messageID"))
            if action == "revert":
                mid = body.get("message_id") or body.get("messageID")
                if not mid:
                    return {"ok": False, "error": "нужен message_id"}
                return await client.revert_session(raw_id, str(mid))
            if action == "rename":
                data = await client.rename_session(raw_id, str(body.get("title") or ""))
                return {"ok": True, "session": data}
            return {"ok": False, "error": f"Неизвестное действие: {action}"}
        except Exception as e:
            return {"ok": False, "error": str(e)}



def _confirm_message(action: str, agent: AgentState, payload: dict) -> str:
    title = agent.title or agent.id
    if action == "change_model":
        model = payload.get("model") or "новую модель"
        return (
            f"Сменить модель агента «{title}» на {model}?\n"
            f"⚠️ Это может увеличить расход квоты/стоимость."
        )
    if action == "new_session":
        model = payload.get("model") or ""
        extra = f" на модели {model}" if model else ""
        return (
            f"Создать новую сессию{extra}?\n"
            f"⚠️ Новая сессия на дорогой модели расходует квоту."
        )
    if action == "delete":
        return f"Удалить агента/сессию «{title}»? Это необратимо."
    if action == "rollback":
        return f"Откатить изменения агента «{title}»?"
    if action == "bulk":
        return "Выполнить массовое действие? ⚠️ Проверьте список затронутых агентов."
    return f"Подтвердите действие «{action}» для «{title}»."


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        try:
            ts = float(value)
            if ts > 1e12:
                ts = ts / 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        except Exception:
            return None
    if isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            pass
        for fmt in (
            "%Y-%m-%dT%H:%M:%S.%fZ",
            "%Y-%m-%dT%H:%M:%SZ",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
        ):
            try:
                dt = datetime.strptime(s.replace("+00:00", "Z"), fmt)
                return dt.replace(tzinfo=timezone.utc)
            except Exception:
                continue
    return None
