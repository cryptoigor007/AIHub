"""Редактирование секретов в логах."""
from __future__ import annotations
import re

_PATTERNS = [
    (re.compile(r"(token[=:\s]+)([A-Za-z0-9_-]{16,})", re.I), r"\1***"),
    (re.compile(r"(Bearer\s+)([A-Za-z0-9._-]{16,})", re.I), r"\1***"),
    (re.compile(r"(api[_-]?key[=:\s]+)([A-Za-z0-9_-]{8,})", re.I), r"\1***"),
    (re.compile(r"(password[=:\s]+)(\S+)", re.I), r"\1***"),
    (re.compile(r"(COOKIE_SECRET[=:\s]+)(\S+)", re.I), r"\1***"),
]


def redact_secrets(text: str) -> str:
    out = text
    for pat, repl in _PATTERNS:
        out = pat.sub(repl, out)
    return out
