from __future__ import annotations

from math import floor
from statistics import median
from typing import Any


def _percentile(values: list[float], ratio: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("历史价格不能为空")
    position = (len(ordered) - 1) * ratio
    lower = floor(position)
    upper = min(len(ordered) - 1, lower + 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def build_grid(lower: float, upper: float, grid_count: int) -> list[float]:
    if lower <= 0 or upper <= lower or grid_count < 2:
        raise ValueError("网格区间或网格数量无效")
    step = (upper - lower) / grid_count
    return [round(lower + step * index, 4) for index in range(grid_count + 1)]


def suggest_grid(bars: list[dict[str, Any]], grid_count: int = 8) -> dict[str, Any]:
    closes = [float(bar["close"]) for bar in bars if bar.get("close") is not None]
    if len(closes) < 2:
        raise ValueError("至少需要 2 个交易日的数据")
    center = median(closes)
    lower = min(_percentile(closes, 0.2), center * 0.97)
    upper = max(_percentile(closes, 0.8), center * 1.03)
    return {
        "lower": round(lower, 2),
        "upper": round(upper, 2),
        "center": round(center, 2),
        "levels": build_grid(lower, upper, grid_count),
        "lookback": len(closes),
    }


def backtest_grid(
    bars: list[dict[str, Any]],
    lower: float,
    upper: float,
    grid_count: int,
    capital: float,
    fee_bps: float = 3,
) -> dict[str, Any]:
    if len(bars) < 2:
        raise ValueError("至少需要 2 个交易日的数据")
    levels = build_grid(lower, upper, grid_count)
    if capital <= 0:
        raise ValueError("本金必须大于 0")

    fee_rate = fee_bps / 10000
    first_close = float(bars[0]["close"])
    cash = capital / 2
    shares = floor((capital / 2) / first_close / 100) * 100
    cash -= shares * first_close * (1 + fee_rate)
    order_budget = capital / grid_count
    previous_close = first_close
    trades: list[dict[str, Any]] = []
    equity_curve = [cash + shares * first_close]

    for bar in bars[1:]:
        low = float(bar.get("low") or bar["close"])
        high = float(bar.get("high") or bar["close"])
        date = bar.get("date", "")
        buy_levels = [level for level in levels[1:-1] if low <= level < previous_close]
        for level in sorted(buy_levels, reverse=True):
            lots = floor(order_budget / level / 100) * 100
            cost = lots * level * (1 + fee_rate)
            if lots and cash >= cost:
                cash -= cost
                shares += lots
                trades.append({"date": date, "side": "buy", "price": round(level, 2), "shares": lots})

        sell_levels = [level for level in levels[1:-1] if previous_close < level <= high]
        for level in sorted(sell_levels):
            lots = min(shares, floor(order_budget / level / 100) * 100)
            if lots:
                cash += lots * level * (1 - fee_rate)
                shares -= lots
                trades.append({"date": date, "side": "sell", "price": round(level, 2), "shares": lots})

        close = float(bar["close"])
        equity_curve.append(cash + shares * close)
        previous_close = close

    end_equity = equity_curve[-1]
    peak = equity_curve[0]
    max_drawdown = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 0)
    days = max(1, len(bars) - 1)
    total_return = end_equity / capital - 1
    annualized = (max(end_equity, 1) / capital) ** (252 / days) - 1
    return {
        "levels": levels,
        "trades": trades[-100:],
        "metrics": {
            "startEquity": round(capital, 2),
            "endEquity": round(end_equity, 2),
            "returnPct": round(total_return * 100, 2),
            "annualizedReturnPct": round(annualized * 100, 2),
            "maxDrawdownPct": round(max_drawdown * 100, 2),
            "tradeCount": len(trades),
            "buyCount": sum(1 for trade in trades if trade["side"] == "buy"),
            "sellCount": sum(1 for trade in trades if trade["side"] == "sell"),
        },
        "assumptions": "日线回测按每根 K 线先触发最低价买入，再触发最高价卖出；按 100 股整数倍和双边手续费计算。",
    }


def optimize_grid(bars: list[dict[str, Any]], capital: float, fee_bps: float = 3) -> list[dict[str, Any]]:
    baseline = suggest_grid(bars, grid_count=8)
    center = baseline["center"]
    lower_gap = center - baseline["lower"]
    upper_gap = baseline["upper"] - center
    candidates = []
    for grid_count in (6, 8, 10, 12):
        for multiplier in (0.8, 1.0, 1.2):
            lower = max(0.01, center - lower_gap * multiplier)
            upper = center + upper_gap * multiplier
            result = backtest_grid(bars, lower, upper, grid_count, capital, fee_bps)
            candidates.append({
                "gridCount": grid_count,
                "lower": round(lower, 2),
                "upper": round(upper, 2),
                "step": round((upper - lower) / grid_count, 3),
                **result,
            })
    return sorted(candidates, key=lambda item: item["metrics"]["endEquity"], reverse=True)
