"""Детект mesh URL: кандидаты и защита от ложного DNSName без Serve."""
from __future__ import annotations

import asyncio
import subprocess

import pytest

pytest.importorskip("httpx", reason="httpx not installed")
pytest.importorskip("pydantic_settings", reason="pydantic_settings not installed")

from src.tunnel.watcher import TunnelWatcher


class _Res:
    def __init__(self, returncode: int = 0, stdout: str = ""):
        self.returncode = returncode
        self.stdout = stdout


def _patch_run(monkeypatch, mapping):
    def fake_run(cmd, **kwargs):
        key = tuple(cmd[:3])
        if key in mapping:
            val = mapping[key]
            if isinstance(val, Exception):
                raise val
            return val
        raise AssertionError(f"unexpected cmd: {cmd}")

    monkeypatch.setattr(subprocess, "run", fake_run)


def test_serve_empty_config_no_dnsname(monkeypatch):
    """`serve status --json` == {} → Serve не настроен, DNSName не подставляем."""
    _patch_run(monkeypatch, {("tailscale", "serve", "status"): _Res(0, "{}")})
    w = TunnelWatcher()
    assert asyncio.run(w._detect_tailscale_urls()) == []


def test_serve_url_found(monkeypatch):
    stdout = (
        '{"Web": {"https://mac.tail123.ts.net:443": '
        '{"Handlers": {"/": {"Proxy": "http://127.0.0.1:8787"}}}}}'
    )
    _patch_run(monkeypatch, {("tailscale", "serve", "status"): _Res(0, stdout)})
    w = TunnelWatcher()
    assert asyncio.run(w._detect_tailscale_urls()) == ["https://mac.tail123.ts.net"]


def test_dnsname_fallback_when_serve_status_unsupported(monkeypatch):
    _patch_run(
        monkeypatch,
        {
            ("tailscale", "serve", "status"): _Res(1, ""),
            ("tailscale", "status", "--json"): _Res(
                0, '{"Self": {"DNSName": "mac.tail123.ts.net."}}'
            ),
        },
    )
    w = TunnelWatcher()
    assert asyncio.run(w._detect_tailscale_urls()) == ["https://mac.tail123.ts.net"]


def test_tailscale_missing(monkeypatch):
    _patch_run(monkeypatch, {("tailscale", "serve", "status"): FileNotFoundError()})
    w = TunnelWatcher()
    assert asyncio.run(w._detect_tailscale_urls()) == []


def test_public_url_env_first(monkeypatch):
    monkeypatch.setenv("PUBLIC_URL", "https://from-env.ts.net")
    _patch_run(monkeypatch, {("tailscale", "serve", "status"): _Res(0, "{}")})
    w = TunnelWatcher()
    cands = asyncio.run(w._detect_tailscale_urls())
    assert cands and cands[0] == "https://from-env.ts.net"


if __name__ == "__main__":
    print("use pytest")
