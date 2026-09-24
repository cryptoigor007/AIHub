"""Общие фейки для тестов (без Keychain, без сети)."""
from __future__ import annotations

from typing import Any, Optional


class FakeKeyProvider:
    """KeyProvider в памяти: ключ не покидает процесс теста."""

    def __init__(self) -> None:
        self.key: Optional[bytes] = None

    def get_key(self) -> Optional[bytes]:
        return self.key

    def set_key(self, key: bytes) -> None:
        self.key = key

    def delete_key(self) -> None:
        self.key = None


_DEFAULT_ME: dict[str, Any] = {"id": 1, "username": "test_bot", "first_name": "T"}

# Сентинел: отличает FakeTelegramClient() (бот по умолчанию)
# от FakeTelegramClient(me=None) (эмуляция неверного токена).
_UNSET: Any = object()


class FakeTelegramClient:
    """TelegramClient без сети."""

    def __init__(
        self,
        me: Optional[dict[str, Any]] | Any = _UNSET,
        owner_id: Optional[int] = 555,
        send_ok: bool = True,
    ) -> None:
        self.me = _DEFAULT_ME if me is _UNSET else me
        self.owner_id = owner_id
        self.send_ok = send_ok
        self.sent: list[tuple[int, str]] = []

    def get_me(self, token: str) -> Optional[dict[str, Any]]:
        return self.me

    def detect_owner_id(self, token: str, timeout_sec: int = 120, sleep=None) -> Optional[int]:
        return self.owner_id

    def send_message(self, token: str, chat_id: int, text: str) -> bool:
        self.sent.append((chat_id, text))
        return self.send_ok
