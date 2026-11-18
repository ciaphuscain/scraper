"""Process-wide polite rate limiter for YouTube requests."""
from __future__ import annotations

import random
import threading
import time


class RateLimiter:
    def __init__(self, min_interval: float = 2.0):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next = 0.0
        self._penalty_until = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            start = max(now, self._next, self._penalty_until)
            # small jitter so parallel workers don't align
            self._next = start + self.min_interval * (1 + random.uniform(0, 0.25))
        delay = start - time.monotonic()
        if delay > 0:
            time.sleep(delay)

    def penalize(self, seconds: float) -> None:
        """Back off globally after HTTP 429 or similar throttling."""
        with self._lock:
            self._penalty_until = max(self._penalty_until, time.monotonic() + seconds)


youtube_limiter = RateLimiter()
