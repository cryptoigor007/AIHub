"""Unit tests for classify_ip / netstate."""
from src.common.netinfo import classify_ip, touch_netstate, load_netstate


def test_loopback():
    assert classify_ip("127.0.0.1") == "loopback"
    assert classify_ip("::1") == "loopback"


def test_lan():
    assert classify_ip("192.168.1.10") == "lan"
    assert classify_ip("10.0.0.5") == "lan"


def test_tailscale_cgnat():
    assert classify_ip("100.64.1.2") == "tailscale"
    assert classify_ip("100.127.0.1") == "tailscale"


def test_other():
    assert classify_ip("8.8.8.8") == "other"


def test_netstate_roundtrip(tmp_path):
    st = touch_netstate(tmp_path, "lan")
    assert st["last_channel"] == "lan"
    assert "last_lan_ts" in st
    loaded = load_netstate(tmp_path)
    assert loaded["last_channel"] == "lan"
