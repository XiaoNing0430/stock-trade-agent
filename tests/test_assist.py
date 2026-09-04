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


from backend.assist.calculator import IndicatorLevels, indicator_levels, sizing  # noqa: E402

# 基准场景截面：A=10.0、ATR=0.5、MA20=9.8（止损候选在 sizing 内按 entry 现算）
LEVELS = IndicatorLevels(reference_date="2026-09-03", closed_count=60, atr14=0.5, ma20=9.8, last_close=10.0)


def test_indicator_levels_computes_atr_and_ma() -> None:
    bars = [
        {
            "date": f"2026-08-{d:02d}",
            "open": 10,
            "close": 10 + (d % 3) * 0.2,
            "high": 10.5 + (d % 3) * 0.2,
            "low": 9.5,
            "volume": 100,
        }
        for d in range(1, 31)
    ]
    levels = indicator_levels(bars, "2026-08-30")
    assert levels.closed_count == 30
    assert levels.atr14 is not None and levels.atr14 > 0
    assert levels.ma20 is not None
    assert levels.last_close == 10.0
    # 与 indicators 直算一致
    from backend.indicators import atr, ma

    closes = [float(b["close"]) for b in bars]
    assert levels.atr14 == atr(bars, period=14)[-1]
    assert levels.ma20 == ma(closes, 20)[-1]


def test_indicator_levels_insufficient_bars() -> None:
    bars = [_bar("2026-08-01", 10.0), _bar("2026-08-02", 10.1)]
    levels = indicator_levels(bars, "2026-08-30")
    assert levels.atr14 is None and levels.ma20 is None


def test_sizing_default_scenario() -> None:
    r = sizing(
        10.0, LEVELS, stop_mode="atr", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10
    )
    assert r.stop == 9.0 and r.stop_distance == 1.0
    assert r.target == 12.0 and r.risk_amount == 1000.0  # target = entry + stop_distance*rr（公式唯一事实）
    assert r.suggested_shares == 1000 and r.position_pct == 10.0


def test_sizing_insufficient_equity() -> None:
    r = sizing(10.0, LEVELS, stop_mode="atr", equity=9000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10)
    assert r.suggested_shares == 0 and any("不足一手" in w for w in r.warnings)


def test_sizing_cap_truncates() -> None:
    r = sizing(
        10.0, LEVELS, stop_mode="atr", equity=100000.0, risk_pct=5.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10
    )
    assert r.suggested_shares == 2500 and any("上限" in w for w in r.warnings)


def test_sizing_ma20_mode_and_fallback() -> None:
    r = sizing(
        10.0, LEVELS, stop_mode="ma20", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10
    )
    assert r.stop == 9.8  # ma20 优先且有效


def test_sizing_invalid_stop_falls_back_to_none() -> None:
    levels = IndicatorLevels(reference_date="d", closed_count=60, atr14=0.5, ma20=10.5, last_close=10.0)
    r = sizing(
        10.0, levels, stop_mode="ma20", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10
    )
    assert r.stop == 9.0  # ma20 无效回退 atr


def test_sizing_all_stops_invalid() -> None:
    # 注：修订版语义下 stop_atr = entry − 2·ATR 在 ATR>0 时恒 < entry，
    # 故全无效场景取 atr14=None（数据不足）+ ma20=11.0 ≥ 入场价。
    levels2 = IndicatorLevels(reference_date="d", closed_count=60, atr14=None, ma20=11.0, last_close=10.0)
    r2 = sizing(
        10.0, levels2, stop_mode="atr", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10
    )
    assert r2.stop is None and r2.target is None and r2.suggested_shares == 0
    assert any("止损" in w for w in r2.warnings)


def test_sizing_multiday_target_warning() -> None:
    r = sizing(
        10.0, LEVELS, stop_mode="atr", equity=100000.0, risk_pct=1.0, rr_ratio=3.0, cap_pct=25.0, limit_ratio=0.10
    )
    assert any("多日" in w for w in r.warnings)
