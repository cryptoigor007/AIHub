"""Audit-лог управляющих действий (JSON-lines)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import get_settings
from .logging import get_logger

log = get_logger(__name__)


def audit(action: str, **kwargs: Any) -> None:
    """Пишет запись в logs/audit.log."""
    settings = get_settings()
    audit_path = Path(settings.log_dir) / "audit.log"
    audit_path.parent.mkdir(parents=True, exist_ok=True)

    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        **kwargs,
    }
    try:
        with audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as e:
        log.error("audit_write_failed", error=str(e), action=action)
