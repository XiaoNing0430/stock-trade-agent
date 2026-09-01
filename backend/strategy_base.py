"""策略基类：统一信号生成 → 交易执行 → 指标计算。

子类只需实现 signal_at(index, state) 返回 Signal（买卖决策），
基类统一处理资金切分、100 股整手、手续费、T+1、权益曲线、基准与指标。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from math import floor
from typing import Any, Literal

from backend.grid_strategy import _compute_metrics, buy_and_hold_benchmark, transaction_fee


@dataclass
class Signal:
    date: str
    side: Literal["buy", "sell"]
    price: float
    reason: str = ""
    amount: float | None = None  # 买入投入金额；None = 全部可用现金
    module: str | None = None  # 模块标签（多因子统计用）


@dataclass
class ExecutionState:
    shares: float = 0.0
    cash: float = 0.0
    position_cost: float = 0.0  # 当前持仓累计买入成本（含费），供止盈止损判断


class BaseStrategy(ABC):
    id: str = ""
    label: str = ""
    config_schema: list[dict[str, Any]] = []

    def __init__(self) -> None:
        self._bars: list[dict[str, Any]] = []
        self._config: dict[str, Any] = {}

    def _cfg(self, key: str, default: Any = None) -> Any:
        return self._config.get(key, default)

    @abstractmethod
    def signal_at(self, index: int, state: ExecutionState) -> Signal | None:
        """第 index 根 K 线的买卖决策；返回 None 表示不操作。"""

    def on_trade(self, trade: dict[str, Any]) -> None:
        """每笔成交后的钩子（默认空实现；多因子僵局保护覆盖）。"""

    def backtest(self, bars: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
        if len(bars) < 2:
            raise ValueError("历史数据不足")
        self._bars = bars
        self._config = config
        capital = float(config.get("capital", 100000))
        allocation = max(0.1, min(1.0, float(config.get("capitalAllocation", 1.0))))
        capital = capital * allocation
        fee_bps = float(config.get("feeBps", 3))
        security_type = config.get("securityType", "股票")
        exchange = config.get("exchange", "上交所")

        cash = capital
        shares = 0.0
        position_cost = 0.0
        lots: list[dict[str, Any]] = []  # {"shares", "available_day"}
        trades: list[dict[str, Any]] = []
        equity_curve = [cash]

        for i in range(1, len(bars)):
            close = float(bars[i]["close"])
            date = bars[i].get("date", "")
            state = ExecutionState(shares=shares, cash=cash, position_cost=position_cost)
            sig = self.signal_at(i, state)
            if sig and sig.side == "buy":
                amount = sig.amount if sig.amount is not None else cash
                buy_lots = floor(amount / close / 100) * 100
                value = buy_lots * close
                fee = transaction_fee("buy", value, fee_bps, security_type, exchange)
                while buy_lots and value + fee > cash:
                    buy_lots -= 100
                    value = buy_lots * close
                    fee = transaction_fee("buy", value, fee_bps, security_type, exchange)
                if buy_lots:
                    cash -= value + fee
                    shares += buy_lots
                    position_cost += value + fee
                    lots.append({"shares": buy_lots, "available_day": i + 1})
                    trade = {
                        "date": date,
                        "side": "buy",
                        "triggerPrice": None,
                        "price": round(close, 2),
                        "shares": buy_lots,
                        "fee": round(fee, 2),
                        "module": sig.module,
                    }
                    trades.append(trade)
                    self.on_trade(trade)
            elif sig and sig.side == "sell":
                sell_lots = int(sum(lt["shares"] for lt in lots if lt["available_day"] <= i))
                if sell_lots:
                    value = sell_lots * close
                    fee = transaction_fee("sell", value, fee_bps, security_type, exchange)
                    cash += value - fee
                    # FIFO 扣减可卖份额
                    remaining = sell_lots
                    kept: list[dict[str, Any]] = []
                    for lt in lots:
                        if remaining > 0 and lt["available_day"] <= i:
                            consume = min(lt["shares"], remaining)
                            lt["shares"] -= consume
                            remaining -= consume
                        if lt["shares"] > 0:
                            kept.append(lt)
                    lots = kept
                    shares -= sell_lots
                    # 持仓成本按剩余比例扣减（old_shares = shares + sell_lots）
                    if shares <= 1e-9:
                        shares = 0.0
                        position_cost = 0.0
                    else:
                        position_cost = position_cost * shares / (shares + sell_lots)
                    trade = {
                        "date": date,
                        "side": "sell",
                        "triggerPrice": None,
                        "price": round(close, 2),
                        "shares": sell_lots,
                        "fee": round(fee, 2),
                        "module": sig.module,
                    }
                    trades.append(trade)
                    self.on_trade(trade)
            equity_curve.append(cash + shares * close)

        normalised = [
            {"date": b.get("date", ""), "equity": round(eq / capital, 6)} for b, eq in zip(bars, equity_curve)
        ]
        benchmark = buy_and_hold_benchmark(bars, capital, fee_bps, security_type, exchange)
        metrics = _compute_metrics(bars, trades, equity_curve, capital, fee_bps, security_type, exchange)
        return {
            "trades": trades[-100:],
            "equityCurve": normalised,
            "benchmarkCurve": benchmark["curve"],
            "metrics": metrics,
            "assumptions": self.build_assumptions(),
        }

    def build_assumptions(self) -> str:
        return (
            f"{self.label}策略：按收盘价成交、100 股整数倍、T+1 可卖。"
            "费用包含佣金（最低 5 元）、印花税（卖出 0.05%）及过户费。"
            "结果仅用于研究，不代表未来收益。"
        )
