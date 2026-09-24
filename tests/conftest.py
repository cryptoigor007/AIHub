"""Обеспечивает cache_clear settings между тестами."""
from __future__ import annotations
import os
import pytest

os.environ.setdefault("COOKIE_SECRET", "test-secret-key-for-unit-tests-32b")
os.environ.setdefault("SECRET_PATH", "/p/testsecret")
os.environ.setdefault("OWNER_TELEGRAM_ID", "123456789")
os.environ.setdefault("NETWORK_MODE", "hybrid")
os.environ.setdefault("GATEKEEPER_HOST", "127.0.0.1")


@pytest.fixture(autouse=True)
def _clear_settings():
    try:
        from src.common.config import clear_settings_cache
        clear_settings_cache()
    except Exception:
        pass
    yield
    try:
        from src.common.config import clear_settings_cache
        clear_settings_cache()
    except Exception:
        pass
