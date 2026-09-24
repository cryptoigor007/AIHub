"""Шифрованное хранилище секретов: AES-256-GCM, ключ — из Keychain."""

from __future__ import annotations

import base64
import json
import os
import time
from pathlib import Path
from typing import Optional, Protocol

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .envfile import remove_env_keys
from .logging import get_logger

log = get_logger(__name__)

VAULT_VERSION = 1
AAD = b"aihub-vault-v1"
DEFAULT_VAULT_PATH = Path("data/vault.enc")


class VaultError(Exception):
    """Ошибка хранилища: повреждённый файл, неверный ключ, нет Keychain."""


class KeyProvider(Protocol):
    def get_key(self) -> Optional[bytes]: ...
    def set_key(self, key: bytes) -> None: ...
    def delete_key(self) -> None: ...


class Vault:
    def __init__(
        self,
        path: Path = DEFAULT_VAULT_PATH,
        provider: Optional[KeyProvider] = None,
    ) -> None:
        self.path = Path(path)
        self._provider = provider

    @property
    def provider(self) -> KeyProvider:
        if self._provider is None:
            from .keychain import get_key_provider

            self._provider = get_key_provider()
        return self._provider

    def exists(self) -> bool:
        return self.path.exists()

    def _get_or_create_key(self) -> bytes:
        key = self.provider.get_key()
        if key is None:
            key = os.urandom(32)
            self.provider.set_key(key)
        if len(key) != 32:
            raise VaultError("ключ vault должен быть 32 байта")
        return key

    def _get_key(self) -> bytes:
        key = self.provider.get_key()
        if key is None:
            raise VaultError("нет ключа vault (Keychain не отдал ключ)")
        if len(key) != 32:
            raise VaultError("ключ vault должен быть 32 байта")
        return key

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            raise VaultError(f"vault повреждён: {e}") from e
        if not isinstance(envelope, dict):
            raise VaultError("vault повреждён: ожидался объект")
        try:
            if int(envelope.get("version", 0)) != VAULT_VERSION:
                raise VaultError("неизвестная версия vault")
        except (TypeError, ValueError) as e:
            raise VaultError(f"vault повреждён: {e}") from e
        try:
            nonce_raw = envelope["nonce"]
            ciphertext_raw = envelope["ciphertext"]
            if not isinstance(nonce_raw, str) or not isinstance(ciphertext_raw, str):
                raise TypeError("nonce/ciphertext должны быть строками")
            nonce = base64.b64decode(nonce_raw)
            ciphertext = base64.b64decode(ciphertext_raw)
        except (KeyError, TypeError, ValueError) as e:
            raise VaultError(f"vault повреждён: {e}") from e
        key = self._get_key()
        try:
            plain = AESGCM(key).decrypt(nonce, ciphertext, AAD)
        except Exception as e:
            raise VaultError("не удалось расшифровать vault (ключ или файл)") from e
        try:
            data = json.loads(plain.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise VaultError(f"vault повреждён: {e}") from e
        if not isinstance(data, dict):
            raise VaultError("vault повреждён: ожидался объект")
        return {str(k): str(v) for k, v in data.items()}

    def save(self, data: dict[str, str]) -> None:
        key = self._get_or_create_key()
        nonce = os.urandom(12)
        plain = json.dumps(
            {str(k): str(v) for k, v in data.items()}, ensure_ascii=False
        ).encode("utf-8")
        ciphertext = AESGCM(key).encrypt(nonce, plain, AAD)
        envelope = {
            "version": VAULT_VERSION,
            "alg": "AES-256-GCM",
            "nonce": base64.b64encode(nonce).decode(),
            "ciphertext": base64.b64encode(ciphertext).decode(),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(self.path.parent, 0o700)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
        os.chmod(tmp, 0o600)
        os.replace(tmp, self.path)

    def get(self, key: str) -> Optional[str]:
        return self.load().get(key)

    def set(self, key: str, value: str) -> None:
        data = self.load()
        data[key] = value
        self.save(data)

    def delete(self, key: str) -> None:
        data = self.load()
        if key in data:
            del data[key]
            self.save(data)


_vault: Optional[Vault] = None


def get_vault() -> Vault:
    global _vault
    if _vault is None:
        _vault = Vault()
    return _vault


ENV_SECRET_KEYS = (
    "TELEGRAM_BOT_TOKEN",
    "OWNER_TELEGRAM_ID",
    "COOKIE_SECRET",
    "SECRET_PATH",
    "OPENCODE_SERVER_PASSWORD",
)


def _scan_env_secrets(env_path: Path) -> tuple[set[str], dict[str, str]]:
    """Присутствующие секреты и их первое непустое значение из .env.

    Возвращает (набор ключей, найденных в .env, первое непустое значение на ключ).
    Пустое значение (``KEY=``) — заглушка: ключ присутствует, но значения нет.
    """
    present: set[str] = set()
    values: dict[str, str] = {}
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k not in ENV_SECRET_KEYS:
            continue
        present.add(k)
        value = v.strip().strip('"').strip("'")
        if value and k not in values:
            values[k] = value
    return present, values


def migrate_env_secrets(vault: Vault, env_path: Path) -> list[str]:
    """Переносит ENV_SECRET_KEYS из .env в vault, чистит .env, chmod 600.

    Vault недоступен (Keychain/provider или OS-ошибка чтения vault, включая
    VaultError с первопричиной-OSError) — возвращает [] и не трогает .env.
    Vault повреждён (VaultError на decrypt/malformed envelope) — пробрасывается.
    Пустое значение в .env — заглушка: строка удаляется, в vault не пишется.
    .env трогается только после успешного save (секрет не теряется).
    """
    env_path = Path(env_path)
    if not env_path.exists():
        return []
    present, values = _scan_env_secrets(env_path)
    try:
        data = vault.load() if vault.exists() else {}
    except VaultError as e:
        # OS-ошибка чтения или нет ключа в Keychain — vault недоступен, .env не трогаем.
        # Повреждённый/неизвестный vault — пробрасываем (не теряем .env).
        msg = str(e)
        if isinstance(e.__cause__, OSError) or "нет ключа vault" in msg:
            log.warning("vault_unavailable")
            return []
        raise
    except Exception:
        log.warning("vault_unavailable")
        return []
    moved = [k for k in ENV_SECRET_KEYS if k in values]
    changed = False
    for key in moved:
        if key not in data:
            data[key] = values[key]
            changed = True
    if changed:
        try:
            vault.save(data)
        except Exception:
            # провайдер/Keychain не отдал ключ или запись упала: секрет не потерян,
            # .env ещё не тронут
            log.warning("vault_unavailable")
            return []
    # Vault доступен (load прошёл). Scrub .env только здесь — после успешного
    # чтения/записи, чтобы не потерять секреты при недоступном vault.
    if present:
        remove_env_keys(env_path, list(present))
    os.chmod(env_path, 0o600)
    return moved
