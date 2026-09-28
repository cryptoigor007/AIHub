"""Автонейминг технических названий через бесплатную модель OpenCode."""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .logging import get_logger

log = get_logger(__name__)

_TECH = [
    re.compile(r"^evt_", re.I),
    re.compile(r"^ses_[0-9a-f]{8,}$", re.I),
    re.compile(r"^[0-9a-f]{12,}$", re.I),
    re.compile(r"^сессия\s+\d{1,2}[./]\d{1,2}", re.I),
    re.compile(r"^session\b", re.I),
    re.compile(r"^untitled", re.I),
    re.compile(r"^new\s+(chat|session)", re.I),
]
_FREE = ("space-bunny-free", "mimo-v2.6-flash-free", "nemotron-3.5-lightning-free")
_data_dir: Optional[Path] = None


def set_data_dir(path: Path | None) -> None:
    global _data_dir
    _data_dir = path


def is_technical_title(title: str) -> bool:
    t = (title or "").strip()
    if not t or len(t) < 3:
        return True
    if any(p.search(t) for p in _TECH):
        return True
    return bool(re.fullmatch(r"[0-9a-f-]{8,}", t, re.I))


def _names_path() -> Path:
    if _data_dir is not None:
        return _data_dir / "names.json"
    from .config import get_settings
    return get_settings().data_dir / "names.json"


def load_names() -> dict[str, Any]:
    p = _names_path()
    if not p.exists():
        return {"cache": {}, "hidden_session_id": None, "progress": {}}
    try:
        return json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {"cache": {}, "hidden_session_id": None, "progress": {}}


def save_names(data: dict[str, Any]) -> None:
    p = _names_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(p)
    except Exception as e:
        log.warning("names_save_error", error=str(e))


def get_cached(agent_id: str) -> Optional[str]:
    entry = (load_names().get("cache") or {}).get(agent_id)
    if isinstance(entry, dict):
        return entry.get("title")
    return entry if isinstance(entry, str) else None


def set_cached(agent_id: str, title: str, source: str = "llm") -> None:
    data = load_names()
    data.setdefault("cache", {})[agent_id] = {
        "title": title[:40],
        "source": source,
        "ts": datetime.now(timezone.utc).isoformat(),
    }
    save_names(data)


def fallback_title(messages: list[dict], max_len: int = 40) -> str:
    for m in messages[:5]:
        role = (m.get("role") or m.get("type") or "").lower()
        if role not in ("user", "human", "input"):
            continue
        text = m.get("content") or m.get("text") or m.get("message") or ""
        if isinstance(text, list):
            text = " ".join(
                str(p.get("text") or p) if isinstance(p, dict) else str(p) for p in text
            )
        line = str(text).strip().split("\n")[0].strip()
        if line:
            if len(line) <= max_len:
                return line
            cut = line[:max_len].rsplit(" ", 1)[0].strip()
            return cut or line[:max_len].strip()
    return "Новый чат"


# ── background service ──────────────────────────────────────────

class AutonameService:
    """Фоновый бэкфилл технических названий (≤10 за проход, ≥6 с пауза)."""

    def __init__(self, aggregator, opencode_client=None):
        self.agg = aggregator
        self.client = opencode_client
        self._running = False
        self._task = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        import asyncio
        self._task = asyncio.create_task(self._loop(), name="autoname")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except Exception:
                pass
            self._task = None

    async def _loop(self) -> None:
        import asyncio
        await asyncio.sleep(10)
        while self._running:
            try:
                await self._pass()
            except Exception as e:
                log.warning("autoname_pass_error", error=str(e))
            await asyncio.sleep(90)

    async def _pass(self) -> None:
        import asyncio
        agents = self.agg.get_agents(include_archived=True)
        done = 0
        for a in agents:
            if done >= 10:
                break
            if get_cached(a.id):
                continue
            if not is_technical_title(a.title or ""):
                continue
            if (a.meta or {}).get("local_title"):
                continue
            history = self.agg.get_history(a.id) or []
            if not history:
                # Нет кэша — тянем историю с upstream, иначе имя будет заглушкой.
                try:
                    history = await self.agg.fetch_remote_history(a.id) or []
                except Exception:
                    history = []
            if not history:
                # Нет данных для осмысленного имени — не затираем техническое имя.
                continue
            title = fallback_title(history)
            # try free model if client available
            if self.client is not None:
                try:
                    title = await self._llm_title(history, a.project)
                except Exception as e:
                    log.debug("autoname_llm_skip", error=str(e))
            if not title or title == "Новый чат":
                # Нечего предложить — попробуем позже, заглушку не кэшируем.
                continue
            set_cached(a.id, title, source="fallback" if title == fallback_title(history) else "llm")
            try:
                from . import chat_meta
                chat_meta.set_title(a.id, title)
            except Exception:
                pass
            if a.id in getattr(self.agg, "_agents", {}):
                self.agg._agents[a.id].title = title
                self.agg._agents[a.id].meta = dict(self.agg._agents[a.id].meta or {})
                self.agg._agents[a.id].meta["local_title"] = True
            done += 1
            log.info("autoname_renamed", agent_id=a.id, title=title)
            await asyncio.sleep(6)
        if done:
            data = load_names()
            data.setdefault("progress", {})["last_pass"] = __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat()
            data["progress"]["renamed"] = data["progress"].get("renamed", 0) + done
            save_names(data)

    async def _llm_title(self, messages, project=None) -> str:
        # Prefer free models; fall back to first-line heuristic
        free = None
        try:
            models = await self.client.list_models()
            ids = []
            if isinstance(models, list):
                for m in models:
                    mid = (m.get("id") or m.get("name") or m.get("model")) if isinstance(m, dict) else str(m)
                    if mid:
                        ids.append(str(mid))
            elif isinstance(models, dict):
                ids = [str(k) for k in models]
            for pref in _FREE:
                if pref in ids:
                    free = pref
                    break
            if not free:
                free = next((m for m in ids if m.endswith("-free") or "-free-" in m), None)
        except Exception:
            free = None
        if not free or not hasattr(self.client, "prompt_once"):
            return fallback_title(messages)
        preview = []
        for m in messages[:5]:
            role = (m.get("role") or "").lower()
            text = m.get("content") or m.get("text") or m.get("message") or ""
            if isinstance(text, list):
                text = " ".join(str(p.get("text") or p) if isinstance(p, dict) else str(p) for p in text)
            text = str(text).strip()[:200]
            if text:
                preview.append(f"{role}: {text}")
        if not preview:
            return fallback_title(messages)
        prompt = (
            "Придумай короткое название чата на русском: 2–4 слова, без кавычек, "
            "без точки, ≤40 символов. Только название.\n\n" + "\n".join(preview)[:800]
        )
        if project:
            prompt += f"\nПроект: {project}"
        result = await self.client.prompt_once(prompt, model=free)
        title = (result or "").strip().strip('"«»').split("\n")[0].strip()
        title = re.sub(r"[^\w\s\-а-яА-ЯёЁ]", "", title, flags=re.UNICODE).strip()
        if 2 <= len(title) <= 40 and not is_technical_title(title):
            return title[:40]
        return fallback_title(messages)
