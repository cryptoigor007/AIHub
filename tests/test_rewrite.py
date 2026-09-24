"""HTML rewrite для proxy DSH."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.gatekeeper.security import rewrite_html_base


def test_http_localhost():
    html = b'<a href="http://127.0.0.1:3080/app">x</a>'
    out = rewrite_html_base(html, "/p/sec/dsh").decode()
    assert "127.0.0.1:3080" not in out
    assert "/p/sec/dsh/app" in out


def test_ws_and_protocol_relative():
    html = b'src="ws://localhost:3080/ws" data="//127.0.0.1:3080/x"'
    out = rewrite_html_base(html, "/p/sec/dsh").decode()
    assert "localhost:3080" not in out
    assert "127.0.0.1:3080" not in out
    assert "/p/sec/dsh" in out


def test_binary_safe():
    # invalid utf-8 → return as-is
    raw = b"\xff\xfe not utf8 http://127.0.0.1:3080"
    assert rewrite_html_base(raw, "/p/x") == raw


if __name__ == "__main__":
    test_http_localhost()
    test_ws_and_protocol_relative()
    test_binary_safe()
    print("OK")
