"""Ключ vault в macOS Keychain (ctypes, Security.framework).

Ключ — 32 случайных байта, хранится как generic password. ACL элемента
привязывает доступ к приложению, создавшему элемент (python из .venv);
другие программы при чтении получают системный запрос.

Item-ссылки, возвращаемые Find/Add, удерживаются вызывающим
(CF_RETURNS_RETAINED) и освобождаются через CFRelease (CoreFoundation).
"""

from __future__ import annotations

import ctypes
import ctypes.util
import sys
from typing import Optional

from .logging import get_logger

log = get_logger(__name__)

SERVICE = "ai.aihub.vault"
ACCOUNT = "vault-key-v1"
ERR_SEC_SUCCESS = 0
ERR_SEC_ITEM_NOT_FOUND = -25300
ERR_SEC_DUPLICATE_ITEM = -25299

# Важные OSStatus -> понятный текст; числовой статус сохраняется в сообщении.
_STATUS_TEXT = {
    -25293: "отказ аутентификации Keychain",
    -25308: "взаимодействие с Keychain запрещено (Keychain заблокирован/disabled)",
    -128: "операция отменена пользователем",
}


class KeychainError(Exception):
    """Keychain недоступен (не macOS, отказ доступа, ошибка Security)."""


def _keychain_error(op: str, status: int) -> KeychainError:
    text = _STATUS_TEXT.get(status)
    if text is not None:
        return KeychainError(f"Keychain {op}: {text} (OSStatus {status})")
    return KeychainError(f"Keychain {op}: ошибка Security (OSStatus {status})")


def _security():
    if sys.platform != "darwin":
        raise KeychainError("Keychain доступен только на macOS")
    path = ctypes.util.find_library("Security")
    if not path:
        raise KeychainError("Security.framework не найден")
    cf_path = ctypes.util.find_library("CoreFoundation")
    if not cf_path:
        raise KeychainError("CoreFoundation.framework не найден")
    try:
        lib = ctypes.cdll.LoadLibrary(path)
        cf = ctypes.cdll.LoadLibrary(cf_path)
    except OSError as e:
        raise KeychainError(f"не удалось загрузить Security/CoreFoundation: {e}") from e
    try:
        lib.CFRelease = cf.CFRelease
        lib.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        lib.SecKeychainFindGenericPassword.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
            ctypes.c_uint32, ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        lib.SecKeychainAddGenericPassword.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
            ctypes.c_uint32, ctypes.c_char_p,
            ctypes.c_uint32, ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p),
        ]
        lib.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
        lib.SecKeychainItemModifyAttributesAndData.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p,
        ]
        lib.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        lib.SecKeychainItemDelete.restype = ctypes.c_int32
        lib.SecKeychainItemDelete.argtypes = [ctypes.c_void_p]
        lib.CFRelease.restype = None
        lib.CFRelease.argtypes = [ctypes.c_void_p]
    except AttributeError as e:
        raise KeychainError(
            f"функция Security/CoreFoundation не найдена: {e}"
        ) from e
    return lib


class KeychainKeyProvider:
    def __init__(self, service: str = SERVICE, account: str = ACCOUNT) -> None:
        self.service = service
        self.account = account
        self._lib = None

    @property
    def lib(self):
        if self._lib is None:
            self._lib = _security()
        return self._lib

    def _release(self, ref: Optional[int]) -> None:
        if ref:
            self.lib.CFRelease(ctypes.c_void_p(ref))

    def _find(self) -> tuple[Optional[int], Optional[bytes]]:
        length = ctypes.c_uint32(0)
        data = ctypes.c_void_p()
        item = ctypes.c_void_p()
        status = self.lib.SecKeychainFindGenericPassword(
            None,
            len(self.service), self.service.encode(),
            len(self.account), self.account.encode(),
            ctypes.byref(length), ctypes.byref(data), ctypes.byref(item),
        )
        if status == ERR_SEC_ITEM_NOT_FOUND:
            return None, None
        if status != ERR_SEC_SUCCESS:
            raise _keychain_error("find", status)
        try:
            value = ctypes.string_at(data, length.value)
        finally:
            self.lib.SecKeychainItemFreeContent(None, data)
        return item.value, value

    def get_key(self) -> Optional[bytes]:
        item, value = self._find()
        if value is None:
            return None
        try:
            return bytes(value)
        finally:
            self._release(item)

    def set_key(self, key: bytes) -> None:
        item, _ = self._find()
        if item is not None:
            try:
                status = self.lib.SecKeychainItemModifyAttributesAndData(
                    item, None, len(key), key
                )
            finally:
                self._release(item)
            if status != ERR_SEC_SUCCESS:
                raise _keychain_error("update", status)
            return
        item = ctypes.c_void_p()
        status = self.lib.SecKeychainAddGenericPassword(
            None,
            len(self.service), self.service.encode(),
            len(self.account), self.account.encode(),
            len(key), key, ctypes.byref(item),
        )
        if status == ERR_SEC_DUPLICATE_ITEM:
            # гонка: элемент появился между find и add — обновляем
            self.set_key(key)
            return
        if status != ERR_SEC_SUCCESS:
            raise _keychain_error("add", status)
        self._release(item.value)

    def delete_key(self) -> None:
        item, _ = self._find()
        if item is None:
            return
        try:
            status = self.lib.SecKeychainItemDelete(item)
        finally:
            self._release(item)
        if status != ERR_SEC_SUCCESS:
            raise _keychain_error("delete", status)


def get_key_provider() -> KeychainKeyProvider:
    if sys.platform != "darwin":
        raise KeychainError("Keychain доступен только на macOS")
    return KeychainKeyProvider()