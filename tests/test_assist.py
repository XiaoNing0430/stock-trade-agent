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
