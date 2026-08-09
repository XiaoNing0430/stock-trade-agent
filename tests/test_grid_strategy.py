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


def test_a_share_t_plus_one_blocks_same_day_grid_sell():
    bars = [
        {"date": "2026-01-02", "close": 10, "low": 10, "high": 10},
        {"date": "2026-01-03", "close": 10, "low": 8.9, "high": 11.1},
    ]

    result = backtest_grid(bars, lower=8, upper=12, grid_count=8, capital=100000, settlement_days=1)

    initial_shares = 5000
    same_day_sells = sum(trade["shares"] for trade in result["trades"] if trade["side"] == "sell")
    assert same_day_sells <= initial_shares


def test_cost_model_applies_stock_sell_tax_but_not_etf_tax():
    stock = backtest_grid(sample_bars(), 8, 12, 4, 100000, security_type="股票")
    etf = backtest_grid(sample_bars(), 8, 12, 4, 100000, security_type="ETF")

    stock_sell_fees = sum(trade["fee"] for trade in stock["trades"] if trade["side"] == "sell")
    etf_sell_fees = sum(trade["fee"] for trade in etf["trades"] if trade["side"] == "sell")
    assert stock_sell_fees > etf_sell_fees


def test_slippage_reduces_backtest_equity():
    baseline = backtest_grid(sample_bars(), 8, 12, 4, 100000, slippage_bps=0)
    with_slippage = backtest_grid(sample_bars(), 8, 12, 4, 100000, slippage_bps=20)

    assert with_slippage["metrics"]["endEquity"] < baseline["metrics"]["endEquity"]


def test_flat_or_zero_volume_bar_does_not_create_fill():
    bars = [
        {"date": "2026-01-02", "close": 10, "low": 10, "high": 10, "volume": 1000},
        {"date": "2026-01-03", "close": 10, "low": 10, "high": 10, "volume": 0},
    ]

    result = backtest_grid(bars, 8, 12, 4, 100000)

    assert result["metrics"]["tradeCount"] == 0


def test_optimize_grid_returns_ranked_candidates():
    candidates = optimize_grid(sample_bars(), capital=100000, fee_bps=3)

    assert len(candidates) >= 3
    assert "inSampleMetrics" in candidates[0]
    assert candidates[0]["metrics"]["endEquity"] >= candidates[-1]["metrics"]["endEquity"]
