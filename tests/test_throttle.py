"""Тесты троттлинга уведомлений (файл-флаг с TTL)."""
from __future__ import annotations

from src.common.throttle import mark_notified, notification_due


def test_due_when_missing(tmp_path):
    assert notification_due(tmp_path / ".flag", ttl_sec=3600, now=1000.0)


def test_not_due_right_after_mark(tmp_path):
    flag = tmp_path / ".flag"
    mark_notified(flag, now=1000.0)
    assert not notification_due(flag, ttl_sec=3600, now=1001.0)


def test_due_after_ttl(tmp_path):
    flag = tmp_path / ".flag"
    mark_notified(flag, now=1000.0)
    assert notification_due(flag, ttl_sec=3600, now=1000.0 + 3601)


def test_corrupt_flag_is_due(tmp_path):
    flag = tmp_path / ".flag"
    flag.write_text("not-a-number", encoding="utf-8")
    assert notification_due(flag, ttl_sec=3600, now=1000.0)


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        test_due_when_missing(Path(d))
    print("OK")
