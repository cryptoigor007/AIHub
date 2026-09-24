"""Тесты .env-хелперов: единый источник правды для config и watcher."""
from __future__ import annotations

from src.common.envfile import read_env_value, upsert_env


def test_upsert_creates_file(tmp_path):
    p = tmp_path / ".env"
    upsert_env(p, "PUBLIC_URL", "https://x.ts.net")
    assert p.read_text(encoding="utf-8") == "PUBLIC_URL=https://x.ts.net\n"


def test_upsert_replaces_existing(tmp_path):
    p = tmp_path / ".env"
    p.write_text("A=1\nPUBLIC_URL=https://old.ts.net\nB=2\n", encoding="utf-8")
    upsert_env(p, "PUBLIC_URL", "https://new.ts.net")
    text = p.read_text(encoding="utf-8")
    assert "https://new.ts.net" in text
    assert "https://old.ts.net" not in text
    assert "A=1" in text and "B=2" in text


def test_upsert_handles_spaces(tmp_path):
    p = tmp_path / ".env"
    p.write_text("PUBLIC_URL = old\n", encoding="utf-8")
    upsert_env(p, "PUBLIC_URL", "new")
    assert p.read_text(encoding="utf-8").strip() == "PUBLIC_URL=new"


def test_read_env_value(tmp_path):
    p = tmp_path / ".env"
    p.write_text('A="quoted"\nB=plain\n# C=commented\n', encoding="utf-8")
    assert read_env_value(p, "A") == "quoted"
    assert read_env_value(p, "B") == "plain"
    assert read_env_value(p, "C") == ""
    assert read_env_value(p, "MISSING") == ""
    assert read_env_value(p, "B", default="d") == "plain"


def test_read_env_value_missing_file(tmp_path):
    assert read_env_value(tmp_path / "nope", "A") == ""


def test_remove_env_keys(tmp_path):
    from src.common.envfile import remove_env_keys
    p = tmp_path / ".env"
    p.write_text("A=1\nTELEGRAM_BOT_TOKEN=x\nB=2\nCOOKIE_SECRET=y\n", encoding="utf-8")
    removed = remove_env_keys(p, ["TELEGRAM_BOT_TOKEN", "COOKIE_SECRET", "MISSING"])
    assert set(removed) == {"TELEGRAM_BOT_TOKEN", "COOKIE_SECRET"}
    text = p.read_text(encoding="utf-8")
    assert "TELEGRAM_BOT_TOKEN" not in text
    assert "A=1" in text and "B=2" in text


def test_remove_env_keys_removes_duplicates_and_empty_values(tmp_path):
    from src.common.envfile import remove_env_keys
    p = tmp_path / ".env"
    p.write_text("A=1\nA=2\nKEEP=1\nA=\n", encoding="utf-8")
    removed = remove_env_keys(p, ["A"])
    assert removed == ["A"]  # ключ возвращается один раз
    text = p.read_text(encoding="utf-8")
    assert "A" not in text  # все строки ключа, включая пустое значение
    assert "KEEP=1" in text


if __name__ == "__main__":
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as d:
        test_upsert_creates_file(Path(d))
    print("OK")
