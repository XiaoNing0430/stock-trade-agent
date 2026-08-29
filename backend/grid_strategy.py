from __future__ import annotations

from math import ceil, floor
from statistics import mean, median, stdev
from typing import Any


def _percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("历史价格不能为空")
    position = (len(ordered) - 1) * ratio
    lower = floor(position)
    upper = min(len(ordered) - 1, lower + 1)
    return ordered[lower] * (1 - (position - lower)) + ordered[upper] * (position - lower)


def build_grid(lower: float, upper: float, grid_count: int) -> list[float]:
    if lower <= 0 or upper <= lower or grid_count < 2:
        raise ValueError("网格区间或网格数量无效")
    step = (upper - lower) / grid_count
    return [round(lower + step * index, 4) for index in range(grid_count + 1)]


def suggest_grid(bars: list[dict[str, Any]], grid_count: int = 8, capital: float = 100000, mode: str = "classic") -> dict[str, Any]:
    closes = [float(bar["close"]) for bar in bars if bar.get("close") is not None]
    if len(closes) < 2:
        raise ValueError("至少需要 2 个交易日的数据")
    center = median(closes)
    lower = min(min(closes), _percentile(closes, 0.2), center * 0.97)
    upper = max(max(closes), _percentile(closes, 0.8), center * 1.03)
    reference_price = closes[-1]
    step = (upper - lower) / grid_count
    per_grid_amount = max(1000, floor(capital / grid_count / 100) * 100)
    lot_size = max(100, floor(per_grid_amount / reference_price / 100) * 100)
    minimum_capital = ceil(max(100 * upper * grid_count * 0.35, 10000) / 100) * 100
    return {
        "lower": round(lower, 2), "upper": round(upper, 2), "center": round(center, 2),
        "referencePrice": round(reference_price, 2), "step": round(step, 3),
        "upTriggerPct": round(step / reference_price * 100, 2), "downTriggerPct": round(step / reference_price * 100, 2),
        "perGridAmount": round(per_grid_amount, 2), "lotSize": lot_size,
        "suggestedCapital": round(max(capital, minimum_capital), 2), "minimumCapital": round(minimum_capital, 2),
        "mode": mode,
        "buyRule": "价格下跌一个网格买入" if mode == "classic" else "价格上涨一个网格买入",
        "sellRule": "价格上涨一个网格卖出" if mode == "classic" else "价格下跌一个网格卖出",
        "levels": build_grid(lower, upper, grid_count), "lookback": len(closes),
    }


def transaction_fee(side: str, value: float, fee_bps: float, security_type: str = "股票", exchange: str = "上交所") -> float:
    commission_rate = fee_bps / 10000
    commission = max(5.0, value * commission_rate)
    stamp_duty = value * 0.0005 if security_type == "股票" and side == "sell" else 0.0
    transfer = value * 0.00001 if security_type == "股票" and exchange == "上交所" else 0.0
    return commission + stamp_duty + transfer


def buy_and_hold_benchmark(
    bars: list[dict[str, Any]], capital: float, fee_bps: float = 3,
    security_type: str = "股票", exchange: str = "上交所",
) -> dict[str, Any]:
    """Buy-and-hold reference: fill max 100-share lots on the first close, hold to the last."""
    if not bars:
        raise ValueError("历史数据不能为空")
    first_close = float(bars[0]["close"])
    last_close = float(bars[-1]["close"])
    lots = floor(capital / first_close / 100) * 100
    while lots and lots * first_close + transaction_fee("buy", lots * first_close, fee_bps, security_type, exchange) > capital:
        lots -= 100
    invested = lots * first_close if lots else 0
    cash = capital - invested - (transaction_fee("buy", invested, fee_bps, security_type, exchange) if lots else 0)
    end_equity = cash + lots * last_close if lots else cash
    curve = [
        {"date": bar.get("date", ""), "equity": round((cash + lots * float(bar["close"])) / capital, 6)}
        for bar in bars
    ]
    return {
        "endEquity": round(end_equity, 2),
        "returnPct": round((end_equity / capital - 1) * 100, 2),
        "curve": curve,
    }


def backtest_grid(
    bars: list[dict[str, Any]], lower: float, upper: float, grid_count: int, capital: float,
    fee_bps: float = 3, mode: str = "classic", security_type: str = "股票",
    exchange: str = "上交所", settlement_days: int = 1, slippage_bps: float = 5, price_limit_pct: float = 0.1,
) -> dict[str, Any]:
    if len(bars) < 2 or capital <= 0:
        raise ValueError("历史数据或本金无效")
    if mode not in {"classic", "trend"}:
        raise ValueError("网格模式无效")
    levels = build_grid(lower, upper, grid_count)

    def fee(side: str, value: float) -> float:
        return transaction_fee(side, value, fee_bps, security_type, exchange)

    first_close = float(bars[0]["close"])
    cash = capital
    initial_lots = floor((capital / 2) / first_close / 100) * 100
    while initial_lots and initial_lots * first_close + fee("buy", initial_lots * first_close) > cash:
        initial_lots -= 100
    initial_value = initial_lots * first_close
    cash -= initial_value + fee("buy", initial_value) if initial_lots else 0
    shares = initial_lots
    lots_held = [{"shares": initial_lots, "available_day": -1}] if initial_lots else []
    order_budget = capital / grid_count
    previous_close = first_close
    trades: list[dict[str, Any]] = []
    equity_curve = [cash + shares * first_close]
    skipped_limit_up_days = 0
    skipped_limit_down_days = 0
    skipped_suspension_days = 0
    one_price_limit_up_days = 0
    one_price_limit_down_days = 0

    for day_index, bar in enumerate(bars[1:], start=1):
        low = float(bar.get("low") or bar["close"])
        high = float(bar.get("high") or bar["close"])
        close = float(bar["close"])
        volume = bar.get("volume")
        if volume is not None and float(volume) <= 0:
            skipped_suspension_days += 1
            equity_curve.append(cash + shares * close)
            previous_close = close
            continue
        upper_limit = previous_close * (1 + price_limit_pct)
        lower_limit = previous_close * (1 - price_limit_pct)
        limit_up = high >= upper_limit - 0.005
        limit_down = low <= lower_limit + 0.005
        if high == low:
            # 一字板：涨停只可卖、跌停只可买。既有 limit_up/limit_down 清空规则
            # 已保证这一语义，此处只负责准确计数。
            if limit_up:
                one_price_limit_up_days += 1
            elif limit_down:
                one_price_limit_down_days += 1
        skipped_limit_up_days += int(limit_up)
        skipped_limit_down_days += int(limit_down)
        date = bar.get("date", "")
        if mode == "classic":
            buy_levels = sorted([level for level in levels[1:-1] if low <= level < previous_close], reverse=True)
            sell_levels = sorted(level for level in levels[1:-1] if previous_close < level <= high)
        else:
            buy_levels = sorted([level for level in levels[1:-1] if previous_close < level <= high], reverse=True)
            sell_levels = sorted((level for level in levels[1:-1] if low <= level < previous_close), reverse=True)

        # Daily OHLC cannot establish queue position at a price limit. Do not assume
        # that breakout buys at limit-up or stop sells at limit-down were filled.
        if limit_up:
            buy_levels = []
        if limit_down:
            sell_levels = []

        for level in buy_levels:
            lots = floor(order_budget / level / 100) * 100
            while lots and lots * level + fee("buy", lots * level) > cash:
                lots -= 100
            if lots:
                execution_price = min(high, level * (1 + slippage_bps / 10000))
                value = lots * execution_price
                trade_fee = fee("buy", value)
                cash -= value + trade_fee
                shares += lots
                lots_held.append({"shares": lots, "available_day": day_index + settlement_days})
                trades.append({"date": date, "side": "buy", "triggerPrice": round(level, 2), "price": round(execution_price, 2), "shares": lots, "fee": round(trade_fee, 2)})

        for level in sell_levels:
            eligible = sum(lot["shares"] for lot in lots_held if lot["available_day"] <= day_index)
            lots = min(eligible, floor(order_budget / level / 100) * 100)
            if not lots:
                continue
            remaining = lots
            for lot in lots_held:
                if lot["available_day"] <= day_index and remaining:
                    consumed = min(lot["shares"], remaining)
                    lot["shares"] -= consumed
                    remaining -= consumed
            lots_held = [lot for lot in lots_held if lot["shares"]]
            execution_price = max(low, level * (1 - slippage_bps / 10000))
            value = lots * execution_price
            trade_fee = fee("sell", value)
            cash += value - trade_fee
            shares -= lots
            trades.append({"date": date, "side": "sell", "triggerPrice": round(level, 2), "price": round(execution_price, 2), "shares": lots, "fee": round(trade_fee, 2)})

        equity_curve.append(cash + shares * close)
        previous_close = close

    end_equity = equity_curve[-1]
    peak, max_drawdown = equity_curve[0], 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 0)
    days = max(1, len(bars) - 1)
    total_return = end_equity / capital - 1
    annualized = (max(end_equity, 1) / capital) ** (252 / days) - 1 if days >= 20 else None

    benchmark = buy_and_hold_benchmark(bars, capital, fee_bps, security_type, exchange)
    benchmark_return_pct = benchmark["returnPct"]
    excess_return_pct = round(total_return * 100 - benchmark_return_pct, 2)

    # Risk-adjusted metrics from the strategy daily equity curve.
    daily_returns = [equity_curve[i] / equity_curve[i - 1] - 1 for i in range(1, len(equity_curve)) if equity_curve[i - 1]]
    vol = None
    if len(daily_returns) >= 2:
        sample_vol = stdev(daily_returns)
        if sample_vol > 0:
            vol = sample_vol
    mean_daily = mean(daily_returns) if daily_returns else 0.0
    annualized_volatility = round(vol * (252 ** 0.5) * 100, 2) if vol else None
    sharpe = round(mean_daily / vol * (252 ** 0.5), 2) if vol and len(daily_returns) >= 20 else None
    total_fees = round(sum(trade["fee"] for trade in trades), 2)
    turnover_multiple = round(sum(trade["price"] * trade["shares"] for trade in trades) / capital, 2)
    equity_curve_normalized = [
        {"date": bar.get("date", ""), "equity": round(eq / capital, 6)}
        for bar, eq in zip(bars, equity_curve)
    ]

    metrics = {
        "startEquity": round(capital, 2),
        "endEquity": round(end_equity, 2),
        "returnPct": round(total_return * 100, 2),
        "annualizedReturnPct": round(annualized * 100, 2) if annualized is not None else None,
        "maxDrawdownPct": round(max_drawdown * 100, 2),
        "tradeCount": len(trades),
        "buyCount": sum(item["side"] == "buy" for item in trades),
        "sellCount": sum(item["side"] == "sell" for item in trades),
        "skippedLimitUpDays": skipped_limit_up_days,
        "skippedLimitDownDays": skipped_limit_down_days,
        "skippedSuspensionDays": skipped_suspension_days,
        "onePriceLimitUpDays": one_price_limit_up_days,
        "onePriceLimitDownDays": one_price_limit_down_days,
        "benchmarkReturnPct": benchmark_return_pct,
        "excessReturnPct": excess_return_pct,
        "annualizedVolatilityPct": annualized_volatility,
        "sharpeRatio": sharpe,
        "totalFees": total_fees,
        "turnoverMultiple": turnover_multiple,
    }
    round_trip_returns = _round_trip_returns(trades)
    win_count = sum(1 for r in round_trip_returns if r > 0)
    total_count = len(round_trip_returns)
    gross_profit = sum(r for r in round_trip_returns if r > 0)
    gross_loss = abs(sum(r for r in round_trip_returns if r < 0))
    metrics["winRatePct"] = round(win_count / total_count * 100, 1) if total_count else None
    metrics["avgGridReturnPct"] = round(mean(round_trip_returns) * 100, 2) if round_trip_returns else None
    metrics["medianGridReturnPct"] = round(median(round_trip_returns) * 100, 2) if round_trip_returns else None
    metrics["maxDrawdownDurationDays"] = _max_drawdown_duration(equity_curve)
    metrics["profitFactor"] = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (None if not total_count else float("inf"))
    return {
        "levels": levels,
        "trades": trades[-100:],
        "equityCurve": equity_curve_normalized,
        "benchmarkCurve": benchmark["curve"],
        "metrics": metrics,
        "assumptions": ("经典网格按日内先低后高触发；趋势网格按日内先高后低触发。"
                        f"按 100 股整数倍、T+{settlement_days} 可卖、{slippage_bps} BP 滑点和股票/ETF差异化费用计算。"
                        "一字涨停日仅可卖出、一字跌停日仅可买入，停牌日整日跳过。"),
    }


def _round_trip_returns(trades: list[dict[str, Any]]) -> list[float]:
    """FIFO 配对买卖，返回每笔完整 round trip 的收益率。"""
    buy_queue: list[list[float]] = []  # [shares, cost, fee_per_share]
    returns: list[float] = []
    for t in trades:
        if t["side"] == "buy":
            buy_queue.append([float(t["shares"]), float(t["price"]), float(t["fee"]) / float(t["shares"])])
        elif t["side"] == "sell":
            remaining = float(t["shares"])
            sell_proceeds = remaining * float(t["price"]) - float(t["fee"])
            buy_cost = 0.0
            while remaining > 0.001 and buy_queue:
                entry = buy_queue[0]
                consume = min(entry[0], remaining)
                buy_cost += consume * (entry[1] + entry[2])
                entry[0] -= consume
                remaining -= consume
                if entry[0] < 0.001:
                    buy_queue.pop(0)
            if buy_cost > 0:
                returns.append((sell_proceeds - buy_cost) / buy_cost)
    return returns


def _max_drawdown_duration(equity_curve: list[float]) -> int:
    """从权益曲线计算最长回撤持续期（交易日数）。"""
    if not equity_curve:
        return 0
    peak_idx = 0
    max_duration = 0
    for i, eq in enumerate(equity_curve):
        if eq >= equity_curve[peak_idx]:
            peak_idx = i
        else:
            duration = i - peak_idx
            if duration > max_duration:
                max_duration = duration
    return max_duration


def optimize_grid(
    bars: list[dict[str, Any]], capital: float, fee_bps: float = 3, mode: str = "classic",
    security_type: str = "股票", exchange: str = "上交所", settlement_days: int = 1, slippage_bps: float = 5, price_limit_pct: float = 0.1,
) -> list[dict[str, Any]]:
    split_index = max(2, int(len(bars) * 0.7))
    training_bars, validation_bars = bars[:split_index], bars[split_index - 1:]
    baseline = suggest_grid(training_bars, grid_count=8, capital=capital, mode=mode)
    center, lower_gap, upper_gap = baseline["center"], baseline["center"] - baseline["lower"], baseline["upper"] - baseline["center"]
    candidates = []
    for grid_count in (6, 8, 10, 12):
        for multiplier in (0.8, 1.0, 1.2):
            lower, upper = max(0.01, center - lower_gap * multiplier), center + upper_gap * multiplier
            in_sample = backtest_grid(training_bars, lower, upper, grid_count, capital, fee_bps, mode, security_type, exchange, settlement_days, slippage_bps, price_limit_pct)
            out_of_sample = backtest_grid(validation_bars, lower, upper, grid_count, capital, fee_bps, mode, security_type, exchange, settlement_days, slippage_bps, price_limit_pct)
            in_metrics = in_sample["metrics"]
            out_metrics = out_of_sample["metrics"]
            if len(validation_bars) < 20:
                flag = "样本外过短"
            elif abs(in_metrics["returnPct"] - out_metrics["returnPct"]) > 10:
                flag = "可能过拟合"
            else:
                flag = None
            recommended = not (
                out_metrics["tradeCount"] == 0
                or out_metrics["buyCount"] == 0
                or out_metrics["sellCount"] == 0
                or out_metrics["excessReturnPct"] <= 0
            )
            candidates.append({
                "gridCount": grid_count,
                "lower": round(lower, 2),
                "upper": round(upper, 2),
                "step": round((upper - lower) / grid_count, 3),
                "inSampleMetrics": in_metrics,
                "metrics": out_metrics,
                "flag": flag,
                "recommended": recommended,
            })

    def sort_key(item: dict[str, Any]) -> tuple[float, float, float]:
        m = item["metrics"]
        diff = abs(item["inSampleMetrics"]["returnPct"] - m["returnPct"])
        return (-m.get("excessReturnPct", -999.0), m.get("maxDrawdownPct", 999.0), diff)

    return sorted(candidates, key=sort_key)
