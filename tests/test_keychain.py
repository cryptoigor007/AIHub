"""Keychain-провайдер: интерфейс, фейковый lib, opt-in реальный Keychain."""
from __future__ import annotations

import ctypes
import os
import secrets
import sys

import pytest

from src.common import keychain
from src.common.keychain import (
    ERR_SEC_DUPLICATE_ITEM,
    ERR_SEC_ITEM_NOT_FOUND,
    KeychainError,
    KeychainKeyProvider,
    get_key_provider,
)

# Синтетический ключ для фейковых тестов (не реальный vault-ключ).
KEY = b"\x5a" * 32


def test_provider_interface():
    p = KeychainKeyProvider(service="ai.aihub.vault.test")
    assert hasattr(p, "get_key") and hasattr(p, "set_key") and hasattr(p, "delete_key")


@pytest.mark.skipif(sys.platform != "darwin", reason="только macOS")
def test_real_keychain_opt_in():
    if os.environ.get("AIHUB_TEST_KEYCHAIN") != "1":
        pytest.skip("реальный Keychain: включить AIHUB_TEST_KEYCHAIN=1")
    p = KeychainKeyProvider(service="ai.aihub.vault.test", account="test-key")
    p.delete_key()
    assert p.get_key() is None
    key = os.urandom(32)
    p.set_key(key)
    stored = p.get_key()
    if stored is None or not secrets.compare_digest(stored, key):
        pytest.fail("Keychain round-trip mismatch")
    p.delete_key()
    assert p.get_key() is None


def test_get_key_provider_returns_provider():
    if sys.platform != "darwin":
        with pytest.raises(KeychainError):
            get_key_provider()
    else:
        assert get_key_provider() is not None


class _SecStub:
    """Подделка Security.framework: планируемые результаты вызовов."""

    def __init__(self) -> None:
        self.find_queue: list[tuple[int, bytes, bool]] = []
        self.item_handle = 0xDEADBEEF
        self.add_status = 0
        self.update_status = 0
        self.delete_status = 0
        self.calls: list[tuple] = []
        self._buf = None

    def plan_find(self, status: int, data: bytes = b"", found: bool = False) -> None:
        self.find_queue.append((status, data, found))

    def SecKeychainFindGenericPassword(
        self, keychain, slen, srv, alen, acct, plen, pdata, pitem
    ):
        self.calls.append(("find", srv))
        status, data, found = (
            self.find_queue.pop(0)
            if self.find_queue
            else (ERR_SEC_ITEM_NOT_FOUND, b"", False)
        )
        plen._obj.value = len(data)
        if status == 0:
            buf = ctypes.create_string_buffer(data or b"\x00")
            self._buf = buf
            pdata._obj.value = ctypes.addressof(buf)
            pitem._obj.value = self.item_handle if found else 0
        else:
            pdata._obj.value = 0
            pitem._obj.value = 0
        return status

    def SecKeychainItemFreeContent(self, attrs, data):
        self.calls.append(("free_content",))

    def SecKeychainAddGenericPassword(
        self, keychain, slen, srv, alen, acct, klen, key, pitem
    ):
        self.calls.append(("add", srv, acct, klen))
        if self.add_status == 0:
            pitem._obj.value = self.item_handle
        return self.add_status

    def SecKeychainItemModifyAttributesAndData(self, item, attrs, klen, key):
        self.calls.append(("update", item))
        return self.update_status

    def SecKeychainItemDelete(self, item):
        self.calls.append(("delete", item))
        return self.delete_status

    def CFRelease(self, ref):
        self.calls.append(("release", ref.value))


def _provider(stub: _SecStub) -> KeychainKeyProvider:
    p = KeychainKeyProvider(service="s", account="a")
    p._lib = stub
    return p


def test_get_key_not_found_returns_none():
    stub = _SecStub()
    stub.plan_find(ERR_SEC_ITEM_NOT_FOUND)
    p = _provider(stub)
    assert p.get_key() is None
    assert ("find", b"s") in stub.calls
    assert not any(c[0] == "release" for c in stub.calls)


def test_get_key_returns_value_and_releases_item():
    stub = _SecStub()
    stub.plan_find(0, data=KEY, found=True)
    p = _provider(stub)
    assert p.get_key() == KEY
    assert ("release", stub.item_handle) in stub.calls
    assert ("free_content",) in stub.calls


def test_set_key_adds_when_missing():
    stub = _SecStub()
    stub.plan_find(ERR_SEC_ITEM_NOT_FOUND)
    p = _provider(stub)
    p.set_key(KEY)
    assert any(c[0] == "add" and c[3] == len(KEY) for c in stub.calls)
    assert ("release", stub.item_handle) in stub.calls


def test_set_key_updates_when_exists():
    stub = _SecStub()
    stub.plan_find(0, data=KEY, found=True)
    p = _provider(stub)
    p.set_key(KEY)
    assert any(c[0] == "update" for c in stub.calls)
    assert not any(c[0] == "add" for c in stub.calls)
    assert ("release", stub.item_handle) in stub.calls


def test_set_key_duplicate_race_updates():
    stub = _SecStub()
    stub.plan_find(ERR_SEC_ITEM_NOT_FOUND)
    stub.add_status = ERR_SEC_DUPLICATE_ITEM
    stub.plan_find(0, data=KEY, found=True)
    p = _provider(stub)
    p.set_key(KEY)
    assert any(c[0] == "add" for c in stub.calls)
    assert any(c[0] == "update" for c in stub.calls)
    # реф освобождается ровно один раз (add не создал item)
    assert [c for c in stub.calls if c[0] == "release"] == [
        ("release", stub.item_handle)
    ]


def test_delete_key_noop_when_missing():
    stub = _SecStub()
    stub.plan_find(ERR_SEC_ITEM_NOT_FOUND)
    p = _provider(stub)
    p.delete_key()
    assert not any(c[0] == "delete" for c in stub.calls)
    assert not any(c[0] == "release" for c in stub.calls)


def test_delete_key_deletes_and_releases():
    stub = _SecStub()
    stub.plan_find(0, data=KEY, found=True)
    p = _provider(stub)
    p.delete_key()
    assert ("delete", stub.item_handle) in stub.calls
    assert ("release", stub.item_handle) in stub.calls


def test_get_key_error_raises_with_text_and_status():
    stub = _SecStub()
    stub.plan_find(-25293)
    p = _provider(stub)
    with pytest.raises(KeychainError) as ei:
        p.get_key()
    msg = str(ei.value)
    assert "аутентификац" in msg
    assert "-25293" in msg


def test_unknown_status_keeps_numeric_diagnostics():
    stub = _SecStub()
    stub.plan_find(-3456)
    p = _provider(stub)
    with pytest.raises(KeychainError) as ei:
        p.get_key()
    msg = str(ei.value)
    assert "Keychain find" in msg
    assert "-3456" in msg


def test_set_key_add_error_raises():
    stub = _SecStub()
    stub.plan_find(ERR_SEC_ITEM_NOT_FOUND)
    stub.add_status = -25308
    p = _provider(stub)
    with pytest.raises(KeychainError) as ei:
        p.set_key(KEY)
    msg = str(ei.value)
    assert "взаимодейств" in msg
    assert "-25308" in msg


def test_set_key_update_error_raises():
    stub = _SecStub()
    stub.plan_find(0, data=KEY, found=True)
    stub.update_status = -25308
    p = _provider(stub)
    with pytest.raises(KeychainError) as ei:
        p.set_key(KEY)
    assert "взаимодейств" in str(ei.value)


def test_delete_key_error_raises():
    stub = _SecStub()
    stub.plan_find(0, data=KEY, found=True)
    stub.delete_status = -128
    p = _provider(stub)
    with pytest.raises(KeychainError) as ei:
        p.delete_key()
    msg = str(ei.value)
    assert "пользовател" in msg
    assert "-128" in msg


@pytest.mark.skipif(sys.platform != "darwin", reason="загрузка Security только на macOS")
def test_security_framework_missing(monkeypatch):
    monkeypatch.setattr("ctypes.util.find_library", lambda name: None)
    with pytest.raises(KeychainError, match="Security.framework не найден"):
        keychain._security()


@pytest.mark.skipif(sys.platform != "darwin", reason="загрузка Security только на macOS")
def test_security_corefoundation_missing(monkeypatch):
    def fake_find(name):
        return (
            "/System/Library/Frameworks/Security.framework/Security"
            if name == "Security"
            else None
        )

    monkeypatch.setattr("ctypes.util.find_library", fake_find)
    with pytest.raises(KeychainError, match="CoreFoundation.framework не найден"):
        keychain._security()


@pytest.mark.skipif(sys.platform != "darwin", reason="загрузка Security только на macOS")
def test_security_load_failure_wrapped(monkeypatch):
    def boom(path):
        raise OSError("dlsym: symbol not found")

    monkeypatch.setattr("ctypes.cdll.LoadLibrary", boom)
    with pytest.raises(KeychainError, match="не удалось загрузить"):
        keychain._security()


@pytest.mark.skipif(sys.platform != "darwin", reason="загрузка Security только на macOS")
def test_security_symbol_missing_wrapped(monkeypatch):
    class _BareCDLL:
        def __getattr__(self, name):
            raise AttributeError(f"symbol {name} missing")

    monkeypatch.setattr("ctypes.cdll.LoadLibrary", lambda path: _BareCDLL())
    with pytest.raises(KeychainError, match="не найдена"):
        keychain._security()