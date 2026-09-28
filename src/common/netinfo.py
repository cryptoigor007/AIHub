"""LAN / Tailscale helpers: адреса, детект частной сети, подсказки пользователю."""

from __future__ import annotations

import ipaddress
import socket
from typing import Iterable


def _parse_ip(ip: str) -> ipaddress._BaseAddress | None:
    try:
        return ipaddress.ip_address(ip.split("%")[0])  # drop zone id
    except ValueError:
        return None


def is_private_ip(ip: str) -> bool:
    addr = _parse_ip(ip)
    if addr is None:
        return False
    return bool(addr.is_private or addr.is_loopback or addr.is_link_local)


def is_loopback_ip(ip: str) -> bool:
    """True только для 127.0.0.0/8 и ::1 — доверенная сторона для /health."""
    addr = _parse_ip(ip)
    return bool(addr is not None and addr.is_loopback)


def list_lan_ipv4() -> list[str]:
    """Локальные IPv4 интерфейсов (без loopback), для подсказок LAN URL."""
    found: list[str] = []
    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in found:
                if is_private_ip(ip):
                    found.append(ip)
    except OSError:
        pass
    # fallback: UDP connect trick (пакеты не отправляются)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
        finally:
            s.close()
        if ip and not ip.startswith("127.") and ip not in found and is_private_ip(ip):
            found.append(ip)
    except OSError:
        pass
    return found


def lan_http_urls(port: int, secret_path: str) -> list[str]:
    secret = secret_path if secret_path.startswith("/") else f"/{secret_path}"
    return [f"http://{ip}:{port}{secret.rstrip('/')}/" for ip in list_lan_ipv4()]


def network_hint_message(*, has_mesh_url: bool, lan_urls: Iterable[str]) -> str:
    """Текст для UI / Telegram: когда что включать."""
    lans = list(lan_urls)
    lines = [
        "📡 Доступ к AIHub",
        "",
        "• Дома в Wi‑Fi (та же сеть, что Mac): Tailscale можно не включать.",
        "  Откройте в браузере на телефоне:",
    ]
    if lans:
        for u in lans[:3]:
            lines.append(f"  {u}")
        lines.append("  (для кнопки в Telegram нужен HTTPS — удобнее Tailscale даже дома.)")
    else:
        lines.append("  http://IP-Mac:8787/p/…/  (IP смотрите в doctor/status)")
    lines.append("")
    if has_mesh_url:
        lines.append("• Вне дома / LTE: включите Tailscale (VPN On) на телефоне,")
        lines.append("  затем кнопку «AIHub» в боте.")
    else:
        lines.append("• Вне дома: установите Tailscale и выполните на Mac:")
        lines.append("  ./scripts/enable_tailscale_serve.sh")
    return "\n".join(lines)


def classify_ip(ip: str) -> str:
    """loopback | lan | tailscale | other"""
    addr = _parse_ip(ip)
    if addr is None:
        return "other"
    if addr.is_loopback:
        return "loopback"
    # Tailscale CGNAT 100.64.0.0/10 and fd7a:115c:a1e0::/48
    try:
        if addr.version == 4 and ipaddress.ip_address(ip) in ipaddress.ip_network("100.64.0.0/10"):
            return "tailscale"
        if addr.version == 6:
            v6 = str(addr).lower()
            if v6.startswith("fd7a:115c:a1e0:"):
                return "tailscale"
    except Exception:
        pass
    if addr.is_private or addr.is_link_local:
        return "lan"
    return "other"


def load_netstate(data_dir) -> dict:
    import json
    from pathlib import Path
    path = Path(data_dir) / "netstate.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}


def save_netstate(data_dir, state: dict) -> None:
    import json
    from pathlib import Path
    path = Path(data_dir) / "netstate.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    except Exception:
        pass


def touch_netstate(data_dir, channel: str) -> dict:
    """Update last_channel / timestamps for owner traffic."""
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    st = load_netstate(data_dir)
    st["last_channel"] = channel
    st["last_seen_ts"] = now
    if channel == "lan":
        st["last_lan_ts"] = now
    if channel == "tailscale":
        st["last_tailscale_ts"] = now
    save_netstate(data_dir, st)
    return st
