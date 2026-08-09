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


def backtest_grid(
    bars: list[dict[str, Any]], lower: float, upper: float, grid_count: int, capital: float,
    fee_bps: float = 3, mode: str = "classic", security_type: str = "股票",
    exchange: str = "上交所", settlement_days: int = 1,
) -> dict[str, Any]:
    if len(bars) < 2 or capital <= 0:
        raise ValueError("历史数据或本金无效")
    if mode not in {"classic", "trend"}:
        raise ValueError("网格模式无效")
    levels = build_grid(lower, upper, grid_count)
    commission_rate = fee_bps / 10000

    def fee(side: str, value: float) -> float:
        commission = max(5.0, value * commission_rate)
        stamp_duty = value * 0.0005 if security_type == "股票" and side == "sell" else 0.0
        transfer = value * 0.00001 if security_type == "股票" and exchange == "上交所" else 0.0
        return commission + stamp_duty + transfer

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

    for day_index, bar in enumerate(bars[1:], start=1):
        low = float(bar.get("low") or bar["close"])
        high = float(bar.get("high") or bar["close"])
        date = bar.get("date", "")
        if mode == "classic":
            buy_levels = sorted([level for level in levels[1:-1] if low <= level < previous_close], reverse=True)
            sell_levels = sorted(level for level in levels[1:-1] if previous_close < level <= high)
        else:
            buy_levels = sorted([level for level in levels[1:-1] if previous_close < level <= high], reverse=True)
            sell_levels = sorted((level for level in levels[1:-1] if low <= level < previous_close), reverse=True)

        for level in buy_levels:
            lots = floor(order_budget / level / 100) * 100
            while lots and lots * level + fee("buy", lots * level) > cash:
                lots -= 100
            if lots:
                value = lots * level
                trade_fee = fee("buy", value)
                cash -= value + trade_fee
                shares += lots
                lots_held.append({"shares": lots, "available_day": day_index + settlement_days})
                trades.append({"date": date, "side": "buy", "price": round(level, 2), "shares": lots, "fee": round(trade_fee, 2)})

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
            value = lots * level
            trade_fee = fee("sell", value)
            cash += value - trade_fee
            shares -= lots
            trades.append({"date": date, "side": "sell", "price": round(level, 2), "shares": lots, "fee": round(trade_fee, 2)})

        close = float(bar["close"])
        equity_curve.append(cash + shares * close)
        previous_close = close

    end_equity = equity_curve[-1]
    peak, max_drawdown = equity_curve[0], 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, (peak - equity) / peak if peak else 0)
    days = max(1, len(bars) - 1)
    total_return = end_equity / capital - 1
    annualized = (max(end_equity, 1) / capital) ** (252 / days) - 1
    return {
        "levels": levels, "trades": trades[-100:],
        "metrics": {"startEquity": round(capital, 2), "endEquity": round(end_equity, 2), "returnPct": round(total_return * 100, 2), "annualizedReturnPct": round(annualized * 100, 2), "maxDrawdownPct": round(max_drawdown * 100, 2), "tradeCount": len(trades), "buyCount": sum(item["side"] == "buy" for item in trades), "sellCount": sum(item["side"] == "sell" for item in trades)},
        "assumptions": ("经典网格按日内先低后高触发；趋势网格按日内先高后低触发。"
                        f"按 100 股整数倍、T+{settlement_days} 可卖和股票/ETF差异化费用计算。"),
    }


def optimize_grid(
    bars: list[dict[str, Any]], capital: float, fee_bps: float = 3, mode: str = "classic",
    security_type: str = "股票", exchange: str = "上交所", settlement_days: int = 1,
) -> list[dict[str, Any]]:
    split_index = max(2, int(len(bars) * 0.7))
    training_bars, validation_bars = bars[:split_index], bars[split_index - 1:]
    baseline = suggest_grid(training_bars, grid_count=8, capital=capital, mode=mode)
    center, lower_gap, upper_gap = baseline["center"], baseline["center"] - baseline["lower"], baseline["upper"] - baseline["center"]
    candidates = []
    for grid_count in (6, 8, 10, 12):
        for multiplier in (0.8, 1.0, 1.2):
            lower, upper = max(0.01, center - lower_gap * multiplier), center + upper_gap * multiplier
            in_sample = backtest_grid(training_bars, lower, upper, grid_count, capital, fee_bps, mode, security_type, exchange, settlement_days)
            out_of_sample = backtest_grid(validation_bars, lower, upper, grid_count, capital, fee_bps, mode, security_type, exchange, settlement_days)
            candidates.append({"gridCount": grid_count, "lower": round(lower, 2), "upper": round(upper, 2), "step": round((upper - lower) / grid_count, 3), "inSampleMetrics": in_sample["metrics"], **out_of_sample})
    return sorted(candidates, key=lambda item: (item["metrics"]["returnPct"], -item["metrics"]["maxDrawdownPct"]), reverse=True)
