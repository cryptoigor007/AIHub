"""Регрессионные проверки фиксов v3.7.0 (без сети/сервисов)."""
from __future__ import annotations

import importlib.util

import pytest

HAS_PS = importlib.util.find_spec("pydantic_settings") is not None
needs_ps = pytest.mark.skipif(not HAS_PS, reason="pydantic_settings not installed")


def test_watcher_uses_async_cli():
    """E: CLI запускается через async _run_cli, а не блокирующий subprocess.run."""
    src = open("src/tunnel/watcher.py", encoding="utf-8").read()
    assert "async def _run_cli" in src
    assert src.count("await self._run_cli") >= 5


def test_netinfo_last_tailscale_ts(tmp_path):
    """L: ключ last_tailscale_ts (был мёртвый last_ts_ts)."""
    from src.common.netinfo import load_netstate, touch_netstate

    st = touch_netstate(tmp_path, "tailscale")
    assert st.get("last_tailscale_ts")
    assert "last_ts_ts" not in st
    assert load_netstate(tmp_path).get("last_tailscale_ts")


def test_fallback_title_word_boundary():
    """Заголовок не режется посреди слова."""
    from src.common.autoname import fallback_title

    text = "проверь пожалуйста почему сейчас не работает туннель и что случилось"
    t = fallback_title([{"role": "user", "content": text}], max_len=40)
    assert 0 < len(t) <= 40
    assert t == t.rstrip()
    assert "  " not in t


def test_autoname_does_not_cache_placeholder():
    """A: автонейминг тянет upstream-историю и не кэширует заглушку «Новый чат»."""
    src = open("src/common/autoname.py", encoding="utf-8").read()
    assert "fetch_remote_history" in src
    assert 'title == "Новый чат"' in src


@needs_ps
def test_service_has_decorate_and_view():
    """J/I: единый декоратор метаданных для get_agents/get_agent_view/broadcast."""
    from src.aggregator.service import AggregatorService

    assert hasattr(AggregatorService, "_decorate")
    assert hasattr(AggregatorService, "get_agent_view")
    src = open("src/aggregator/service.py", encoding="utf-8").read()
    assert "by_id = {a.id: a for a in self.get_agents" in src


def test_payload_none_guarded():
    """K: payload=null не роняет обработчик."""
    svc = open("src/aggregator/service.py", encoding="utf-8").read()
    assert "payload = payload or {}" in svc
    app = open("src/gatekeeper/app.py", encoding="utf-8").read()
    assert 'body.get("payload") or {}' in app


def test_app_killswitch_can_be_disabled():
    """H: settings доступны владельцу при активном kill switch."""
    src = open("src/gatekeeper/app.py", encoding="utf-8").read()
    assert "def require_session_no_kill" in src
    seg = src.split("api_settings_get", 1)[1]
    assert "require_session_no_kill" in seg


def test_new_session_confirmed_by_default():
    """C/G: явный маршрут нового чата подтверждён и использует уникальный id."""
    src = open("src/gatekeeper/app.py", encoding="utf-8").read()
    assert 'payload.setdefault("_confirmed", True)' in src
    assert "uuid4().hex" in src


def test_ui_metrics_fields_match_backend():
    """D: UI читает реальные поля /api/metrics."""
    js = open("static/js/aihub.js", encoding="utf-8").read()
    assert "metrics.agents_total" in js
    assert "metrics.circuit" in js
    assert "metrics.agents_count" not in js


def test_extract_assistant_text_for_prompt_once():
    """prompt_once: берём текст (не reasoning) из parts; sid из вложенного data."""
    pytest.importorskip("httpx", reason="httpx not installed")
    if not HAS_PS:
        pytest.skip("pydantic_settings not installed")
    from src.common.opencode_client import OpenCodeClient

    msgs = [
        {
            "type": "assistant",
            "content": [
                {"type": "reasoning", "text": "размышление"},
                {"type": "text", "text": "Код и кофе"},
            ],
        },
        {"type": "user", "text": "привет"},
    ]
    assert OpenCodeClient._extract_assistant_text(msgs) == "Код и кофе"
    assert (
        OpenCodeClient._extract_assistant_text(
            [{"type": "assistant", "content": [{"type": "reasoning", "text": "x"}]}]
        )
        == ""
    )
    assert OpenCodeClient._extract_assistant_text([]) == ""


def test_prompt_once_handles_nested_session_id():
    """prompt_once: id сессии V2 приходит как {"data":{"id":...}} и ждём ответ асинхронно."""
    src = open("src/common/opencode_client.py", encoding="utf-8").read()
    assert '(data or {}).get("id")' in src
    assert "deadline" in src


def test_shutdown_catches_cancelled_error():
    """Shutdown не должен падать: CancelledError (BaseException) ловится явно."""
    for f in ("src/common/autoname.py", "src/tunnel/bot_dialog.py"):
        src = open(f, encoding="utf-8").read()
        assert "except asyncio.CancelledError" in src, f


@needs_ps
def test_dsh_token_negative_cache(tmp_path, monkeypatch):
    """Ненайденный токен не читает лог каждый вызов (негативный кэш)."""
    from src.common import dsh_token

    monkeypatch.setattr(
        dsh_token.DSHTokenReader, "log_path",
        property(lambda self: tmp_path / "nope.log"),
    )
    r = dsh_token.DSHTokenReader()
    calls = {"n": 0}
    orig = r._read_from_log

    def wrapped():
        calls["n"] += 1
        return orig()

    monkeypatch.setattr(r, "_read_from_log", wrapped)
    assert r.get_token() is None
    assert r.get_token() is None
    assert calls["n"] == 1


def test_mesh_notify_throttle_is_24h():
    """Уведомления про внешний доступ — не чаще 24 ч (было 6 ч)."""
    src = open("src/tunnel/watcher.py", encoding="utf-8").read()
    assert "ttl_sec=24 * 3600" in src


def test_upsert_skips_unchanged_broadcast():
    """Сервер не шлёт state_update, если агент не изменился (кроме updated_at)."""
    src = open("src/aggregator/service.py", encoding="utf-8").read()
    assert 'a.pop("updated_at", None)' in src
    assert "if a == b:" in src


def test_ui_incremental_render_no_full_rebuild():
    """UI: рендеры коалесцируются (rAF) и список обновляется инкрементально."""
    js = open("static/js/aihub.js", encoding="utf-8").read()
    assert "function scheduleRender" in js
    assert "renderList" in js
    assert "_rowEls" in js
    assert "el.innerHTML = list.map(rowHtml).join" not in js


def test_message_ts_normalized_and_invalid_date_guard():
    """Время сообщений: объект time{created} → ISO на сервере; UI не рисует Invalid Date."""
    svc = open("src/aggregator/service.py", encoding="utf-8").read()
    assert 't.get("created") or t.get("updated")' in svc
    assert "ts_dt.isoformat() if ts_dt else None" in svc
    js = open("static/js/aihub.js", encoding="utf-8").read()
    assert "isNaN(d.getTime())" in js


def test_sse_events_are_not_sessions():
    """События evt_* не попадают в список сессий."""
    svc = open("src/aggregator/service.py", encoding="utf-8").read()
    assert 'startswith("evt_")' in svc
    assert svc.count('startswith("evt_")') >= 2




