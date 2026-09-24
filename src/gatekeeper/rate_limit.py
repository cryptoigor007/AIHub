"""Простой in-memory rate limiter по IP."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Deque


class RateLimiter:
    def __init__(self, max_requests: int, window_sec: float) -> None:
        self.max_requests = max_requests
        self.window_sec = window_sec
        self._hits: dict[str, Deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def is_allowed(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and (now - q[0]) > self.window_sec:
                q.popleft()
            if len(q) >= self.max_requests:
                return False
            q.append(now)
            return True

    def remaining(self, key: str) -> int:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and (now - q[0]) > self.window_sec:
                q.popleft()
            return max(0, self.max_requests - len(q))

    def prune(self) -> int:
        """Удаляет пустые ключи (защита от роста dict)."""
        now = time.monotonic()
        removed = 0
        with self._lock:
            dead = []
            for k, q in self._hits.items():
                while q and (now - q[0]) > self.window_sec:
                    q.popleft()
                if not q:
                    dead.append(k)
            for k in dead:
                del self._hits[k]
                removed += 1
        return removed


# Auth: 10 / 5 мин
auth_limiter = RateLimiter(max_requests=10, window_sec=300)

# Остальное: 120 / мин
general_limiter = RateLimiter(max_requests=120, window_sec=60)
