"""DSH rename — source + optional runtime tests."""
import importlib.util
import pytest


def test_rename_source_candidates():
    src = open("src/common/dsh_client.py", encoding="utf-8").read()
    assert "async def rename_session" in src
    assert "/rename" in src
    assert "PATCH" in src
    assert "local" in src


@pytest.mark.skipif(
    importlib.util.find_spec("pydantic_settings") is None,
    reason="pydantic_settings not installed",
)
def test_rename_tries_candidates(monkeypatch):
    import asyncio
    from src.common.dsh_client import DSHClient

    client = DSHClient()
    calls = []

    async def fake_request(method, path, json_body=None, timeout=30.0):
        calls.append((method, path, json_body))
        class R:
            status_code = 404
            text = "no"
        return R()

    monkeypatch.setattr(client, "_request", fake_request)
    result = asyncio.run(client.rename_session("sid1", "Новое имя"))
    assert result["ok"] is False
    assert result.get("local") is True
    assert len(calls) >= 2


@pytest.mark.skipif(
    importlib.util.find_spec("pydantic_settings") is None,
    reason="pydantic_settings not installed",
)
def test_rename_success_short_circuit(monkeypatch):
    import asyncio
    from src.common.dsh_client import DSHClient

    client = DSHClient()
    calls = []

    async def fake_request(method, path, json_body=None, timeout=30.0):
        calls.append((method, path))
        class R:
            status_code = 200
            text = "ok"
        return R()

    monkeypatch.setattr(client, "_request", fake_request)
    result = asyncio.run(client.rename_session("sid1", "Имя"))
    assert result["ok"] is True
    assert len(calls) == 1
