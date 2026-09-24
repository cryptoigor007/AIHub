#!/usr/bin/env python3
"""Запуск отдельного процесса агрегатора (ai.aihub.aggregator)."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from src.aggregator.server import main
if __name__ == "__main__":
    main()
