"""进程内滑动窗口限频（单用户本地部署；线程安全；时钟可注入便于测试）。"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable


class SlidingWindowLimiter:
    def __init__(
        self, max_events: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        if max_events < 1:
            raise ValueError("max_events must be >= 1")
        self._max = max_events
        self._window = window_seconds
        self._clock = clock
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def check(self) -> tuple[bool, float]:
        with self._lock:
            now = self._clock()
            while self._events and now - self._events[0] >= self._window:
                self._events.popleft()
            if len(self._events) >= self._max:
                return False, max(self._window - (now - self._events[0]), 0.0)
            self._events.append(now)
            return True, 0.0
