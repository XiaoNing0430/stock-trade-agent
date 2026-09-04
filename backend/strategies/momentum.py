"""动量策略：N 日涨跌幅超阈值买入，动量衰竭（跌破退出阈值）卖出。独立策略，需资金隔离。"""

from __future__ import annotations

from backend.indicators import momentum
from backend.strategy_base import BaseStrategy, ExecutionState, Signal


class MomentumStrategy(BaseStrategy):
    id = "momentum"
    label = "动量"
    config_schema = [
        {"key": "period", "label": "动量周期", "type": "int", "default": 20, "min": 3, "max": 120},
        {"key": "entryPct", "label": "入场阈值 %", "type": "float", "default": 5, "min": 0.5, "max": 50},
        {"key": "exitPct", "label": "退出阈值 %", "type": "float", "default": -3, "min": -50, "max": 0},
    ]

    def signal_at(self, index: int, state: ExecutionState) -> Signal | None:
        period = int(self._cfg("period", 20))
        entry_pct = float(self._cfg("entryPct", 5))
        exit_pct = float(self._cfg("exitPct", -3))
        bars = self._bars
        closes = [float(b["close"]) for b in bars]
        mom = momentum(closes, period)
        mom_val = mom[index]
        if mom_val is None:
            return None
        close = float(bars[index]["close"])
        date = bars[index].get("date", "")
        if state.shares == 0 and mom_val > entry_pct:
            return Signal(date, "buy", close, reason=f"{period} 日动量 {mom_val:.1f}% 超过入场阈值 {entry_pct}%")
        if state.shares > 0 and mom_val < exit_pct:
            return Signal(date, "sell", close, reason=f"{period} 日动量 {mom_val:.1f}% 跌破退出阈值 {exit_pct}%")
        return None

    def build_assumptions(self) -> str:
        period = int(self._cfg("period", 20))
        return (
            f"动量策略：{period} 日涨跌幅超过入场阈值时全仓买入，跌破退出阈值时卖出。"
            "独立资金管理：建议通过资金分配比例（capitalAllocation）与其他策略隔离。"
            "按当日收盘价成交、100 股整数倍、T+1 可卖。"
            "费用包含佣金（最低 5 元）、印花税（卖出 0.05%）及过户费。"
            "结果仅用于研究，不代表未来收益。"
        )
