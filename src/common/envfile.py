"""Чтение/запись .env — единый источник правды для config и tunnel-watcher."""

from __future__ import annotations

from pathlib import Path


def read_env_value(path: Path, key: str, default: str = "") -> str:
    """Значение KEY из .env (кавычки снимаются). default, если ключа нет."""
    path = Path(path)
    if not path.exists():
        return default
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            return v.strip().strip('"').strip("'")
    return default


def upsert_env(path: Path, key: str, value: str) -> None:
    """Ставит KEY=value: обновляет существующую строку или добавляет в конец."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    out: list[str] = []
    found = False
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            out.append(raw)
            continue
        k, _, _ = line.partition("=")
        if k.strip() == key:
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(raw)
    if not found:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def remove_env_keys(path: Path, keys: list[str]) -> list[str]:
    """Удаляет строки KEY=... для перечисленных ключей. Возвращает найденные."""
    path = Path(path)
    if not path.exists():
        return []
    wanted = set(keys)
    removed: list[str] = []
    out: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, _ = line.partition("=")
            k = k.strip()
            if k in wanted:
                if k not in removed:
                    removed.append(k)
                continue
        out.append(raw)
    if removed:
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
    return removed
