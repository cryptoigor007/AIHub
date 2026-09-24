#!/usr/bin/env python3
"""Извлекает токен DSH из web.log и проверяет текущие TOKEN_PATTERNS.

Запуск:
  ./scripts/probe_token.py
  ./scripts/probe_token.py /path/to/web.log

Вывод: найден/не найден, длина, первые/последние 4 символа, какая regex сработала.
Никогда не печатает полный токен.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Паттерны — дублируем явно, чтобы скрипт работал даже без полного import config
DEFAULT_PATTERNS = [
    re.compile(r"token[=:\s]+([A-Za-z0-9._-]{20,})", re.IGNORECASE),
    re.compile(r"access[_-]?token[=:\s]+([A-Za-z0-9._-]{20,})", re.IGNORECASE),
    re.compile(r"Bearer\s+([A-Za-z0-9._-]{20,})", re.IGNORECASE),
    re.compile(r'"token"\s*:\s*"([A-Za-z0-9._-]{20,})"'),
    re.compile(r"'token'\s*:\s*'([A-Za-z0-9._-]{20,})'"),
    re.compile(r"[?&]token=([A-Za-z0-9._-]{20,})", re.IGNORECASE),
]


def mask(tok: str) -> str:
    if len(tok) <= 8:
        return "***"
    return f"{tok[:4]}…{tok[-4:]} (len={len(tok)})"


def main() -> int:
    log_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    if log_path is None:
        # пробуем .env
        env = ROOT / ".env"
        default = Path.home() / ".dsh" / "web.log"
        if env.exists():
            for line in env.read_text().splitlines():
                if line.startswith("DSH_WEB_LOG="):
                    default = Path(line.split("=", 1)[1].strip()).expanduser()
        log_path = default

    print(f"log: {log_path}")
    if not log_path.exists():
        print("FAIL: файл не найден")
        print("  → запустите dsh web, либо укажите путь: ./scripts/probe_token.py /path/to/web.log")
        return 1

    size = log_path.stat().st_size
    with log_path.open("rb") as f:
        if size > 65536:
            f.seek(size - 65536)
        content = f.read().decode("utf-8", errors="ignore")

    lines = content.splitlines()
    print(f"lines_in_window: {len(lines)}  size={size}")

    # с конца
    found = None
    pattern_idx = -1
    sample_line = ""
    for line in reversed(lines):
        for i, pat in enumerate(DEFAULT_PATTERNS):
            m = pat.search(line)
            if m:
                found = m.group(1)
                pattern_idx = i
                sample_line = line.strip()[:120]
                break
        if found:
            break

    if not found:
        print("FAIL: токен не найден текущими паттернами")
        print("--- последние 15 строк лога (для подбора regex) ---")
        for line in lines[-15:]:
            # redact possible secrets loosely
            safe = re.sub(r"([A-Za-z0-9._-]{20,})", lambda m: m.group(0)[:4] + "…", line)
            print(safe[:160])
        print("---")
        print("Добавьте паттерн в src/common/dsh_token.py TOKEN_PATTERNS")
        return 2

    print(f"OK: токен найден  pattern#{pattern_idx}  {mask(found)}")
    print(f"sample_line: {re.sub(re.escape(found), mask(found), sample_line)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
