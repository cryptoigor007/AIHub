"""Rate limiter + prune."""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.gatekeeper.rate_limit import RateLimiter


def test_allows_then_blocks():
    rl = RateLimiter(max_requests=3, window_sec=60)
    assert rl.is_allowed("ip1")
    assert rl.is_allowed("ip1")
    assert rl.is_allowed("ip1")
    assert not rl.is_allowed("ip1")
    assert rl.is_allowed("ip2")  # другой ключ


def test_prune_removes_empty():
    rl = RateLimiter(max_requests=2, window_sec=0.01)
    rl.is_allowed("gone")
    import time
    time.sleep(0.02)
    removed = rl.prune()
    assert removed >= 1
    assert "gone" not in rl._hits


if __name__ == "__main__":
    test_allows_then_blocks()
    test_prune_removes_empty()
    print("OK")
