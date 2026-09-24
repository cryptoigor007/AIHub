#!/usr/bin/env python3
"""Отдельный процесс заглушки (обычно встроен в tunnel-watcher)."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.tunnel.stub import run_stub_forever
if __name__ == "__main__":
    run_stub_forever()
