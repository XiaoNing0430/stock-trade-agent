"""草案计算核心测试：closed_bars / 限频 / 纯函数 sizing（Task 1-3 逐段补充）。"""

from __future__ import annotations

from backend.indicators import closed_bars


def _bar(day: str, close: float) -> dict:
    return {"date": day, "open": close, "close": close, "high": close, "low": close, "volume": 100}


def test_closed_bars_truncates_future_dates() -> None:
    bars = [_bar("2026-09-01", 10.0), _bar("2026-09-02", 11.0), _bar("2026-09-03", 12.0)]
    closed = closed_bars(bars, "2026-09-02", limit=60)
    assert [b["date"] for b in closed] == ["2026-09-01", "2026-09-02"]


def test_closed_bars_keeps_last_limit() -> None:
    bars = [_bar(f"2026-08-{d:02d}", 10.0) for d in range(1, 11)]
    assert len(closed_bars(bars, "2026-08-31", limit=5)) == 5


def test_closed_bars_empty() -> None:
    assert closed_bars([], "2026-09-02", limit=60) == []


from backend.assist.limiter import SlidingWindowLimiter  # noqa: E402


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_allows_burst_then_blocks() -> None:
    clock = _FakeClock()
    limiter = SlidingWindowLimiter(max_events=3, window_seconds=60.0, clock=clock)
    assert limiter.check() == (True, 0.0)
    assert limiter.check() == (True, 0.0)
    assert limiter.check() == (True, 0.0)
    allowed, retry_after = limiter.check()
    assert not allowed
    assert 59.0 <= retry_after <= 60.0


def test_limiter_window_slides() -> None:
    clock = _FakeClock()
    limiter = SlidingWindowLimiter(max_events=2, window_seconds=60.0, clock=clock)
    limiter.check()
    limiter.check()
    clock.now += 61.0
    allowed, _ = limiter.check()
    assert allowed
