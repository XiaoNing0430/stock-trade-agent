from backend.grid_strategy import backtest_grid, build_grid, buy_and_hold_benchmark, optimize_grid, suggest_grid


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


def test_price_limit_blocks_unreliable_breakout_buy_and_stop_sell():
    bars = [
        {"date": "2026-01-02", "close": 10, "low": 10, "high": 10, "volume": 1000},
        {"date": "2026-01-03", "close": 10.8, "low": 9, "high": 11, "volume": 1000},
    ]

    result = backtest_grid(bars, 8, 12, 4, 100000, mode="trend", price_limit_pct=0.1)

    assert result["metrics"]["skippedLimitUpDays"] == 1
    assert result["metrics"]["skippedLimitDownDays"] == 1


def test_optimize_grid_returns_ranked_candidates():
    candidates = optimize_grid(sample_bars(), capital=100000, fee_bps=3)

    assert len(candidates) >= 3
    assert "inSampleMetrics" in candidates[0]
    assert "metrics" in candidates[0]
    assert "flag" in candidates[0]
    assert "recommended" in candidates[0]
    # Ranking: validation excess return descending.
    excess = [c["metrics"]["excessReturnPct"] for c in candidates]
    assert excess == sorted(excess, reverse=True)
    # With the 3-bar validation window the sample-out is too short.
    assert candidates[0]["flag"] == "样本外过短"


def test_backtest_exposes_benchmark_and_risk_metrics():
    result = backtest_grid(sample_bars(), 8, 12, 4, 100000, fee_bps=3)
    metrics = result["metrics"]

    assert "benchmarkReturnPct" in metrics
    assert "excessReturnPct" in metrics
    assert "totalFees" in metrics
    assert "turnoverMultiple" in metrics
    assert metrics["excessReturnPct"] is not None
    assert "sharpeRatio" in metrics
    assert "annualizedVolatilityPct" in metrics
    assert result["equityCurve"]
    assert result["benchmarkCurve"]
    assert len(result["equityCurve"]) == len(result["benchmarkCurve"])


def test_short_sample_returns_null_risk_metrics():
    result = backtest_grid(sample_bars()[:2], 8, 12, 4, 100000)

    assert result["metrics"]["annualizedVolatilityPct"] is None
    assert result["metrics"]["sharpeRatio"] is None


def test_buy_and_hold_benchmark_buys_lots_and_charges_fee():
    bars = [
        {"date": "2026-01-02", "close": 10, "high": 10, "low": 10},
        {"date": "2026-01-03", "close": 12, "high": 12, "low": 12},
    ]

    benchmark = buy_and_hold_benchmark(bars, capital=100000, fee_bps=3)

    assert benchmark["endEquity"] > 100000
    assert benchmark["returnPct"] > 0
    assert len(benchmark["curve"]) == 2


def _make_bar(date, open_, high, low, close, volume):
    return {"date": date, "open": open_, "high": high, "low": low, "close": close, "volume": volume}


def test_one_price_limit_up_day_allows_sells_only():
    bars = [
        _make_bar("2026-01-01", 10.0, 10.0, 10.0, 10.0, 10000),
        _make_bar("2026-01-02", 11.0, 11.0, 11.0, 11.0, 4000),
    ]

    result = backtest_grid(bars, lower=9.0, upper=12.0, grid_count=3, capital=100000, mode="classic")
    metrics = result["metrics"]
    buys = [t for t in result["trades"] if t["side"] == "buy"]
    sells = [t for t in result["trades"] if t["side"] == "sell"]

    assert metrics["onePriceLimitUpDays"] == 1
    assert metrics["onePriceLimitDownDays"] == 0
    assert metrics["skippedSuspensionDays"] == 0
    assert len(sells) == 1
    assert sells[0]["price"] == 11.0
    assert not buys


def test_one_price_limit_down_day_allows_buys_only():
    bars = [
        _make_bar("2026-01-01", 10.0, 10.0, 10.0, 10.0, 10000),
        _make_bar("2026-01-02", 9.0, 9.0, 9.0, 9.0, 4000),
    ]

    result = backtest_grid(bars, lower=8.0, upper=12.0, grid_count=4, capital=100000, mode="classic")
    metrics = result["metrics"]
    buys = [t for t in result["trades"] if t["side"] == "buy"]
    sells = [t for t in result["trades"] if t["side"] == "sell"]

    assert metrics["onePriceLimitDownDays"] == 1
    assert metrics["onePriceLimitUpDays"] == 0
    assert metrics["skippedSuspensionDays"] == 0
    assert len(buys) == 1
    assert buys[0]["price"] == 9.0
    assert not sells


def test_zero_volume_day_is_still_suspension():
    bars = [
        _make_bar("2026-01-01", 10.0, 10.0, 10.0, 10.0, 10000),
        _make_bar("2026-01-02", 10.0, 10.0, 10.0, 10.0, 0),
    ]

    result = backtest_grid(bars, lower=9.0, upper=11.0, grid_count=2, capital=100000, mode="classic")
    metrics = result["metrics"]

    assert metrics["skippedSuspensionDays"] == 1
    assert metrics["onePriceLimitUpDays"] == 0
    assert metrics["onePriceLimitDownDays"] == 0
    assert result["trades"] == []


def test_metrics_include_new_risk_fields():
    result = backtest_grid(sample_bars(), lower=8, upper=12, grid_count=4, capital=100000, fee_bps=3)
    m = result["metrics"]
    for key in ("winRatePct", "maxDrawdownDurationDays", "avgGridReturnPct", "profitFactor"):
        assert key in m, f"missing {key}"
    if m["winRatePct"] is not None:
        assert 0 <= m["winRatePct"] <= 100
    assert m["maxDrawdownDurationDays"] >= 0


def test_risk_metrics_round_trip_accuracy():
    bars = [
        {"date": "2026-01-02", "open": 10, "high": 10, "low": 10, "close": 10},
        {"date": "2026-01-03", "open": 10, "high": 8, "low": 8, "close": 8},
        {"date": "2026-01-06", "open": 8, "high": 12, "low": 8, "close": 12},
        {"date": "2026-01-07", "open": 12, "high": 12, "low": 12, "close": 12},
    ]
    result = backtest_grid(bars, lower=8, upper=12, grid_count=4, capital=100000, fee_bps=3)
    m = result["metrics"]
    assert m["winRatePct"] is not None
    assert m["avgGridReturnPct"] > 0
