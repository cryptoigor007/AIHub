"""CLI хранилища: без секретов в выводе, команды работают."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("cryptography", reason="cryptography not installed")

from scripts import vault_cli
from src.common.vault import Vault
from tests.fakes import FakeKeyProvider


def _args(**kw):
    class A:
        pass
    a = A()
    for k, v in kw.items():
        setattr(a, k, v)
    return a


def test_set_get_status(tmp_path, capsys):
    v = Vault(tmp_path / "vault.enc", provider=FakeKeyProvider())
    assert vault_cli.cmd_set(_args(vault=v, key="COOKIE_SECRET", value="s3cret")) == 0
    assert vault_cli.cmd_get(_args(vault=v, key="COOKIE_SECRET")) == 0
    assert capsys.readouterr().out.strip() == "s3cret"
    assert vault_cli.cmd_status(_args(vault=v)) == 0
    out = capsys.readouterr().out
    assert "COOKIE_SECRET" in out
    assert "s3cret" not in out


def test_gen_creates_value(tmp_path):
    v = Vault(tmp_path / "vault.enc", provider=FakeKeyProvider())
    assert vault_cli.cmd_gen(_args(vault=v, key="OPENCODE_SERVER_PASSWORD", length=24)) == 0
    value = v.get("OPENCODE_SERVER_PASSWORD")
    assert value and len(value) >= 24


def test_delete(tmp_path):
    v = Vault(tmp_path / "vault.enc", provider=FakeKeyProvider())
    v.set("COOKIE_SECRET", "x")
    assert vault_cli.cmd_delete(_args(vault=v, key="COOKIE_SECRET")) == 0
    assert v.get("COOKIE_SECRET") is None


def test_migrate(tmp_path):
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=1:abc\n", encoding="utf-8")
    v = Vault(tmp_path / "vault.enc", provider=FakeKeyProvider())
    assert vault_cli.cmd_migrate(_args(vault=v, env=env)) == 0
    assert v.get("TELEGRAM_BOT_TOKEN") == "1:abc"


def test_unknown_key_rejected(tmp_path):
    v = Vault(tmp_path / "vault.enc", provider=FakeKeyProvider())
    assert vault_cli.cmd_get(_args(vault=v, key="NOT_A_SECRET")) == 2


def test_main_gen_via_parser(tmp_path, monkeypatch, capsys):
    """Регрессия: argparse dest флага --len должен быть length (для Task 8)."""
    v = Vault(tmp_path / "vault.enc", provider=FakeKeyProvider())
    monkeypatch.setattr(vault_cli, "get_vault", lambda: v)
    assert vault_cli.main(["gen", "OPENCODE_SERVER_PASSWORD", "--len", "32"]) == 0
    value = v.get("OPENCODE_SERVER_PASSWORD")
    assert value and len(value) >= 32
    out = capsys.readouterr().out
    assert "OPENCODE_SERVER_PASSWORD" in out
    assert value not in out
