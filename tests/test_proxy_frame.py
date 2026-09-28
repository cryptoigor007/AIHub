"""Proxy source must allow same-origin iframe embed."""


def test_proxy_source_has_frame_rewrite():
    src = open("src/gatekeeper/proxy.py", encoding="utf-8").read()
    assert "x-frame-options" in src.lower() or "X-Frame-Options" in src
    assert "frame-ancestors" in src


def test_security_headers_sameorigin_default():
    src = open("src/gatekeeper/security.py", encoding="utf-8").read()
    assert "X-Frame-Options" in src
    assert "SAMEORIGIN" in src
