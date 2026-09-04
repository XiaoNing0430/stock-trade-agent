"""布林带反转策略：价格跌破下轨买入（超卖均值回归），上穿上轨卖出（超买回归中轨）。"""

from __future__ import annotations

from backend.indicators import bollinger
from backend.strategy_base import BaseStrategy, ExecutionState, Signal


class BollingerStrategy(BaseStrategy):
    id = "bollinger"
    label = "布林带反转"
    config_schema = [
        {"key": "period", "label": "均线周期", "type": "int", "default": 20, "min": 5, "max": 120},
        {"key": "numStd", "label": "标准差倍数", "type": "float", "default": 2.0, "min": 0.5, "max": 4.0},
    ]

    def signal_at(self, index: int, state: ExecutionState) -> Signal | None:
        period = int(self._cfg("period", 20))
        num_std = float(self._cfg("numStd", 2.0))
        bars = self._bars
        closes = [float(b["close"]) for b in bars]
        mid, upper, lower = bollinger(closes, period, num_std)
        if mid[index] is None:
            return None
        close = float(bars[index]["close"])
        date = bars[index].get("date", "")
        if state.shares == 0 and close < lower[index]:
            return Signal(date, "buy", close, reason=f"价格 {close:.2f} 跌破下轨 {lower[index]:.2f}，均值回归买入")
        if state.shares > 0 and close > upper[index]:
            return Signal(date, "sell", close, reason=f"价格 {close:.2f} 上穿上轨 {upper[index]:.2f}，均值回归卖出")
        return None

    def build_assumptions(self) -> str:
        period = int(self._cfg("period", 20))
        num_std = float(self._cfg("numStd", 2.0))
        return (
            f"布林带反转策略：价格跌破下轨（MA{period}−{num_std:.1f}σ）买入，上穿上轨卖出。"
            "本质为均值回归——价格偏离均线后回归中轨。"
            "按当日收盘价成交、100 股整数倍、T+1 可卖。"
            "费用包含佣金（最低 5 元）、印花税（卖出 0.05%）及过户费。"
            "结果仅用于研究，不代表未来收益。"
        )
