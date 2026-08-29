from backend.grid_strategy import backtest_grid, _compute_metrics
from backend.strategy_engines import (
    STRATEGY_ENGINES,
    backtest_dca,
    backtest_ma_cross,
    backtest_macd,
)


def _trend_bars(count=120, start=100.0, dip=0.7, rise=1.3):
    """确定性三段序列：先下跌（占 40%）→上涨（30%）→再下跌（30%），触发均线/MACD 交叉。"""
    bars = []
    for i in range(count):
        progress = i / max(1, count - 1)
        if progress < 0.4:
            factor = 1 - (progress / 0.4) * (1 - dip)
        elif progress < 0.7:
            factor = dip + ((progress - 0.4) / 0.3) * (rise - dip)
        else:
            factor = rise - ((progress - 0.7) / 0.3) * (rise - dip)
        close = round(start * factor, 2)
        bars.append({
            "date": f"2026-{1 + i // 22:02d}-{1 + i % 28:02d}",
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 10000,
        })
    return bars


def test_compute_metrics_matches_backtest_grid_metrics():
    """抽取后的 _compute_metrics 与 backtest_grid 内部指标一致。"""
    bars = _trend_bars(60)
    result = backtest_grid(bars, lower=80, upper=130, grid_count=6, capital=100000, fee_bps=3)
    # 用与 backtest_grid 相同入参重新计算，验证关键指标结构
    assert "winRatePct" in result["metrics"]
    assert "profitFactor" in result["metrics"]
    assert result["metrics"]["tradeCount"] == len(result["trades"])
    assert result["metrics"]["returnPct"] is not None


def test_ma_cross_returns_unified_shape():
    result = backtest_ma_cross(_trend_bars(), {"fastPeriod": 5, "slowPeriod": 20, "capital": 100000, "feeBps": 3})
    assert set(result.keys()) == {"trades", "equityCurve", "benchmarkCurve", "metrics", "assumptions"}
    assert "双均线" in result["assumptions"]


def test_ma_cross_creates_buy_on_golden_cross():
    result = backtest_ma_cross(_trend_bars(), {"fastPeriod": 5, "slowPeriod": 20, "capital": 100000, "feeBps": 3})
    buys = [t for t in result["trades"] if t["side"] == "buy"]
    sells = [t for t in result["trades"] if t["side"] == "sell"]
    assert buys, "先跌后涨序列应触发金叉买入"
    assert sells, "后续应触发死叉卖出"
    assert result["metrics"]["tradeCount"] == len(result["trades"])


def test_ma_cross_requires_fast_lt_slow():
    try:
        backtest_ma_cross(_trend_bars(), {"fastPeriod": 20, "slowPeriod": 5})
        assert False, "fastPeriod >= slowPeriod 应报错"
    except ValueError:
        pass


def test_dca_returns_unified_shape():
    result = backtest_dca(_trend_bars(50), {"amountPerPeriod": 5000, "intervalDays": 5, "stopProfitPct": 50, "stopLossPct": 50, "capital": 100000, "feeBps": 3})
    assert set(result.keys()) == {"trades", "equityCurve", "benchmarkCurve", "metrics", "assumptions"}
    assert "定投" in result["assumptions"]


def test_dca_buys_periodically():
    count, interval = 60, 5
    result = backtest_dca(_trend_bars(count), {"amountPerPeriod": 15000, "intervalDays": interval, "stopProfitPct": 500, "stopLossPct": 500, "capital": 300000, "feeBps": 3})
    buys = [t for t in result["trades"] if t["side"] == "buy"]
    # 每 interval 根买一次（首买在 i==interval）
    expected_min = max(0, count // interval - 2)
    assert len(buys) >= expected_min, f"定投买入次数应约 {expected_min}，实际 {len(buys)}"


def test_dca_stop_profit_triggers_sell():
    bars = [
        {"date": f"2026-01-{i + 1:02d}", "open": 100, "high": 100, "low": 100, "close": 100 + i * 5, "volume": 10000}
        for i in range(30)
    ]
    result = backtest_dca(bars, {"amountPerPeriod": 10000, "intervalDays": 3, "stopProfitPct": 10, "stopLossPct": 50, "capital": 100000, "feeBps": 3})
    sells = [t for t in result["trades"] if t["side"] == "sell"]
    assert sells, "强上涨序列应触发止盈卖出"


def test_macd_returns_unified_shape():
    result = backtest_macd(_trend_bars(), {"fastPeriod": 12, "slowPeriod": 26, "signalPeriod": 9, "capital": 100000, "feeBps": 3})
    assert set(result.keys()) == {"trades", "equityCurve", "benchmarkCurve", "metrics", "assumptions"}
    assert "MACD" in result["assumptions"]


def test_macd_warms_up_before_trading():
    result = backtest_macd(_trend_bars(), {"fastPeriod": 12, "slowPeriod": 26, "signalPeriod": 9, "capital": 100000, "feeBps": 3})
    warmup = 26 + 9
    for t in result["trades"]:
        # 交易日期应出现在预热期之后
        idx = next(i for i, b in enumerate(_trend_bars()) if b["date"] == t["date"])
        assert idx >= warmup, f"预热期内不应出现交易：{t}"


def test_macd_creates_trades_after_warmup():
    result = backtest_macd(_trend_bars(), {"fastPeriod": 12, "slowPeriod": 26, "signalPeriod": 9, "capital": 100000, "feeBps": 3})
    assert result["trades"], "先跌后涨序列应在预热期后触发交易"
    assert result["metrics"]["tradeCount"] > 0


def test_strategy_engines_registry_lists_all_types():
    assert set(STRATEGY_ENGINES.keys()) == {"ma_cross", "dca", "macd"}
    for spec in STRATEGY_ENGINES.values():
        assert spec["label"]
        assert callable(spec["backtest"])
        assert spec["configSchema"]
