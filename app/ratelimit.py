"""In-memory rate limiting. Suitable for one server process only."""

import math
import threading
from collections import defaultdict, deque


class TokenBucket:
    """Allows short bursts, then a steady rate per key (here: per account)."""

    def __init__(self, rate_per_second: float, burst: int):
        self.rate = rate_per_second
        self.burst = burst
        self._state: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def take(self, key: str, now_s: float) -> float:
        """Spend one token. Returns 0 if allowed, else the seconds to wait."""
        with self._lock:
            tokens, last = self._state.get(key, (float(self.burst), now_s))
            tokens = min(self.burst, tokens + (now_s - last) * self.rate)
            if tokens >= 1:
                self._state[key] = (tokens - 1, now_s)
                return 0.0
            self._state[key] = (tokens, now_s)
            return (1 - tokens) / self.rate


class FailureWindow:
    """Counts failures per key in a sliding window, e.g. failed logins per address."""

    def __init__(self, limit: int, window_seconds: float):
        self.limit = limit
        self.window = window_seconds
        self._events: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def retry_after(self, key: str, now_s: float) -> int:
        with self._lock:
            events = self._events[key]
            while events and events[0] <= now_s - self.window:
                events.popleft()
            if len(events) < self.limit:
                return 0
            return max(1, math.ceil(events[0] + self.window - now_s))

    def record(self, key: str, now_s: float) -> None:
        with self._lock:
            self._events[key].append(now_s)
