"""Request pacing: a minimum interval between request starts, plus Retry-After parsing."""

from __future__ import annotations

import time
from collections.abc import Callable


def parse_retry_after(value: str | None, default: float) -> float:
    if not value:
        return default
    try:
        return max(0.0, float(value))
    except ValueError:
        return default


class Throttle:
    """Keeps a minimum interval between request starts."""

    def __init__(
        self,
        interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.interval_s = interval_s
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0

    def wait(self) -> None:
        now = self._clock()
        if now < self._next:
            self._sleep(self._next - now)
            now = self._next
        self._next = now + self.interval_s

    def push_back(self, seconds: float) -> None:
        """Delay the next request by at least `seconds` from now (Retry-After)."""
        self._next = max(self._next, self._clock() + seconds)
