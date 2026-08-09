from __future__ import annotations

from math import ceil, floor
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


def suggest_grid(bars: list[dict[str, Any]], grid_count: int = 8, capital: float = 100000, mode: str = "classic") -> dict[str, Any]:
    closes = [float(bar["close"]) for bar in bars if bar.get("close") is not None]
    if len(closes) < 2:
        raise ValueError("至少需要 2 个交易日的数据")
    center = median(closes)
    lower = min(min(closes), _percentile(closes, 0.2), center * 0.97)
    upper = max(max(closes), _percentile(closes, 0.8), center * 1.03)
    levels = build_grid(lower, upper, grid_count)
    reference_price = float(closes[-1])
    step = (upper - lower) / grid_count
    per_grid_amount = max(1000, floor(capital / grid_count / 100) * 100)
    lot_size = max(100, floor(per_grid_amount / reference_price / 100) * 100)
    minimum_capital = ceil(max(100 * upper * grid_count * 0.35, 10000) / 100) * 100
    return {
        "lower": round(lower, 2),
        "upper": round(upper, 2),
        "center": round(center, 2),
        "referencePrice": round(reference_price, 2),
        "step": round(step, 3),
        "upTriggerPct": round(step / reference_price * 100, 2),
        "downTriggerPct": round(step / reference_price * 100, 2),
        "perGridAmount": round(per_grid_amount, 2),
        "lotSize": lot_size,
        "suggestedCapital": round(max(capital, minimum_capital), 2),
        "minimumCapital": round(minimum_capital, 2),
        "mode": mode,
        "buyRule": "价格下跌一个网格买入" if mode == "classic" else "价格上涨一个网格买入",
        "sellRule": "价格上涨一个网格卖出" if mode == "classic" else "价格下跌一个网格卖出",
        "levels": levels,
        "lookback": len(closes),
    }


def backtest_grid(
    bars: list[dict[str, Any]],
    lower: float,
    upper: float,
    grid_count: int,
    capital: float,
    fee_bps: float = 3,
    mode: str = "classic",
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
        if mode == "classic":
            buy_levels = [level for level in levels[1:-1] if low <= level < previous_close]
            sell_levels = [level for level in levels[1:-1] if previous_close < level <= high]
        elif mode == "trend":
            buy_levels = [level for level in levels[1:-1] if previous_close < level <= high]
            sell_levels = [level for level in levels[1:-1] if low <= level < previous_close]
        else:
            raise ValueError("网格模式无效")
        for level in sorted(buy_levels, reverse=True):
            lots = floor(order_budget / level / 100) * 100
            cost = lots * level * (1 + fee_rate)
            if lots and cash >= cost:
                cash -= cost
                shares += lots
                trades.append({"date": date, "side": "buy", "price": round(level, 2), "shares": lots})

        for level in sorted(sell_levels, reverse=mode == "trend"):
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
        "assumptions": ("经典网格按日内先低后高触发；趋势网格按日内先高后低触发。"
                        "按 100 股整数倍和双边手续费计算。"),
    }


def optimize_grid(bars: list[dict[str, Any]], capital: float, fee_bps: float = 3, mode: str = "classic") -> list[dict[str, Any]]:
    baseline = suggest_grid(bars, grid_count=8, capital=capital, mode=mode)
    center = baseline["center"]
    lower_gap = center - baseline["lower"]
    upper_gap = baseline["upper"] - center
    candidates = []
    for grid_count in (6, 8, 10, 12):
        for multiplier in (0.8, 1.0, 1.2):
            lower = max(0.01, center - lower_gap * multiplier)
            upper = center + upper_gap * multiplier
            result = backtest_grid(bars, lower, upper, grid_count, capital, fee_bps, mode)
            candidates.append({
                "gridCount": grid_count,
                "lower": round(lower, 2),
                "upper": round(upper, 2),
                "step": round((upper - lower) / grid_count, 3),
                **result,
            })
    return sorted(candidates, key=lambda item: item["metrics"]["endEquity"], reverse=True)
