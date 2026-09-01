# tests/test_strategy_base.py
from backend.strategy_base import BaseStrategy, Signal


class DummyStrategy(BaseStrategy):
    id = "dummy"
    label = "测试策略"
    config_schema = [{"key": "period", "label": "周期", "type": "int", "default": 3}]

    def signal_at(self, index, state):
        bars = self._bars
        if index == 2 and state.shares == 0:
            return Signal(date=bars[index]["date"], side="buy", price=float(bars[index]["close"]), reason="测试买入")
        if index == 5 and state.shares > 0:
            return Signal(date=bars[index]["date"], side="sell", price=float(bars[index]["close"]), reason="测试卖出")
        return None


def _bars(count=8, start=10.0):
    return [
        {
            "date": f"2026-01-{i + 1:02d}",
            "open": start + i,
            "high": start + i + 1,
            "low": start + i - 1,
            "close": start + i,
            "volume": 10000,
        }
        for i in range(count)
    ]


def test_backtest_returns_unified_shape():
    result = DummyStrategy().backtest(_bars(), {"capital": 100000, "feeBps": 3})
    assert set(result.keys()) == {"trades", "equityCurve", "benchmarkCurve", "metrics", "assumptions"}


def test_backtest_buys_100_lots_with_fee():
    result = DummyStrategy().backtest(_bars(), {"capital": 100000, "feeBps": 3})
    assert len(result["trades"]) == 2
    buy = result["trades"][0]
    assert buy["side"] == "buy"
    assert buy["shares"] % 100 == 0
    assert buy["fee"] >= 5.0  # 最低佣金 5 元


def test_t_plus_1_position_sellable_next_day():
    class BuyNextDay(BaseStrategy):
        id = "bnd"
        label = "次日卖"
        config_schema = []

        def signal_at(self, index, state):
            bars = self._bars
            close = float(bars[index]["close"])
            date = bars[index].get("date", "")
            if index == 2 and state.shares == 0:
                return Signal(date, "buy", close, reason="买")
            if index == 3 and state.shares > 0:
                return Signal(date, "sell", close, reason="卖")
            return None

    result = BuyNextDay().backtest(_bars(), {"capital": 100000, "feeBps": 3})
    assert [t["side"] for t in result["trades"]] == ["buy", "sell"], (
        "index 2 买入 → index 3 应可卖（available_day = 3）"
    )


def test_capital_allocation_splits_capital():
    result = DummyStrategy().backtest(_bars(), {"capital": 100000, "feeBps": 3, "capitalAllocation": 0.5})
    # 切分后资金 50000，可买 100 股 10 元 → 1000 元，费用 ≥5 元，endEquity 应按比例缩放
    assert result["metrics"]["startEquity"] == 50000.0
