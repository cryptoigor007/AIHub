"""Vault: AES-256-GCM, права файла, ошибки."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

import pytest

from src.common.keychain import KeychainError
from src.common.vault import Vault, VaultError
from tests.fakes import FakeKeyProvider


def _vault(tmp_path: Path) -> Vault:
    return Vault(tmp_path / "vault.enc", provider=FakeKeyProvider())


def test_missing_file_returns_empty(tmp_path):
    assert _vault(tmp_path).load() == {}


def test_roundtrip(tmp_path):
    v = _vault(tmp_path)
    v.set("A", "secret-1")
    v.set("B", "secret-2")
    assert v.get("A") == "secret-1"
    assert v.get("B") == "secret-2"


def test_wrong_key_fails(tmp_path):
    path = tmp_path / "vault.enc"
    Vault(path, provider=FakeKeyProvider()).set("A", "x")
    other = FakeKeyProvider()
    other.set_key(b"\x01" * 32)
    with pytest.raises(VaultError):
        Vault(path, provider=other).load()


def test_tampered_ciphertext_fails(tmp_path):
    path = tmp_path / "vault.enc"
    provider = FakeKeyProvider()
    Vault(path, provider=provider).set("A", "x")
    env = json.loads(path.read_text(encoding="utf-8"))
    ct = bytearray(base64.b64decode(env["ciphertext"]))
    ct[0] ^= 1
    env["ciphertext"] = base64.b64encode(bytes(ct)).decode()
    path.write_text(json.dumps(env), encoding="utf-8")
    with pytest.raises(VaultError):
        Vault(path, provider=provider).load()


def test_missing_key_does_not_create_one(tmp_path):
    path = tmp_path / "vault.enc"
    original = FakeKeyProvider()
    Vault(path, provider=original).set("A", "x")
    empty = FakeKeyProvider()
    with pytest.raises(VaultError):
        Vault(path, provider=empty).load()
    assert empty.key is None
    assert Vault(path, provider=original).get("A") == "x"


@pytest.mark.parametrize("raw", ["[1, 2, 3]", '"hello"', "null"])
def test_non_object_envelope_fails(tmp_path, raw):
    path = tmp_path / "vault.enc"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(VaultError):
        Vault(path, provider=FakeKeyProvider()).load()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda env: env.update({"version": "not-a-number"}),
        lambda env: env.update({"version": None}),
        lambda env: env.pop("version", None),
        lambda env: env.update({"nonce": 12345}),
        lambda env: env.update({"ciphertext": ["partial"]}),
    ],
)
def test_malformed_envelope_fields_fails(tmp_path, mutate):
    path = tmp_path / "vault.enc"
    provider = FakeKeyProvider()
    Vault(path, provider=provider).set("A", "x")
    env = json.loads(path.read_text(encoding="utf-8"))
    mutate(env)
    path.write_text(json.dumps(env), encoding="utf-8")
    with pytest.raises(VaultError):
        Vault(path, provider=provider).load()


def test_corrupt_json_fails(tmp_path):
    path = tmp_path / "vault.enc"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(VaultError):
        Vault(path, provider=FakeKeyProvider()).load()


def test_file_permissions(tmp_path):
    path = tmp_path / "vault.enc"
    Vault(path, provider=FakeKeyProvider()).set("A", "x")
    assert (path.stat().st_mode & 0o777) == 0o600


def test_key_created_once(tmp_path):
    path = tmp_path / "vault.enc"
    provider = FakeKeyProvider()
    v = Vault(path, provider=provider)
    v.set("A", "x")
    first = provider.key
    v.set("B", "y")
    assert provider.key == first
    assert len(first) == 32


def test_delete(tmp_path):
    v = _vault(tmp_path)
    v.set("A", "x")
    v.delete("A")
    assert v.get("A") is None


def test_migrate_env_secrets(tmp_path):
    from src.common.vault import ENV_SECRET_KEYS, migrate_env_secrets
    env = tmp_path / ".env"
    env.write_text(
        "NETWORK_MODE=hybrid\nTELEGRAM_BOT_TOKEN=123:abc\nCOOKIE_SECRET='quoted'\n"
        "OWNER_TELEGRAM_ID=42\n# COOKIE_SECRET=commented\n",
        encoding="utf-8",
    )
    v = _vault(tmp_path)
    migrated = migrate_env_secrets(v, env)
    assert set(migrated) == {"TELEGRAM_BOT_TOKEN", "COOKIE_SECRET", "OWNER_TELEGRAM_ID"}
    assert v.get("TELEGRAM_BOT_TOKEN") == "123:abc"
    assert v.get("COOKIE_SECRET") == "quoted"
    assert v.get("OWNER_TELEGRAM_ID") == "42"
    text = env.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN" not in text
    assert "NETWORK_MODE=hybrid" in text
    assert (env.stat().st_mode & 0o777) == 0o600
    # повторная миграция ничего не делает
    assert migrate_env_secrets(v, env) == []


def test_migrate_without_env_file(tmp_path):
    from src.common.vault import migrate_env_secrets
    assert migrate_env_secrets(_vault(tmp_path), tmp_path / "missing.env") == []


def test_migrate_does_not_override_vault(tmp_path):
    from src.common.vault import migrate_env_secrets
    v = _vault(tmp_path)
    v.set("COOKIE_SECRET", "from-vault")
    env = tmp_path / ".env"
    env.write_text("COOKIE_SECRET=from-env\n", encoding="utf-8")
    assert migrate_env_secrets(v, env) == ["COOKIE_SECRET"]
    assert v.get("COOKIE_SECRET") == "from-vault"  # vault главнее
    assert "COOKIE_SECRET" not in env.read_text(encoding="utf-8")


class _BrokenKeyProvider:
    """KeyProvider, имитирующий недоступный Keychain (получатель ключа падает)."""

    def get_key(self):
        raise KeychainError("Keychain недоступен")

    def set_key(self, key: bytes) -> None:
        raise AssertionError("set_key не должен вызываться при недоступном Keychain")

    def delete_key(self) -> None:
        pass


def test_migrate_unavailable_keychain_leaves_env_alone(tmp_path):
    from src.common.vault import migrate_env_secrets
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=123:abc\n", encoding="utf-8")
    before = env.read_text(encoding="utf-8")
    v = Vault(tmp_path / "vault.enc", provider=_BrokenKeyProvider())
    assert migrate_env_secrets(v, env) == []
    assert env.read_text(encoding="utf-8") == before  # .env не тронут
    assert not v.exists()


def test_migrate_unreadable_vault_path_leaves_env_alone(tmp_path):
    from src.common.vault import migrate_env_secrets
    vault_dir = tmp_path / "vault.enc"
    vault_dir.mkdir()  # существует, но это не файл: чтение даёт OS-ошибку
    env = tmp_path / ".env"
    env.write_text("COOKIE_SECRET=abc\n", encoding="utf-8")
    before = env.read_text(encoding="utf-8")
    v = Vault(vault_dir, provider=FakeKeyProvider())
    assert migrate_env_secrets(v, env) == []
    assert env.read_text(encoding="utf-8") == before


def test_migrate_corrupted_vault_raises(tmp_path):
    from src.common.vault import migrate_env_secrets
    (tmp_path / "vault.enc").write_text("not json", encoding="utf-8")
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=123\n", encoding="utf-8")
    with pytest.raises(VaultError):
        migrate_env_secrets(_vault(tmp_path), env)
    assert "TELEGRAM_BOT_TOKEN" in env.read_text(encoding="utf-8")  # .env не тронут


def test_migrate_empty_value_scrubbed_but_not_written(tmp_path):
    from src.common.vault import migrate_env_secrets
    env = tmp_path / ".env"
    env.write_text("COOKIE_SECRET=\nKEEP=1\n", encoding="utf-8")
    v = _vault(tmp_path)
    assert migrate_env_secrets(v, env) == []
    text = env.read_text(encoding="utf-8")
    assert "COOKIE_SECRET" not in text
    assert "KEEP=1" in text
    assert v.get("COOKIE_SECRET") is None  # пустое значение не пишется в vault
    assert (env.stat().st_mode & 0o777) == 0o600


def test_migrate_duplicates_remove_all_and_migrate_first_nonempty(tmp_path):
    from src.common.vault import migrate_env_secrets
    env = tmp_path / ".env"
    env.write_text(
        "COOKIE_SECRET=\nCOOKIE_SECRET=from-second\nKEEP=1\n", encoding="utf-8"
    )
    v = _vault(tmp_path)
    assert migrate_env_secrets(v, env) == ["COOKIE_SECRET"]
    assert v.get("COOKIE_SECRET") == "from-second"
    text = env.read_text(encoding="utf-8")
    assert "COOKIE_SECRET" not in text  # удаляются все строки ключа
    assert "KEEP=1" in text


def test_migrate_duplicates_first_nonempty_value_wins(tmp_path):
    from src.common.vault import migrate_env_secrets
    env = tmp_path / ".env"
    env.write_text("COOKIE_SECRET=first\nCOOKIE_SECRET=second\n", encoding="utf-8")
    v = _vault(tmp_path)
    assert migrate_env_secrets(v, env) == ["COOKIE_SECRET"]
    assert v.get("COOKIE_SECRET") == "first"
    assert "COOKIE_SECRET" not in env.read_text(encoding="utf-8")


def test_migrate_existing_vault_missing_key_leaves_env_alone(tmp_path):
    """Vault-файл есть, но провайдер не отдаёт ключ — .env не трогаем."""
    from src.common.vault import migrate_env_secrets
    path = tmp_path / "vault.enc"
    original = FakeKeyProvider()
    Vault(path, provider=original).set("A", "x")
    env = tmp_path / ".env"
    env.write_text("TELEGRAM_BOT_TOKEN=123:abc\n", encoding="utf-8")
    before = env.read_text(encoding="utf-8")
    empty = FakeKeyProvider()  # key is None
    v = Vault(path, provider=empty)
    assert migrate_env_secrets(v, env) == []
    assert env.read_text(encoding="utf-8") == before
    assert empty.key is None
