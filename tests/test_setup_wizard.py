"""Мастер: успех, неверный токен, таймаут owner id, миграция."""
from __future__ import annotations

import pytest

pytest.importorskip("httpx", reason="httpx not installed")
pytest.importorskip("cryptography", reason="cryptography not installed")

from pathlib import Path

from scripts.setup_wizard import run_wizard
from src.common.envfile import read_env_value
from src.common.vault import Vault
from tests.fakes import FakeKeyProvider, FakeTelegramClient


def _run(tmp_path, tg, answers=("123456:ABC",), force=False):
    env = tmp_path / ".env"
    env.write_text("NETWORK_MODE=hybrid\nTELEGRAM_BOT_TOKEN=\n", encoding="utf-8")
    vault = Vault(tmp_path / "vault.enc", provider=FakeKeyProvider())
    inputs = iter(answers)
    code = run_wizard(
        prompt=lambda q, default="": next(inputs, default),
        prompt_secret=lambda q: "123456:ABC",
        telegram=tg,
        vault=vault,
        env_path=env,
        start_services=None,
        interactive=False,
        force=force,
    )
    return code, vault, env


def test_wizard_success(tmp_path):
    tg = FakeTelegramClient(owner_id=777)
    code, vault, env = _run(tmp_path, tg)
    assert code == 0
    assert vault.get("TELEGRAM_BOT_TOKEN") == "123456:ABC"
    assert vault.get("OWNER_TELEGRAM_ID") == "777"
    assert read_env_value(env, "ENV") == "production"
    assert read_env_value(env, "LOCAL_LOGIN") == "loopback"
    assert "TELEGRAM_BOT_TOKEN" not in env.read_text(encoding="utf-8")
    assert tg.sent and tg.sent[0][0] == 777  # тестовое сообщение владельцу


def test_wizard_bad_token(tmp_path):
    tg = FakeTelegramClient(me=None)
    code, vault, env = _run(tmp_path, tg)
    assert code == 1
    assert vault.get("TELEGRAM_BOT_TOKEN") is None


def test_wizard_owner_timeout_uses_manual(tmp_path):
    tg = FakeTelegramClient(owner_id=None)
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    vault = Vault(tmp_path / "vault.enc", provider=FakeKeyProvider())
    inputs = iter(["4242"])  # ручной ввод ID
    code = run_wizard(
        prompt=lambda q, default="": next(inputs, default),
        prompt_secret=lambda q: "123456:ABC",
        telegram=tg,
        vault=vault,
        env_path=env,
        start_services=None,
        interactive=False,
        force=False,
    )
    assert code == 0
    assert vault.get("OWNER_TELEGRAM_ID") == "4242"


def test_wizard_migrates_existing_secrets(tmp_path):
    env = tmp_path / ".env"
    env.write_text("COOKIE_SECRET=old\nTELEGRAM_BOT_TOKEN=\n", encoding="utf-8")
    vault = Vault(tmp_path / "vault.enc", provider=FakeKeyProvider())
    code = run_wizard(
        prompt=lambda q, default="": default,
        prompt_secret=lambda q: "123456:ABC",
        telegram=FakeTelegramClient(owner_id=1),
        vault=vault,
        env_path=env,
        start_services=None,
        interactive=False,
        force=False,
    )
    assert code == 0
    assert vault.get("COOKIE_SECRET") == "old"
    assert "COOKIE_SECRET" not in env.read_text(encoding="utf-8")


def test_wizard_already_configured_without_force(tmp_path):
    vault = Vault(tmp_path / "vault.enc", provider=FakeKeyProvider())
    vault.set("TELEGRAM_BOT_TOKEN", "123456:ABC")
    vault.set("OWNER_TELEGRAM_ID", "1")
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    code = run_wizard(
        prompt=lambda q, default="": default,
        prompt_secret=lambda q: "x",
        telegram=FakeTelegramClient(),
        vault=vault,
        env_path=env,
        start_services=None,
        interactive=False,
        force=False,
    )
    assert code == 0  # ничего не делаем, показываем статус
