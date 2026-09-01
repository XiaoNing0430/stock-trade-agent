# tests/test_multi_factor.py
from backend.multi_factor import MultiFactorStrategy
from backend.strategy_base import Signal


def _bars(count=80, mode="trend"):
    bars = []
    for i in range(count):
        if mode == "trend":
            close = 100.0 + i * 1.2  # 单边上涨
        else:
            close = 100.0 + (i % 6) * 2.0 - 5.0  # 震荡
        bars.append(
            {
                "date": f"2026-01-{i % 28 + 1:02d}",
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 10000,
            }
        )
    return bars


def test_multi_factor_returns_unified_shape():
    result = MultiFactorStrategy().backtest(_bars(), {"capital": 100000, "feeBps": 3, "maxConsecutiveLosses": 10})
    assert set(result.keys()) == {
        "trades",
        "equityCurve",
        "benchmarkCurve",
        "metrics",
        "assumptions",
        "moduleUsage",
        "theoreticalIfUnfrozen",
    }
    assert "多因子" in result["assumptions"]


def test_multi_factor_trend_module_structure_present():
    result = MultiFactorStrategy().backtest(_bars(80, "trend"), {"capital": 100000, "feeBps": 3})
    usage = result["moduleUsage"]
    assert "trend" in usage and "range" in usage
    for key in ("trades", "frozenPeriods"):
        assert key in usage["trend"]
        assert key in usage["range"]


def test_multi_factor_stagnation_guard_freezes_losing_module():
    # 子类强制「偶数日高价买、奇数日低价卖」：每笔 round trip 都亏损 → 达阈值冻结
    class Whipsaw(MultiFactorStrategy):
        def signal_at(self, index, state):
            if self._module_stats["trend"]["frozen"]:
                return None  # 冻结检查（与父类行为一致）
            bars = self._bars
            close = float(bars[index]["close"])
            date = bars[index].get("date", "")
            if index % 2 == 0 and state.shares == 0:
                return Signal(date, "buy", close, reason="假买", module="trend")
            if index % 2 == 1 and state.shares > 0:
                return Signal(date, "sell", close, reason="假卖", module="trend")
            return None

    bars = [
        {
            "date": f"2026-01-{i + 1:02d}",
            "open": 100.0,
            "high": 100.0,
            "low": 100.0,
            "close": 100.0 - i,
            "volume": 10000,
        }
        for i in range(20)
    ]
    result = Whipsaw().backtest(bars, {"capital": 100000, "feeBps": 3, "maxConsecutiveLosses": 3})
    stats = result["moduleUsage"]["trend"]
    assert stats["frozenPeriods"], "连续亏损应触发冻结记录"
    frozen_start = stats["frozenPeriods"][0]["start"]
    frozen_trades = [t for t in result["trades"] if t.get("module") == "trend" and t["date"] > frozen_start]
    assert all(t["side"] != "buy" for t in frozen_trades), "冻结后 trend 模块不得再买入"


def test_multi_factor_assumptions_disclose_adx_lag():
    result = MultiFactorStrategy().backtest(_bars(), {"capital": 100000, "feeBps": 3})
    assert "滞后" in result["assumptions"] or "ADX" in result["assumptions"]
