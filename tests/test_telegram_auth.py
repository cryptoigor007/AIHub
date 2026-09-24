"""Тесты auth/session: standalone без тяжёлых deps; integration — skip если нет пакетов."""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import os
import time

import pytest

OWNER = 123456789
SECRET = "test-secret-key-for-unit-tests-32b"
SALT = "aihub-session-v1"

HAS_ITS = importlib.util.find_spec("itsdangerous") is not None
HAS_PS = importlib.util.find_spec("pydantic_settings") is not None


def test_init_data_hmac_shape():
    bot_token = "123456:ABC-DEF"
    user = '{"id":123456789,"first_name":"T"}'
    auth_date = str(int(time.time()))
    fields = {"auth_date": auth_date, "user": user, "query_id": "AA"}
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    digest = hmac.new(secret_key, data_check.encode(), hashlib.sha256).hexdigest()
    assert len(digest) == 64


@pytest.mark.skipif(not HAS_ITS, reason="itsdangerous not installed")
def test_session_roundtrip_itsdangerous():
    from itsdangerous import URLSafeTimedSerializer

    s = URLSafeTimedSerializer(SECRET, salt=SALT)
    tok = s.dumps({"uid": OWNER})
    data = s.loads(tok, max_age=7 * 24 * 3600)
    assert data["uid"] == OWNER


@pytest.mark.skipif(not HAS_ITS, reason="itsdangerous not installed")
def test_session_wrong_user_payload():
    from itsdangerous import URLSafeTimedSerializer

    s = URLSafeTimedSerializer(SECRET, salt=SALT)
    bad = s.dumps({"uid": 999})
    data = s.loads(bad, max_age=7 * 24 * 3600)
    assert data["uid"] == 999


@pytest.mark.skipif(not HAS_PS, reason="pydantic_settings not installed")
def test_validate_init_data_empty_token_integration():
    os.environ.setdefault("COOKIE_SECRET", SECRET)
    os.environ.setdefault("SECRET_PATH", "/p/test")
    os.environ["TELEGRAM_BOT_TOKEN"] = ""
    from src.common.config import clear_settings_cache
    from src.common.telegram_auth import validate_init_data

    clear_settings_cache()
    r = validate_init_data("query_id=1&user=%7B%22id%22%3A1%7D&auth_date=1&hash=abc")
    assert r.ok is False


@pytest.mark.skipif(not (HAS_PS and HAS_ITS), reason="full stack not installed")
def test_session_module_roundtrip_integration():
    os.environ["COOKIE_SECRET"] = SECRET
    os.environ["OWNER_TELEGRAM_ID"] = str(OWNER)
    from src.common.config import clear_settings_cache
    from src.common.session import create_session_token, verify_session_token

    clear_settings_cache()
    tok = create_session_token(OWNER)
    data = verify_session_token(tok)
    assert data is not None
    assert data["uid"] == OWNER


if __name__ == "__main__":
    test_init_data_hmac_shape()
    if HAS_ITS:
        test_session_roundtrip_itsdangerous()
        test_session_wrong_user_payload()
    print("OK")
