#!/usr/bin/env python3
"""Запуск привратника (uvicorn)."""

from __future__ import annotations

import sys
from pathlib import Path

# Добавляем корень репозитория в path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import uvicorn

from src.common.config import get_settings


def main() -> None:
    settings = get_settings()
    settings.ensure_secrets()
    settings.ensure_dirs()
    if not settings.telegram_bot_token:
        print("WARN: TELEGRAM_BOT_TOKEN не задан — /auth вернёт «токен не задан»", flush=True)

    uvicorn.run(
        "src.gatekeeper.app:app",
        host=settings.gatekeeper_host,
        port=settings.gatekeeper_port,
        log_level=settings.log_level.lower(),
        reload=False,
        workers=1,
    )


if __name__ == "__main__":
    main()
