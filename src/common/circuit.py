"""Простой circuit breaker для внешних систем (DSH / OpenCode)."""

from __future__ import annotations

import time
from threading import Lock
from typing import Optional


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_sec: float = 30.0,
        name: str = "cb",
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_sec = recovery_sec
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._lock = Lock()

    @property
    def is_open(self) -> bool:
        with self._lock:
            if self._opened_at is None:
                return False
            if (time.monotonic() - self._opened_at) >= self.recovery_sec:
                # half-open: разрешаем одну попытку
                return False
            return True

    def record_success(self) -> None:
        with self._lock:
            self._failures = 0
            self._opened_at = None

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._opened_at = time.monotonic()

    def state(self) -> str:
        if self.is_open:
            return "open"
        if self._failures > 0:
            return "degraded"
        return "closed"


dsh_circuit = CircuitBreaker(name="dsh")
opencode_circuit = CircuitBreaker(name="opencode")
