"""Проверка Telegram WebApp initData (HMAC-SHA256)."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import parse_qsl

from .config import get_settings
from .logging import get_logger

log = get_logger(__name__)


@dataclass
class TelegramUser:
    id: int
    first_name: str = ""
    last_name: str = ""
    username: str = ""
    language_code: str = ""
    is_premium: bool = False


@dataclass
class AuthResult:
    ok: bool
    user: Optional[TelegramUser] = None
    error: str = ""
    auth_date: int = 0


def _parse_init_data(init_data: str) -> dict[str, str]:
    return dict(parse_qsl(init_data, keep_blank_values=True))


def validate_init_data(init_data: str, max_age_sec: int = 300) -> AuthResult:
    """
    Проверяет initData по спецификации Telegram WebApp.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    settings = get_settings()
    token = settings.telegram_bot_token

    if not token:
        return AuthResult(ok=False, error="Токен бота ещё не задан")

    if not init_data or not init_data.strip():
        return AuthResult(ok=False, error="Пустой initData")

    try:
        data = _parse_init_data(init_data)
    except Exception as e:
        log.warning("init_data_parse_error", error=str(e))
        return AuthResult(ok=False, error="Некорректный initData")

    received_hash = data.pop("hash", None)
    if not received_hash:
        return AuthResult(ok=False, error="Отсутствует hash")

    # data-check-string
    pairs = sorted(f"{k}={v}" for k, v in data.items())
    data_check_string = "\n".join(pairs)

    secret_key = hmac.new(
        b"WebAppData",
        token.encode("utf-8"),
        hashlib.sha256,
    ).digest()

    calculated = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated, received_hash):
        return AuthResult(ok=False, error="Неверная подпись")

    auth_date = int(data.get("auth_date", "0") or "0")
    now = int(time.time())
    if auth_date <= 0 or (now - auth_date) > max_age_sec:
        return AuthResult(ok=False, error="Данные устарели", auth_date=auth_date)

    user_raw = data.get("user")
    if not user_raw:
        return AuthResult(ok=False, error="Нет данных пользователя")

    try:
        user_dict: dict[str, Any] = json.loads(user_raw)
    except json.JSONDecodeError:
        return AuthResult(ok=False, error="Некорректный JSON пользователя")

    user_id = int(user_dict.get("id", 0))
    if user_id != settings.owner_telegram_id:
        return AuthResult(
            ok=False,
            error="Доступ запрещён",
            user=TelegramUser(
                id=user_id,
                first_name=str(user_dict.get("first_name", "")),
                last_name=str(user_dict.get("last_name", "")),
                username=str(user_dict.get("username", "")),
            ),
            auth_date=auth_date,
        )

    user = TelegramUser(
        id=user_id,
        first_name=str(user_dict.get("first_name", "")),
        last_name=str(user_dict.get("last_name", "")),
        username=str(user_dict.get("username", "")),
        language_code=str(user_dict.get("language_code", "")),
        is_premium=bool(user_dict.get("is_premium", False)),
    )
    return AuthResult(ok=True, user=user, auth_date=auth_date)
