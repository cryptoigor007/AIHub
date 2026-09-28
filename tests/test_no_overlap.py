"""Sanity: new modules import without breaking old contracts."""
import importlib.util
import pytest


def _has_pydantic_settings() -> bool:
    return importlib.util.find_spec("pydantic_settings") is not None


def test_chat_meta_exportable():
    from src.common import chat_meta
    assert callable(chat_meta.load_meta)
    assert callable(chat_meta.set_title)
    assert callable(chat_meta.toggle_pin)
    assert callable(chat_meta.toggle_archive)


def test_autoname_exportable():
    from src.common.autoname import is_technical_title, AutonameService, fallback_title
    assert is_technical_title("evt_x")
    assert not is_technical_title("Анализ логов")
    assert fallback_title([]) == "Новый чат"


@pytest.mark.skipif(not _has_pydantic_settings(), reason="pydantic_settings not installed")
def test_bot_dialog_import():
    from src.tunnel.bot_dialog import BotDialog
    b = BotDialog()
    assert b._running is False


@pytest.mark.skipif(not _has_pydantic_settings(), reason="pydantic_settings not installed")
def test_dsh_client_has_rename():
    from src.common.dsh_client import DSHClient
    assert hasattr(DSHClient, "rename_session")
    assert hasattr(DSHClient, "post_action")
    src = open("src/common/dsh_client.py", encoding="utf-8").read()
    assert "rename_session" in src
    assert "PATCH" in src


def test_dsh_rename_in_source():
    """Source-level check — no runtime config needed."""
    src = open("src/common/dsh_client.py", encoding="utf-8").read()
    assert "async def rename_session" in src
    assert '"local": True' in src or "'local': True" in src


@pytest.mark.skipif(not _has_pydantic_settings(), reason="pydantic_settings not installed")
def test_watcher_has_autopilot_methods():
    from src.tunnel.watcher import TunnelWatcher
    w = TunnelWatcher()
    assert hasattr(w, "_maybe_autoserve")
    assert hasattr(w, "_maybe_fix_acceptdns")
    assert hasattr(w, "_maybe_remind_tailscale")
    assert hasattr(w, "_set_menu_button")


def test_watcher_autopilot_in_source():
    src = open("src/tunnel/watcher.py", encoding="utf-8").read()
    assert "_maybe_autoserve" in src
    assert "_maybe_fix_acceptdns" in src
    assert "_maybe_remind_tailscale" in src
    assert "chat_id" in src  # D6 dual menu button
    assert "BotDialog" in src


def test_app_has_chats_meta_route():
    src = open("src/gatekeeper/app.py", encoding="utf-8").read()
    assert "api/chats/meta" in src
    assert "last_channel" in src


def test_prompt_once_in_source():
    src = open("src/common/opencode_client.py", encoding="utf-8").read()
    assert "async def prompt_once" in src


def test_notify_owner_uses_path_flags():
    src = open("src/tunnel/watcher.py", encoding="utf-8").read()
    assert '.notify_' in src
    assert "notification_due(flag" in src or "notification_due(flag," in src


def test_get_agents_copies():
    src = open("src/aggregator/service.py", encoding="utf-8").read()
    assert "model_copy" in src


def test_kill_switch_post_route():
    src = open("src/gatekeeper/app.py", encoding="utf-8").read()
    assert "api_settings_post" in src
    assert "kill_switch" in src


def test_ui_has_change_model_and_longpress():
    js = open("static/js/aihub.js", encoding="utf-8").read()
    assert "change_model" in js
    assert "longPressTimer" in js
    assert "killBtn" in js
