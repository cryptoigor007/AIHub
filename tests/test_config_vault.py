"""Приоритет env > vault > .env и запись секретов в vault."""
from __future__ import annotations

import os

import pytest

pytest.importorskip("pydantic_settings", reason="pydantic_settings not installed")

from src.common import config as config_mod
from src.common.config import clear_settings_cache, get_settings
from src.common.vault import Vault
from tests.fakes import FakeKeyProvider


def _inject_vault(monkeypatch, tmp_path):
    vault = Vault(tmp_path / "vault.enc", provider=FakeKeyProvider())
    monkeypatch.setattr(config_mod, "get_vault", lambda: vault)
    return vault


def test_owner_default_is_zero(monkeypatch):
    monkeypatch.delenv("OWNER_TELEGRAM_ID", raising=False)
    s = config_mod.Settings()
    assert s.owner_telegram_id == 0


def test_vault_fills_secret(monkeypatch, tmp_path):
    vault = _inject_vault(monkeypatch, tmp_path)
    vault.set("COOKIE_SECRET", "from-vault")
    monkeypatch.delenv("COOKIE_SECRET", raising=False)
    clear_settings_cache()
    assert get_settings().cookie_secret == "from-vault"


def test_env_wins_over_vault(monkeypatch, tmp_path):
    vault = _inject_vault(monkeypatch, tmp_path)
    vault.set("COOKIE_SECRET", "from-vault")
    monkeypatch.setenv("COOKIE_SECRET", "from-env")
    clear_settings_cache()
    assert get_settings().cookie_secret == "from-env"


def test_vault_owner_id_converted_to_int(monkeypatch, tmp_path):
    vault = _inject_vault(monkeypatch, tmp_path)
    vault.set("OWNER_TELEGRAM_ID", "12345")
    monkeypatch.delenv("OWNER_TELEGRAM_ID", raising=False)
    clear_settings_cache()
    assert get_settings().owner_telegram_id == 12345


def test_ensure_secrets_writes_vault(monkeypatch, tmp_path):
    vault = _inject_vault(monkeypatch, tmp_path)
    monkeypatch.delenv("COOKIE_SECRET", raising=False)
    monkeypatch.delenv("SECRET_PATH", raising=False)
    monkeypatch.chdir(tmp_path)
    clear_settings_cache()
    s = get_settings()
    s.cookie_secret = ""
    s.secret_path = ""
    s.ensure_secrets()
    assert vault.get("COOKIE_SECRET") == s.cookie_secret
    assert vault.get("SECRET_PATH") == s.secret_path
    assert not (tmp_path / ".env").exists()  # в .env секреты не пишутся
