"""唐奇安突破策略：上破通道买入（ADX 确认趋势），下破通道卖出（反向突破，不依赖 ADX）。"""

from __future__ import annotations

from backend.indicators import adx, donchian
from backend.strategy_base import BaseStrategy, ExecutionState, Signal


class DonchianStrategy(BaseStrategy):
    id = "donchian"
    label = "唐奇安突破"
    config_schema = [
        {"key": "period", "label": "通道周期", "type": "int", "default": 20, "min": 5, "max": 120},
        {"key": "adxPeriod", "label": "ADX 周期", "type": "int", "default": 14, "min": 5, "max": 60},
        {"key": "adxThreshold", "label": "ADX 阈值", "type": "int", "default": 25, "min": 10, "max": 50},
    ]

    def signal_at(self, index: int, state: ExecutionState) -> Signal | None:
        period = int(self._cfg("period", 20))
        adx_period = int(self._cfg("adxPeriod", 14))
        adx_threshold = float(self._cfg("adxThreshold", 25))
        bars = self._bars
        upper, lower = donchian(bars, period)
        if upper[index] is None:
            return None
        close = float(bars[index]["close"])
        date = bars[index].get("date", "")
        if state.shares == 0:
            adx_series = adx(bars, adx_period)
            adx_val = adx_series[index]
            if close > upper[index] and adx_val is not None and adx_val > adx_threshold:
                return Signal(
                    date, "buy", close, reason=f"价格 {close:.2f} 突破上轨 {upper[index]:.2f} 且 ADX={adx_val:.1f}"
                )
        elif close < lower[index]:
            return Signal(date, "sell", close, reason=f"价格 {close:.2f} 跌破下轨 {lower[index]:.2f}，趋势衰竭")
        return None

    def build_assumptions(self) -> str:
        period = int(self._cfg("period", 20))
        return (
            f"唐奇安突破策略：价格上破 {period} 日通道上轨且 ADX 高于阈值时买入（趋势确认），"
            f"跌破 {period} 日通道下轨时卖出（反向突破，不等待 ADX 回落，避免双重延迟）。"
            "按当日收盘价成交、100 股整数倍、T+1 可卖。"
            "费用包含佣金（最低 5 元）、印花税（卖出 0.05%）及过户费。"
            "结果仅用于研究，不代表未来收益。"
        )
