"""Политика локального входа в UI без Telegram."""

from __future__ import annotations

from .netinfo import is_loopback_ip

MODES = ("off", "loopback", "lan")


def local_login_allowed(mode: str, peer_ip: str) -> bool:
    """off — никогда; loopback — только с Mac; lan — откуда угодно."""
    mode = (mode or "loopback").strip().lower()
    if mode == "off":
        return False
    if mode == "lan":
        return True
    return is_loopback_ip(peer_ip)
