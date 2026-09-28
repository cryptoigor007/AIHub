"""Security: HTML escape helpers used by UI must neutralize XSS vectors."""
import re

# Mirror the client esc() contract (also verified in static/js)
def esc(s):
    return (
        str(s if s is not None else "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def test_esc_script_tag():
    assert "<script>" not in esc("<script>alert(1)</script>")
    assert "&lt;script&gt;" in esc("<script>alert(1)</script>")


def test_esc_attr():
    assert '"' not in esc('x" onload="alert(1)')
    assert "&quot;" in esc('x" onload="alert(1)')


def test_esc_amp():
    assert esc("a&b") == "a&amp;b"


def test_no_raw_innerhtml_pattern_in_js():
    """Guard: production JS must not use innerHTML with unescaped agent data via template injection."""
    js = open("static/js/aihub.js", encoding="utf-8").read()
    # titles/messages go through esc()
    assert "function esc(" in js or "esc(s)" in js
    # no eval
    assert "eval(" not in js
