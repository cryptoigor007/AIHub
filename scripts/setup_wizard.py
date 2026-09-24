#!/usr/bin/env python3
"""Мастер первого запуска: Telegram + шифрованное хранилище секретов."""

from __future__ import annotations

import argparse
import getpass
import os
import secrets
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from src.common.envfile import read_env_value, upsert_env  # noqa: E402
from src.common.vault import (  # noqa: E402
    Vault,
    VaultError,
    get_vault,
    migrate_env_secrets,
)

TG_API = "https://api.telegram.org"


class TelegramClient:
    def __init__(self, base: str = TG_API, transport=None) -> None:
        self.base = base
        self._transport = transport

    def _client(self, timeout: float = 15.0) -> httpx.Client:
        return httpx.Client(timeout=timeout, transport=self._transport)

    def get_me(self, token: str) -> Optional[dict]:
        try:
            with self._client() as c:
                r = c.get(f"{self.base}/bot{token}/getMe")
                data = r.json()
                return data.get("result") if data.get("ok") else None
        except Exception:
            return None

    def detect_owner_id(self, token: str, timeout_sec: int = 120, sleep=time.sleep) -> Optional[int]:
        offset = 0
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            try:
                with self._client(20.0) as c:
                    r = c.get(
                        f"{self.base}/bot{token}/getUpdates",
                        params={"offset": offset, "timeout": 5},
                    )
                    data = r.json()
                    if not data.get("ok"):
                        return None  # webhook/неверный токен — на ручной ввод
                    for upd in data.get("result", []):
                        offset = max(offset, int(upd.get("update_id", 0)) + 1)
                        msg = upd.get("message") or upd.get("edited_message") or {}
                        chat = msg.get("chat") or {}
                        if chat.get("type") == "private" and chat.get("id"):
                            return int(chat["id"])
            except Exception:
                pass
            sleep(1)
        return None

    def send_message(self, token: str, chat_id: int, text: str) -> bool:
        try:
            with self._client() as c:
                r = c.post(
                    f"{self.base}/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": text},
                )
                return bool(r.json().get("ok"))
        except Exception:
            return False


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{prompt}{suffix}: ").strip() or default


def ask_secret(prompt: str) -> str:
    return getpass.getpass(f"{prompt}: ").strip()


def _step(n: int, title: str) -> None:
    print(f"\n── Шаг {n}: {title} ──")


def _preflight() -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []
    checks.append(("macOS", sys.platform == "darwin", "Keychain доступен только на macOS"))
    checks.append(("python", True, sys.version.split()[0]))
    checks.append(("dsh в PATH", shutil.which("dsh") is not None, "npm i -g @deepseek-ai/dsh"))
    checks.append(("opencode в PATH", shutil.which("opencode") is not None, "brew install opencode"))
    ts = shutil.which("tailscale") is not None
    checks.append(("tailscale (опц.)", ts, "нужен для доступа вне дома"))
    log = Path(os.environ.get("DSH_WEB_LOG", Path.home() / ".dsh" / "web.log"))
    checks.append(("dsh web.log", log.exists(), "запустите dsh web"))
    return checks


def _print_preflight() -> None:
    _step(0, "Проверка окружения")
    for name, ok, hint in _preflight():
        mark = "✓" if ok else "✗"
        extra = "" if ok else f" — {hint}"
        print(f"  {mark} {name}{extra}")


def run_wizard(
    *,
    prompt: Callable[..., str] = ask,
    prompt_secret: Callable[[str], str] = ask_secret,
    telegram: Optional[TelegramClient] = None,
    vault: Optional[Vault] = None,
    env_path: Path = Path(".env"),
    start_services: Optional[Callable[[], None]] = None,
    interactive: bool = True,
    force: bool = False,
) -> int:
    vault = vault or get_vault()
    telegram = telegram or TelegramClient()
    env_path = Path(env_path)

    if interactive:
        _print_preflight()

    configured = False
    try:
        data = vault.load() if vault.exists() else {}
        configured = bool(data.get("TELEGRAM_BOT_TOKEN") and data.get("OWNER_TELEGRAM_ID"))
    except VaultError as e:
        print(f"ОШИБКА хранилища: {e}")
        return 1

    if configured and not force:
        print("\nAIHub уже настроен:")
        print(f"  бот: {'да' if data.get('TELEGRAM_BOT_TOKEN') else 'нет'}")
        print(f"  владелец: {'да' if data.get('OWNER_TELEGRAM_ID') else 'нет'}")
        print("  перезапуск мастера: ./scripts/setup.sh --force")
        return 0

    if interactive:
        _step(1, "Вступление")
        print("  Секреты будут зашифрованы (data/vault.enc), ключ — в Keychain.")
        print("  Данные уходят только на api.telegram.org. В чат/логи они не пишутся.")

        _step(2, "Telegram: создание бота")
        print("  1. Открой Telegram → @BotFather → команда /newbot")
        print("  2. Задай имя и username (заканчивается на _bot)")
        print("  3. BotFather пришлёт токен вида 123456:AA... — скопируй его")

    token = prompt_secret("Вставь токен бота (ввод скрыт)")
    if not token:
        print("Токен не введён — выходим.")
        return 1
    me = telegram.get_me(token)
    if not me:
        print("Токен не прошёл проверку getMe — проверь и запусти мастер снова.")
        return 1
    print(f"  ✓ Бот: {me.get('first_name', '')} @{me.get('username', '')}")

    if interactive:
        _step(3, "Telegram: доступ владельца")
        print(f"  Открой своего бота @{me.get('username', '')} в Telegram и нажми Start.")
        print("  Жду сообщение до 120 секунд...")
    owner_id = telegram.detect_owner_id(token, timeout_sec=120 if interactive else 0)
    if owner_id is None:
        if interactive:
            print("  Не увидел сообщение. Можно ввести ID вручную (узнать: @userinfobot).")
        raw = prompt("Твой Telegram ID", default="")
        try:
            owner_id = int(raw) if raw else None
        except ValueError:
            owner_id = None
    if not owner_id:
        print("Не удалось определить владельца — выходим, ничего не сохранено.")
        return 1
    print(f"  ✓ Владелец: {owner_id}")

    if not telegram.send_message(token, owner_id, "AIHub настроен ✅"):
        print("  ⚠ Тестовое сообщение не ушло (бот не может писать первым — нажми Start у бота)")

    migrated = migrate_env_secrets(vault, env_path)
    vault.set("TELEGRAM_BOT_TOKEN", token)
    vault.set("OWNER_TELEGRAM_ID", str(owner_id))
    if migrated:
        print(f"  ✓ Перенесено из .env в vault: {', '.join(migrated)}")

    if not vault.get("COOKIE_SECRET"):
        vault.set("COOKIE_SECRET", secrets.token_urlsafe(32))
    if not vault.get("SECRET_PATH"):
        vault.set("SECRET_PATH", "/p/" + secrets.token_urlsafe(12))
    if not vault.get("OPENCODE_SERVER_PASSWORD"):
        vault.set("OPENCODE_SERVER_PASSWORD", secrets.token_urlsafe(24))

    upsert_env(env_path, "ENV", "production")
    upsert_env(env_path, "LOCAL_LOGIN", "loopback")
    if read_env_value(env_path, "NETWORK_MODE") == "":
        upsert_env(env_path, "NETWORK_MODE", "hybrid")
    os.chmod(env_path, 0o600)

    if interactive and shutil.which("tailscale") and not read_env_value(env_path, "PUBLIC_URL"):
        answer = prompt("Настроить доступ вне дома (Tailscale Serve) сейчас? (y/N)", default="n")
        if answer.strip().lower() in ("y", "yes", "д", "да"):
            subprocess.run(
                [str(ROOT / "scripts" / "enable_tailscale_serve.sh")], check=False
            )

    if interactive:
        _step(4, "Итог")
        print("  Секреты — в data/vault.enc (ключ в Keychain). В .env секретов нет.")
        print("  Дома: открой на Mac http://127.0.0.1:8787 + secret path (см. ./scripts/status.sh).")
        print("  С телефона: кнопка в боте (вне дома — включи Tailscale).")
        print("  Внешний доступ: ./scripts/enable_tailscale_serve.sh")

    if start_services is not None:
        start_services()
    return 0


def _default_start_services() -> None:
    script = ROOT / "scripts" / "restart.sh"
    if script.exists():
        subprocess.run([str(script)], check=False)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="setup_wizard")
    p.add_argument("--force", action="store_true", help="перенастроить заново")
    args = p.parse_args(argv)
    try:
        return run_wizard(force=args.force, start_services=_default_start_services)
    except KeyboardInterrupt:
        print("\nПрервано.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
