"""Token bucket rate limiter — 8 req/min to stay under MaaS 10 RPM ceiling."""
from __future__ import annotations

import time
from collections import deque
from threading import Lock


class TokenBucket:
    def __init__(self, rate_rpm: int = 8, capacity: int | None = None):
        self.rate = rate_rpm
        self.capacity = capacity or rate_rpm
        self._tokens = float(self.capacity)
        self._last = time.monotonic()
        self._lock = Lock()
        self._timestamps: deque[float] = deque(maxlen=rate_rpm * 2)

    def acquire(self, timeout_s: float = 30.0) -> float:
        """Acquire a token. Returns wait time in seconds (0 if immediate)."""
        with self._lock:
            now = time.monotonic()
            elapsed = now - self._last
            self._tokens = min(self.capacity, self._tokens + elapsed * (self.rate / 60.0))
            self._last = now

            if self._tokens >= 1.0:
                self._tokens -= 1.0
                self._timestamps.append(now)
                return 0.0

            needed = 1.0 - self._tokens
            wait = needed / (self.rate / 60.0)
            if wait > timeout_s:
                from app.errors import LLMRateLimitError
                raise LLMRateLimitError(f"Rate limit: would wait {wait:.1f}s > timeout {timeout_s}s")
            time.sleep(wait)
            self._tokens = 0.0
            self._last = time.monotonic()
            self._timestamps.append(self._last)
            return wait
