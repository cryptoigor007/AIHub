"""Локальные метаданные чатов: pinned / archived / title overrides.

data/pins.json:
  {"pinned": [...], "archived": [...], "titles": {"id": "Имя"}}
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .logging import get_logger

log = get_logger(__name__)

# Optional override for tests
_data_dir: Optional[Path] = None


def set_data_dir(path: Path | None) -> None:
    global _data_dir
    _data_dir = path


def _path() -> Path:
    if _data_dir is not None:
        return _data_dir / "pins.json"
    from .config import get_settings
    return get_settings().data_dir / "pins.json"


def load_meta() -> dict[str, Any]:
    path = _path()
    if not path.exists():
        return {"pinned": [], "archived": [], "titles": {}}
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
        return {
            "pinned": list(raw.get("pinned") or []),
            "archived": list(raw.get("archived") or []),
            "titles": dict(raw.get("titles") or {}),
        }
    except Exception as e:
        log.warning("chat_meta_load_error", error=str(e))
        return {"pinned": [], "archived": [], "titles": {}}


def save_meta(meta: dict[str, Any]) -> None:
    path = _path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "pinned": list(meta.get("pinned") or []),
            "archived": list(meta.get("archived") or []),
            "titles": dict(meta.get("titles") or {}),
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception as e:
        log.warning("chat_meta_save_error", error=str(e))


def set_title(agent_id: str, title: str) -> dict[str, Any]:
    meta = load_meta()
    t = (title or "").strip()[:120]
    if t:
        meta["titles"][agent_id] = t
    else:
        meta["titles"].pop(agent_id, None)
    save_meta(meta)
    return meta


def toggle_pin(agent_id: str, pinned: bool | None = None) -> dict[str, Any]:
    meta = load_meta()
    pins = list(meta.get("pinned") or [])
    if pinned is None:
        pinned = agent_id not in pins
    if pinned:
        if agent_id not in pins:
            pins.insert(0, agent_id)
    else:
        pins = [x for x in pins if x != agent_id]
    meta["pinned"] = pins
    save_meta(meta)
    return meta


def toggle_archive(agent_id: str, archived: bool | None = None) -> dict[str, Any]:
    meta = load_meta()
    arch = list(meta.get("archived") or [])
    if archived is None:
        archived = agent_id not in arch
    if archived:
        if agent_id not in arch:
            arch.append(agent_id)
        meta["pinned"] = [x for x in (meta.get("pinned") or []) if x != agent_id]
    else:
        arch = [x for x in arch if x != agent_id]
    meta["archived"] = arch
    save_meta(meta)
    return meta
