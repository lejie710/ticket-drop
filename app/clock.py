"""A clock the application reads instead of calling time.time() directly.

Hold expiry and the sale opening are time rules. Tests need to put the
clock on an exact boundary, such as the millisecond a hold expires, so every
time decision goes through this object.
"""

import threading
import time


class Clock:
    def __init__(self, frozen_at_ms: int | None = None):
        self._lock = threading.Lock()
        self._frozen_at_ms = frozen_at_ms
        self._offset_ms = 0

    def now_ms(self) -> int:
        with self._lock:
            base = self._frozen_at_ms if self._frozen_at_ms is not None else int(time.time() * 1000)
            return base + self._offset_ms

    def advance(self, ms: int) -> None:
        with self._lock:
            self._offset_ms += ms

    def freeze(self, at_ms: int) -> None:
        with self._lock:
            self._frozen_at_ms = at_ms
            self._offset_ms = 0
