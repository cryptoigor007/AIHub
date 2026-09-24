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
