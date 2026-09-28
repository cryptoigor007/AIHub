"""Unit tests for autoname helpers."""
from src.common.autoname import is_technical_title, fallback_title


def test_tech_evt():
    assert is_technical_title("evt_abc123")


def test_tech_ses():
    assert is_technical_title("ses_a1b2c3d4e5f6")


def test_tech_hex():
    assert is_technical_title("a1b2c3d4e5f67890")


def test_tech_session_date():
    assert is_technical_title("Сессия 12.03")


def test_tech_session_en():
    assert is_technical_title("Session foo")


def test_human_ok():
    assert not is_technical_title("Анализ логов сервера")


def test_fallback_from_user():
    msgs = [
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "Как настроить VPN на macOS?\nподробнее"},
    ]
    assert fallback_title(msgs).startswith("Как настроить VPN")


def test_fallback_empty():
    assert fallback_title([]) == "Новый чат"
