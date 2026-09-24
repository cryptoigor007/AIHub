#!/usr/bin/env python3
"""Проверка .env и доступности зависимостей при старте."""
from __future__ import annotations
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main() -> int:
    from src.common.config import get_settings
    from src.common.netinfo import lan_http_urls

    s = get_settings()
    s.ensure_secrets()
    s.ensure_dirs()
    errors: list[str] = []
    warnings: list[str] = []
    if not s.telegram_bot_token:
        warnings.append("TELEGRAM_BOT_TOKEN пуст — auth недоступен до заполнения")
    if not s.cookie_secret:
        errors.append("COOKIE_SECRET не сгенерирован")
    if not s.secret_path or "xxxx" in s.secret_path:
        errors.append("SECRET_PATH невалиден")

    mode = (getattr(s, "network_mode", "hybrid") or "hybrid").strip().lower()
    mesh_modes = ("hybrid", "tailscale", "mesh", "ts")
    host_disp = "127.0.0.1" if s.gatekeeper_host in ("0.0.0.0", "::") else s.gatekeeper_host
    lans = lan_http_urls(s.gatekeeper_port, s.secret_path)

    if mode in mesh_modes and not shutil.which("tailscale"):
        if mode == "tailscale":
            errors.append(
                "NETWORK_MODE=tailscale, но tailscale CLI не найден — mesh не поднимется "
                "(https://tailscale.com/download/mac)"
            )
        else:
            warnings.append(
                "tailscale не найден — дома LAN работает, вне дома доступа не будет "
                "(https://tailscale.com/download/mac, затем ./scripts/enable_tailscale_serve.sh)"
            )
    if mode == "cloudflare" and not shutil.which("cloudflared"):
        warnings.append("NETWORK_MODE=cloudflare, но cloudflared не найден (brew install cloudflared)")

    print(f"SECRET_PATH={s.secret_path}")
    print(f"GATEKEEPER={s.gatekeeper_host}:{s.gatekeeper_port}")
    print(f"DSH={s.dsh_web_host}:{s.dsh_web_port}")
    print(f"OPENCODE={s.opencode_serve_host}:{s.opencode_serve_port}")
    print(f"OWNER={s.owner_telegram_id}")
    print(f"TOKEN_SET={bool(s.telegram_bot_token)}")
    print(f"ENV={s.env}")
    print(f"NETWORK_MODE={mode}")
    print(f"LOCAL_UI=http://{host_disp}:{s.gatekeeper_port}{s.secret_path}/")
    if lans:
        print("LAN_URLS=" + ",".join(lans[:5]))
    if mode == "cloudflare":
        warnings.append("NETWORK_MODE=cloudflare — публичный вход; для max-security используйте hybrid")
    if mode in mesh_modes and not (s.public_url or "").strip():
        warnings.append("PUBLIC_URL пуст — выполните ./scripts/enable_tailscale_serve.sh (для вне дома)")

    for w in warnings:
        print(f"WARN: {w}")
    for e in errors:
        print(f"ERR: {e}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
