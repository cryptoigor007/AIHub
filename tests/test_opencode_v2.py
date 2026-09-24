"""OpenCode V2: HTML web-UI на неизвестных путях не должен ломать клиент."""
from __future__ import annotations

import asyncio
import json as _json

import pytest

pytest.importorskip("httpx", reason="httpx not installed")
pytest.importorskip("pydantic_settings", reason="pydantic_settings not installed")

import httpx

from src.common.opencode_client import OpenCodeClient

HTML = "<!doctype html><html><body>web ui</body></html>"


def _client(handler, flavor: str = "v2") -> OpenCodeClient:
    c = OpenCodeClient()
    c._flavor = flavor
    c._flavor_ts = 10**12  # кэш «свежий» — без сетевого /api/info

    def fake_client(timeout: float = 15.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    c._client = fake_client  # type: ignore[method-assign]
    return c


def test_list_sessions_v2_skips_html():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session":
            return httpx.Response(200, json={"data": [{"id": "ses_1", "title": "T"}]})
        if request.url.path in ("/session", "/sessions"):
            return httpx.Response(200, html=HTML)
        return httpx.Response(404)

    sessions = asyncio.run(_client(handler).list_sessions())
    assert sessions == [{"id": "ses_1", "title": "T"}]


def test_health_v2_uses_api_info():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/info":
            return httpx.Response(200, json={"version": "2.0.12", "pid": 1})
        return httpx.Response(200, html=HTML)

    health = asyncio.run(_client(handler).health())
    assert health.get("version") == "2.0.12"


def test_health_v1_json_fallback():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/global/health":
            return httpx.Response(200, json={"healthy": True})
        return httpx.Response(404)

    health = asyncio.run(_client(handler, flavor="v1").health())
    assert health == {"healthy": True}


def test_list_messages_v2():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/ses_1/message":
            return httpx.Response(200, json={"data": [{"id": "msg_1"}]})
        return httpx.Response(200, html=HTML)

    msgs = asyncio.run(_client(handler).list_messages("ses_1"))
    assert msgs == [{"id": "msg_1"}]


def test_create_session_v2_body_without_parent():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session" and request.method == "POST":
            body = _json.loads(request.content)
            assert "parentID" not in body  # V2 create не принимает parentID
            assert body.get("title") == "X"
            return httpx.Response(200, json={"id": "ses_new"})
        return httpx.Response(404)

    res = asyncio.run(_client(handler).create_session(title="X", parent_id="ses_parent"))
    assert res["id"] == "ses_new"


def test_prompt_v2_body():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/ses_1/prompt" and request.method == "POST":
            seen.update(_json.loads(request.content))
            return httpx.Response(200, json={"id": "msg_1"})
        return httpx.Response(200, html=HTML)

    res = asyncio.run(_client(handler).prompt("ses_1", "привет"))
    assert seen.get("text") == "привет"
    assert res.get("id") == "msg_1"


def test_set_model_v2_splits_provider():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/ses_1/model" and request.method == "POST":
            seen.update(_json.loads(request.content))
            return httpx.Response(200, json={})
        return httpx.Response(404)

    res = asyncio.run(_client(handler).set_model("ses_1", "deepseek/chat"))
    assert res.get("ok") is True
    assert seen.get("model") == {"providerID": "deepseek", "id": "chat"}


def test_event_urls_v2_first():
    urls = OpenCodeClient().event_urls()
    assert urls[0].endswith("/api/event")
    assert any(u.endswith("/event") for u in urls)


if __name__ == "__main__":
    print("use pytest")
