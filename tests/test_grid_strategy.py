from backend.grid_strategy import backtest_grid, build_grid, suggest_grid, optimize_grid


def sample_bars():
    return [
        {"date": "2026-01-02", "open": 10, "high": 10.2, "low": 9.8, "close": 10},
        {"date": "2026-01-03", "open": 10, "high": 10.1, "low": 8.9, "close": 9.2},
        {"date": "2026-01-06", "open": 9.2, "high": 11.1, "low": 9.1, "close": 10.8},
        {"date": "2026-01-07", "open": 10.8, "high": 11.2, "low": 10.5, "close": 11},
    ]


def test_build_grid_contains_evenly_spaced_bounds():
    levels = build_grid(8, 12, 4)

    assert levels == [8.0, 9.0, 10.0, 11.0, 12.0]


def test_suggest_grid_uses_history_price_range():
    suggestion = suggest_grid(sample_bars(), grid_count=6, capital=60000, mode="trend")

    assert suggestion["lower"] < suggestion["upper"]
    assert len(suggestion["levels"]) == 7
    assert suggestion["lower"] <= 9.2 <= suggestion["upper"]
    assert suggestion["referencePrice"] == 11
    assert suggestion["buyRule"] == "价格上涨一个网格买入"
    assert suggestion["perGridAmount"] > 0


def test_backtest_grid_generates_trades_and_metrics():
    result = backtest_grid(sample_bars(), lower=8, upper=12, grid_count=4, capital=100000, fee_bps=3)

    assert result["trades"]
    assert result["metrics"]["tradeCount"] > 0
    assert result["metrics"]["endEquity"] > 0
    assert result["metrics"]["maxDrawdownPct"] >= 0


def test_trend_grid_uses_rise_to_buy_and_fall_to_sell():
    result = backtest_grid(sample_bars(), lower=8, upper=12, grid_count=4, capital=100000, mode="trend")

    assert result["metrics"]["tradeCount"] > 0
    assert "趋势网格" in result["assumptions"]


def test_optimize_grid_returns_ranked_candidates():
    candidates = optimize_grid(sample_bars(), capital=100000, fee_bps=3)

    assert len(candidates) >= 3
    assert candidates[0]["metrics"]["endEquity"] >= candidates[-1]["metrics"]["endEquity"]
