#!/usr/bin/env python3
"""Запуск сторожа туннеля."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.tunnel.watcher import main

if __name__ == "__main__":
    asyncio.run(main())
