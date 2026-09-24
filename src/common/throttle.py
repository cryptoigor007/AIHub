"""Троттлинг уведомлений: файл-флаг с TTL, чтобы не спамить владельца."""

from __future__ import annotations

import time
from pathlib import Path


def notification_due(flag: Path, ttl_sec: float, now: float | None = None) -> bool:
    """True, если уведомление можно отправить: файла нет, он просрочен или битый."""
    now = time.time() if now is None else now
    try:
        last = float(Path(flag).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return (now - last) >= ttl_sec


def mark_notified(flag: Path, now: float | None = None) -> None:
    """Отметить попытку уведомления. Пишем до отправки — троттлим попытки, а не успехи."""
    now = time.time() if now is None else now
    flag = Path(flag)
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.write_text(f"{now:.3f}", encoding="utf-8")
