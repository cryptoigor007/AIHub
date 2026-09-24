"""TOKEN_PATTERNS покрывают типичные строки web.log."""
from __future__ import annotations
import re
from pathlib import Path

# Читаем паттерны из исходника без тяжёлых deps
SRC = Path(__file__).resolve().parent.parent / "src/common/dsh_token.py"
text = SRC.read_text(encoding="utf-8")

def _load_patterns():
    pats = []
    for m in re.finditer(
        r're\.compile\((r["\'].+?["\'])(?:,\s*(re\.\w+))?\)',
        text,
    ):
        pat_s = eval(m.group(1))  # noqa: S307 — только наши литералы
        flags = re.IGNORECASE if m.group(2) == "re.IGNORECASE" else 0
        pats.append(re.compile(pat_s, flags))
    return pats


def test_patterns_match_common_forms():
    pats = _load_patterns()
    assert len(pats) >= 4
    samples = [
        "token=abc123xyzABC123xyzABC12",
        "access_token: abc123xyzABC123xyzABC12",
        "Authorization: Bearer abc123xyzABC123xyzABC12",
        '{"token": "abc123xyzABC123xyzABC12"}',
        "GET /x?token=abc123xyzABC123xyzABC12 HTTP/1.1",
    ]
    for s in samples:
        assert any(p.search(s) for p in pats), f"no match for: {s}"


def test_source_parses():
    import ast
    ast.parse(text)


if __name__ == "__main__":
    test_patterns_match_common_forms()
    test_source_parses()
    print("OK")
