"""Чтение токена DSH из web.log с авто-обновлением."""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Optional

from .config import get_settings
from .logging import get_logger

log = get_logger(__name__)

# Паттерны из логов dsh web. Уточнять на месте (docs/ON_SITE.md).
TOKEN_PATTERNS = [
    # common log forms: token=..., access_token: ..., "token": "..."
    re.compile(r"token[=:\s]+([A-Za-z0-9._-]{20,})", re.IGNORECASE),
    re.compile(r"access[_-]?token[=:\s]+([A-Za-z0-9._-]{20,})", re.IGNORECASE),
    re.compile(r"Bearer\s+([A-Za-z0-9._-]{20,})", re.IGNORECASE),
    re.compile(r'"token"\s*:\s*"([A-Za-z0-9._-]{20,})"'),
    re.compile(r"'token'\s*:\s*'([A-Za-z0-9._-]{20,})'"),
    # URL query fragments occasionally logged
    re.compile(r"[?&]token=([A-Za-z0-9._-]{20,})", re.IGNORECASE),
]


class DSHTokenReader:
    def __init__(self) -> None:
        self._token: Optional[str] = None
        self._last_mtime: float = 0.0
        self._last_read: float = 0.0

    @property
    def log_path(self) -> Path:
        return get_settings().dsh_web_log

    def _read_from_log(self) -> Optional[str]:
        path = self.log_path
        if not path.exists():
            log.warning("dsh_web_log_missing", path=str(path))
            return None

        try:
            # Читаем с конца (последние ~64 КБ достаточно)
            size = path.stat().st_size
            with path.open("rb") as f:
                if size > 65536:
                    f.seek(size - 65536)
                content = f.read().decode("utf-8", errors="ignore")
        except Exception as e:
            log.error("dsh_log_read_error", error=str(e))
            return None

        lines = content.splitlines()
        # Ищем с конца — самый свежий токен
        for line in reversed(lines):
            for pat in TOKEN_PATTERNS:
                m = pat.search(line)
                if m:
                    token = m.group(1)
                    log.debug("dsh_token_found", length=len(token))
                    return token
        log.warning("dsh_token_not_found_in_log")
        return None

    def get_token(self, force: bool = False) -> Optional[str]:
        path = self.log_path
        now = time.time()
        mtime = 0.0
        if path.exists():
            try:
                mtime = path.stat().st_mtime
            except OSError:
                pass

        if (
            not force
            and self._token
            and mtime == self._last_mtime
            and (now - self._last_read) < 30
        ):
            return self._token

        token = self._read_from_log()
        if token:
            self._token = token
            self._last_mtime = mtime
            self._last_read = now
        return self._token

    def invalidate(self) -> None:
        self._token = None
        self._last_mtime = 0.0


# Singleton
_reader = DSHTokenReader()


def get_dsh_token(force: bool = False) -> Optional[str]:
    return _reader.get_token(force=force)


def invalidate_dsh_token() -> None:
    _reader.invalidate()
