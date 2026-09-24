"""Тест моделей: skip, если pydantic нет в окружении (standalone-прогон)."""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

pytest.importorskip("pydantic", reason="pydantic not installed")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.common.models import AgentState, AgentStatus, SystemType, Tokens


def test_agent_state_roundtrip():
    a = AgentState(
        id="dsh:1",
        system=SystemType.DSH,
        title="Test",
        status=AgentStatus.RUNNING,
        tokens=Tokens(input=10, output=5, total=15),
        updated_at=datetime.now(timezone.utc),
    )
    d = a.to_dict()
    assert d["id"] == "dsh:1"
    assert d["system"] == "dsh"
    b = AgentState.model_validate(d)
    assert b.title == "Test"


if __name__ == "__main__":
    test_agent_state_roundtrip()
    print("OK")
