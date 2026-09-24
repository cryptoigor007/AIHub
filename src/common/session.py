"""Сессионные cookie (JWT-like через itsdangerous)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Optional

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from .config import get_settings
from .logging import get_logger

log = get_logger(__name__)

COOKIE_NAME = "aihub_session"
MAX_AGE_SEC = 7 * 24 * 3600  # 7 дней


def _cookie_secret() -> str:
    import os
    env = os.environ.get("COOKIE_SECRET", "").strip()
    if env:
        return env
    return get_settings().cookie_secret


def _owner_id() -> int:
    import os
    env = os.environ.get("OWNER_TELEGRAM_ID", "").strip()
    if env.isdigit():
        return int(env)
    return int(get_settings().owner_telegram_id)


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(
        secret_key=_cookie_secret(),
        salt="aihub-session-v1",
    )


def create_session_token(user_id: int, extra: Optional[dict[str, Any]] = None) -> str:
    payload = {"uid": user_id, **(extra or {})}
    return _serializer().dumps(payload)


def verify_session_token(token: str) -> Optional[dict[str, Any]]:
    try:
        data = _serializer().loads(token, max_age=MAX_AGE_SEC)
        if not isinstance(data, dict) or "uid" not in data:
            return None
        if int(data["uid"]) != _owner_id():
            return None
        return data
    except SignatureExpired:
        log.info("session_expired")
        return None
    except BadSignature:
        log.warning("session_bad_signature")
        return None
    except Exception as e:
        log.warning("session_verify_error", error=str(e))
        return None
