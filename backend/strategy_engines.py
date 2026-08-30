from __future__ import annotations

from math import floor
from typing import Any

from backend.grid_strategy import (
    _compute_metrics,
    buy_and_hold_benchmark,
    transaction_fee,
)

# ── helpers ──────────────────────────────────────────────────────────────


def _ema(values: list[float], period: int) -> list[float]:
    """Return EMA of `values` with smoothing factor 2/(period+1)."""
    if not values or period < 1:
        return []
    multiplier = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append((v - result[-1]) * multiplier + result[-1])
    return result


def _ma(values: list[float], period: int) -> list[float | None]:
    """Simple moving average (prefix positions filled with None-equivalent)."""
    if not values or period < 1:
        return []
    cum = sum(values[:period])
    result = [None] * (period - 1) + [cum / period]
    for i in range(period, len(values)):
        cum += values[i] - values[i - period]
        result.append(cum / period)
    return result


# ── 双均线 ───────────────────────────────────────────────────────────────


def backtest_ma_cross(bars: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    """双均线策略：快线上穿慢线买入，下穿卖出。"""
    fast = int(config.get("fastPeriod", 5))
    slow = int(config.get("slowPeriod", 20))
    if fast >= slow:
        raise ValueError("fastPeriod 必须小于 slowPeriod")
    capital = float(config.get("capital", 100000))
    fee_bps = float(config.get("feeBps", 3))
    security_type = config.get("securityType", "股票")
    exchange = config.get("exchange", "上交所")

    closes = [float(b["close"]) for b in bars]
    ma_fast = _ma(closes, fast)
    ma_slow = _ma(closes, slow)

    cash = capital
    shares = 0
    trades: list[dict[str, Any]] = []
    equity_curve = [cash]
    position = 0  # 0=empty, 1=full

    for i in range(1, len(bars)):
        close = float(bars[i]["close"])
        date = bars[i].get("date", "")

        prev_fast = ma_fast[i - 1]
        prev_slow = ma_slow[i - 1]
        curr_fast = ma_fast[i]
        curr_slow = ma_slow[i]

        # 当前或前一根均线缺失（预热区）时不构成交叉信号
        if curr_fast is None or curr_slow is None or prev_fast is None or prev_slow is None:
            equity_curve.append(cash + shares * close)
            continue

        # Golden cross: fast crosses above slow
        if position == 0 and prev_fast <= prev_slow and curr_fast > curr_slow:
            # buy full position
            lots = floor(cash / close / 100) * 100
            if lots:
                value = lots * close
                fee = transaction_fee("buy", value, fee_bps, security_type, exchange)
                while lots and value + fee > cash:
                    lots -= 100
                    value = lots * close
                    fee = transaction_fee("buy", value, fee_bps, security_type, exchange)
                if lots:
                    cash -= value + fee
                    shares += lots
                    trades.append(
                        {
                            "date": date,
                            "side": "buy",
                            "triggerPrice": None,
                            "price": round(close, 2),
                            "shares": lots,
                            "fee": round(fee, 2),
                        }
                    )
                    position = 1

        # Death cross: fast crosses below slow
        elif position == 1 and prev_fast >= prev_slow and curr_fast < curr_slow:
            if shares:
                value = shares * close
                fee = transaction_fee("sell", value, fee_bps, security_type, exchange)
                cash += value - fee
                trades.append(
                    {
                        "date": date,
                        "side": "sell",
                        "triggerPrice": None,
                        "price": round(close, 2),
                        "shares": shares,
                        "fee": round(fee, 2),
                    }
                )
                shares = 0
                position = 0

        equity_curve.append(cash + shares * close)

    normalised = [{"date": b.get("date", ""), "equity": round(eq / capital, 6)} for b, eq in zip(bars, equity_curve)]
    benchmark = buy_and_hold_benchmark(bars, capital, fee_bps, security_type, exchange)
    metrics = _compute_metrics(bars, trades, equity_curve, capital, fee_bps, security_type, exchange)
    return {
        "trades": trades[-100:],
        "equityCurve": normalised,
        "benchmarkCurve": benchmark["curve"],
        "metrics": metrics,
        "assumptions": (
            f"双均线策略：快线 MA({fast}) 上穿慢线 MA({slow}) 时全仓买入，下穿时全仓卖出。"
            "按当日收盘价成交、100 股整数倍、T+1 可卖。"
            "费用包含佣金（最低 5 元）、印花税（卖出 0.05%）及过户费。"
            "结果仅用于研究，不代表未来收益。"
        ),
    }


# ── 定投 DCA ─────────────────────────────────────────────────────────────


def backtest_dca(bars: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    """定投策略：每 N 个交易日固定金额买入，止盈/止损线全仓卖出。"""
    amount_per = float(config.get("amountPerPeriod", 5000))
    interval = int(config.get("intervalDays", 5))
    stop_profit = float(config.get("stopProfitPct", 20)) / 100
    stop_loss = float(config.get("stopLossPct", 15)) / 100
    capital = float(config.get("capital", 100000))
    fee_bps = float(config.get("feeBps", 3))
    security_type = config.get("securityType", "股票")
    exchange = config.get("exchange", "上交所")

    if amount_per <= 0 or interval <= 0:
        raise ValueError("amountPerPeriod 和 intervalDays 必须大于 0")

    cash = capital
    shares = 0
    position_cost = 0.0  # 当前持仓的买入总成本（含费用）
    pending = 0.0  # 累计未投入的定投资金
    trades: list[dict[str, Any]] = []
    equity_curve = [cash]

    for i in range(1, len(bars)):
        close = float(bars[i]["close"])
        date = bars[i].get("date", "")

        # 定投买入：每 interval 天累积一次，资金不足一手时滚入下一期
        if (i % interval) == 0:
            pending += amount_per
            invest = min(pending, cash)
            lots = floor(invest / close / 100) * 100
            if lots:
                value = lots * close
                fee = transaction_fee("buy", value, fee_bps, security_type, exchange)
                while lots and value + fee > cash:
                    lots -= 100
                    value = lots * close
                    fee = transaction_fee("buy", value, fee_bps, security_type, exchange)
                if lots:
                    cash -= value + fee
                    shares += lots
                    position_cost += value + fee
                    pending -= value + fee
                    trades.append(
                        {
                            "date": date,
                            "side": "buy",
                            "triggerPrice": None,
                            "price": round(close, 2),
                            "shares": lots,
                            "fee": round(fee, 2),
                        }
                    )

        # 基于持仓成本的止盈/止损检查
        if shares > 0 and position_cost > 0:
            position_value = shares * close
            return_pct = position_value / position_cost - 1
            if return_pct >= stop_profit or return_pct <= -stop_loss:
                value = position_value
                fee = transaction_fee("sell", value, fee_bps, security_type, exchange)
                cash += value - fee
                trades.append(
                    {
                        "date": date,
                        "side": "sell",
                        "triggerPrice": None,
                        "price": round(close, 2),
                        "shares": shares,
                        "fee": round(fee, 2),
                    }
                )
                shares = 0
                position_cost = 0.0

        equity_curve.append(cash + shares * close)

    normalised = [{"date": b.get("date", ""), "equity": round(eq / capital, 6)} for b, eq in zip(bars, equity_curve)]
    benchmark = buy_and_hold_benchmark(bars, capital, fee_bps, security_type, exchange)
    metrics = _compute_metrics(bars, trades, equity_curve, capital, fee_bps, security_type, exchange)
    return {
        "trades": trades[-100:],
        "equityCurve": normalised,
        "benchmarkCurve": benchmark["curve"],
        "metrics": metrics,
        "assumptions": (
            f"定投（DCA）：每 {interval} 个交易日投入 {amount_per:.0f} 元，"
            f"止盈 {stop_profit * 100:.0f}% / 止损 {stop_loss * 100:.0f}%。"
            "资金不足一手时滚入下一期。按当日收盘价成交、100 股整数倍。"
            "费用包含佣金（最低 5 元）、印花税（卖出 0.05%）及过户费。"
            "结果仅用于研究，不代表未来收益。"
        ),
    }


# ── MACD ─────────────────────────────────────────────────────────────────


def backtest_macd(bars: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
    """MACD 策略：DIF 上穿 DEA 买入，下穿卖出。"""
    fast = int(config.get("fastPeriod", 12))
    slow = int(config.get("slowPeriod", 26))
    signal = int(config.get("signalPeriod", 9))
    if fast >= slow:
        raise ValueError("fastPeriod 必须小于 slowPeriod")
    capital = float(config.get("capital", 100000))
    fee_bps = float(config.get("feeBps", 3))
    security_type = config.get("securityType", "股票")
    exchange = config.get("exchange", "上交所")

    closes = [float(b["close"]) for b in bars]
    ema_fast = _ema(closes, fast)
    ema_slow = _ema(closes, slow)
    dif = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    dea = _ema(dif, signal)

    warmup = slow + signal  # bars needed before we can have valid DIF/DEA
    cash = capital
    shares = 0
    trades: list[dict[str, Any]] = []
    equity_curve = [cash]
    position = 0

    for i in range(1, len(bars)):
        close = float(bars[i]["close"])
        date = bars[i].get("date", "")

        # warmup: 无信号
        if i < warmup:
            equity_curve.append(cash + shares * close)
            continue

        prev_dif = dif[i - 1]
        prev_dea = dea[i - 1]
        curr_dif = dif[i]
        curr_dea = dea[i]

        # 金叉买入
        if position == 0 and prev_dif <= prev_dea and curr_dif > curr_dea:
            lots = floor(cash / close / 100) * 100
            if lots:
                value = lots * close
                fee = transaction_fee("buy", value, fee_bps, security_type, exchange)
                while lots and value + fee > cash:
                    lots -= 100
                    value = lots * close
                    fee = transaction_fee("buy", value, fee_bps, security_type, exchange)
                if lots:
                    cash -= value + fee
                    shares += lots
                    trades.append(
                        {
                            "date": date,
                            "side": "buy",
                            "triggerPrice": None,
                            "price": round(close, 2),
                            "shares": lots,
                            "fee": round(fee, 2),
                        }
                    )
                    position = 1

        # 死叉卖出
        elif position == 1 and prev_dif >= prev_dea and curr_dif < curr_dea:
            if shares:
                value = shares * close
                fee = transaction_fee("sell", value, fee_bps, security_type, exchange)
                cash += value - fee
                trades.append(
                    {
                        "date": date,
                        "side": "sell",
                        "triggerPrice": None,
                        "price": round(close, 2),
                        "shares": shares,
                        "fee": round(fee, 2),
                    }
                )
                shares = 0
                position = 0

        equity_curve.append(cash + shares * close)

    normalised = [{"date": b.get("date", ""), "equity": round(eq / capital, 6)} for b, eq in zip(bars, equity_curve)]
    benchmark = buy_and_hold_benchmark(bars, capital, fee_bps, security_type, exchange)
    metrics = _compute_metrics(bars, trades, equity_curve, capital, fee_bps, security_type, exchange)
    return {
        "trades": trades[-100:],
        "equityCurve": normalised,
        "benchmarkCurve": benchmark["curve"],
        "metrics": metrics,
        "assumptions": (
            f"MACD 策略：DIF (EMA{fast}−EMA{slow}) 上穿 DEA({signal}) 时全仓买入，下穿时全仓卖出。"
            f"预热期 {warmup} 根 K 线内无交易信号。"
            "按当日收盘价成交、100 股整数倍、T+1 可卖。"
            "费用包含佣金（最低 5 元）、印花税（卖出 0.05%）及过户费。"
            "结果仅用于研究，不代表未来收益。"
        ),
    }


# ── 注册表 ────────────────────────────────────────────────────────────────

STRATEGY_ENGINES: dict[str, dict[str, Any]] = {
    "ma_cross": {
        "label": "双均线",
        "backtest": backtest_ma_cross,
        "suggest": None,
        "configSchema": [
            {"key": "fastPeriod", "label": "快线周期", "type": "int", "default": 5, "min": 2, "max": 60},
            {"key": "slowPeriod", "label": "慢线周期", "type": "int", "default": 20, "min": 3, "max": 120},
        ],
    },
    "dca": {
        "label": "定投",
        "backtest": backtest_dca,
        "suggest": None,
        "configSchema": [
            {"key": "amountPerPeriod", "label": "每期投入", "type": "int", "default": 5000, "min": 1000, "step": 1000},
            {"key": "intervalDays", "label": "间隔交易日", "type": "int", "default": 5, "min": 1, "max": 60},
            {"key": "stopProfitPct", "label": "止盈 %", "type": "float", "default": 20, "min": 1, "max": 200},
            {"key": "stopLossPct", "label": "止损 %", "type": "float", "default": 15, "min": 1, "max": 100},
        ],
    },
    "macd": {
        "label": "MACD",
        "backtest": backtest_macd,
        "suggest": None,
        "configSchema": [
            {"key": "fastPeriod", "label": "快线周期", "type": "int", "default": 12, "min": 2, "max": 30},
            {"key": "slowPeriod", "label": "慢线周期", "type": "int", "default": 26, "min": 5, "max": 60},
            {"key": "signalPeriod", "label": "信号周期", "type": "int", "default": 9, "min": 2, "max": 30},
        ],
    },
}
