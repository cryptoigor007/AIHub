#!/usr/bin/env python3
"""CLI шифрованного хранилища секретов.

Команды: status | get KEY | set KEY [VALUE] | gen KEY [--len N] |
delete KEY | migrate [--env PATH] | reauth
Значения не логируются; get печатает значение в stdout (для скриптов).
"""

from __future__ import annotations

import argparse
import getpass
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.common.vault import (  # noqa: E402
    ENV_SECRET_KEYS,
    Vault,
    VaultError,
    get_vault,
    migrate_env_secrets,
)


def _check_key(key: str) -> bool:
    if key not in ENV_SECRET_KEYS:
        print(f"неизвестный ключ: {key}", file=sys.stderr)
        return False
    return True


def cmd_status(args) -> int:
    vault = args.vault
    print(f"vault: {'есть' if vault.exists() else 'нет'} ({vault.path})")
    if vault.exists():
        try:
            data = vault.load()
        except VaultError as e:
            print(f"ОШИБКА: {e}", file=sys.stderr)
            return 1
        for key in ENV_SECRET_KEYS:
            print(f"  {key}: {'задан' if data.get(key) else '—'}")
    return 0


def cmd_get(args) -> int:
    if not _check_key(args.key):
        return 2
    print(args.vault.get(args.key) or "")
    return 0


def cmd_set(args) -> int:
    if not _check_key(args.key):
        return 2
    value = args.value
    if value is None:
        value = getpass.getpass(f"{args.key}: ")
    if not value:
        print("пустое значение — не сохраняю", file=sys.stderr)
        return 2
    args.vault.set(args.key, value)
    # stderr: stdout в cmd_set должен оставаться чистым (тест требует,
    # что после set+get в stdout только значение; значение не печатаем).
    print(f"{args.key}: сохранено в vault", file=sys.stderr)
    return 0


def cmd_gen(args) -> int:
    if not _check_key(args.key):
        return 2
    args.vault.set(args.key, secrets.token_urlsafe(args.length))
    print(f"{args.key}: сгенерировано и сохранено в vault")
    return 0


def cmd_delete(args) -> int:
    if not _check_key(args.key):
        return 2
    args.vault.delete(args.key)
    print(f"{args.key}: удалено")
    return 0


def cmd_migrate(args) -> int:
    moved = migrate_env_secrets(args.vault, Path(args.env))
    print(f"перенесено из .env: {', '.join(moved) if moved else 'нечего'}")
    return 0


def cmd_reauth(args) -> int:
    """Пересоздать элемент Keychain тем же ключом (обновить ACL)."""
    provider = args.vault.provider
    key = provider.get_key()
    if key is None:
        print("ключа в Keychain нет", file=sys.stderr)
        return 1
    provider.delete_key()
    provider.set_key(key)
    print("Keychain: доступ перепривязан к текущему python")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="vault_cli", description="Хранилище секретов AIHub")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status"); s.set_defaults(func=cmd_status)
    s = sub.add_parser("get"); s.add_argument("key"); s.set_defaults(func=cmd_get)
    s = sub.add_parser("set"); s.add_argument("key"); s.add_argument("value", nargs="?"); s.set_defaults(func=cmd_set)
    s = sub.add_parser("gen"); s.add_argument("key"); s.add_argument("--len", dest="length", type=int, default=24); s.set_defaults(func=cmd_gen)
    s = sub.add_parser("delete"); s.add_argument("key"); s.set_defaults(func=cmd_delete)
    s = sub.add_parser("migrate"); s.add_argument("--env", default=".env"); s.set_defaults(func=cmd_migrate)
    s = sub.add_parser("reauth"); s.set_defaults(func=cmd_reauth)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "vault", None) is None:
        args.vault = get_vault()
    try:
        return int(args.func(args))
    except VaultError as e:
        print(f"ОШИБКА vault: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
