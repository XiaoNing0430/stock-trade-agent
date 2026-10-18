"""上游调用护栏：token bucket 节流 + 连接级连败熔断（半开单探测）。

只对**连接级/超时**这类可恢复故障计数（HTTP 4xx/5xx 说明链路本身是通的，交调用方既有语义处理）。
熔断开启后 `before_call()` 立刻失败——配合路由层运行时降级链与后台补跑，避免把上游惩罚窗越打越深。
"""

from __future__ import annotations

import time
from collections.abc import Callable


class SourceCircuitOpen(RuntimeError):
    """熔断开启：本次调用未触达上游（可恢复，窗口到期后自动半开探测）。"""


class SourceGuard:
    def __init__(
        self,
        *,
        min_interval_s: float = 0.0,
        failure_threshold: int = 3,
        open_seconds: float = 300.0,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if open_seconds <= 0:
            raise ValueError("open_seconds must be > 0")
        self._min_interval_s = max(float(min_interval_s), 0.0)
        self._threshold = int(failure_threshold)
        self._open_seconds = float(open_seconds)
        self._clock = clock
        self._sleep = sleeper
        self._last_call: float | None = None
        self._failures = 0
        self._open_until: float | None = None
        self._probing = False

    def acquire(self) -> None:
        """节流：距上次调用不足 `min_interval_s` 时等待补足。"""
        now = self._clock()
        if self._last_call is not None and self._min_interval_s > 0:
            wait = self._min_interval_s - (now - self._last_call)
            if wait > 0:
                self._sleep(wait)
                now = self._clock()
        self._last_call = now

    def before_call(self) -> None:
        """熔断开启 → 抛 `SourceCircuitOpen`（不打上游）；窗口到期放行**单次**半开探测。"""
        if self._open_until is None:
            return
        now = self._clock()
        if now < self._open_until:
            raise SourceCircuitOpen(f"circuit open for {round(self._open_until - now, 1)}s more")
        if self._probing:
            raise SourceCircuitOpen("circuit half-open probe already in flight")
        self._probing = True

    def record_success(self) -> None:
        self._failures = 0
        self._open_until = None
        self._probing = False

    def record_connection_failure(self) -> None:
        self._probing = False
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = self._clock() + self._open_seconds

    def state(self) -> str:
        """closed（正常）| open（熔断中，快速失败）| half-open（窗口已过，待单次探测）。"""
        if self._open_until is None:
            return "closed"
        return "open" if self._clock() < self._open_until else "half-open"

    def reset(self) -> None:
        """测试隔离 / 人工复位：等价于刚创建。"""
        self._last_call = None
        self._failures = 0
        self._open_until = None
        self._probing = False
