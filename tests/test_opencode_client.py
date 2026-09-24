"""Лёгкий тест без pydantic-settings (если нет в окружении)."""
import ast
from pathlib import Path

def test_source_has_official_paths():
    src = Path(__file__).resolve().parent.parent / "src/common/opencode_client.py"
    text = src.read_text(encoding="utf-8")
    # V1
    assert "/session" in text
    assert "/event" in text
    assert "list_projects" in text
    assert "fork_session" in text
    # V2
    assert "/api/session" in text
    assert "/api/event" in text
    assert "/api/info" in text
    assert "/api/model" in text
    assert "flavor" in text
    assert "stream_client" in text
    ast.parse(text)

if __name__ == "__main__":
    test_source_has_official_paths()
