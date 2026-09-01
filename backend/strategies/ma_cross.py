"""双均线策略：快线上穿慢线买入，下穿卖出。"""

from backend.indicators import ma
from backend.strategy_base import BaseStrategy, Signal


class MaCrossStrategy(BaseStrategy):
    id = "ma_cross"
    label = "双均线"
    config_schema = [
        {"key": "fastPeriod", "label": "快线周期", "type": "int", "default": 5, "min": 2, "max": 60},
        {"key": "slowPeriod", "label": "慢线周期", "type": "int", "default": 20, "min": 3, "max": 120},
    ]

    def signal_at(self, index, state):
        fast = int(self._cfg("fastPeriod", 5))
        slow = int(self._cfg("slowPeriod", 20))
        if fast >= slow:
            raise ValueError("fastPeriod 必须小于 slowPeriod")
        bars = self._bars
        closes = [float(b["close"]) for b in bars]
        ma_fast = ma(closes, fast)
        ma_slow = ma(closes, slow)
        if index == 0:
            return None
        prev_f, prev_s = ma_fast[index - 1], ma_slow[index - 1]
        cur_f, cur_s = ma_fast[index], ma_slow[index]
        if None in (prev_f, prev_s, cur_f, cur_s):
            return None
        close = float(bars[index]["close"])
        date = bars[index].get("date", "")
        if state.shares == 0 and prev_f <= prev_s and cur_f > cur_s:
            return Signal(date, "buy", close, reason="快线上穿慢线（金叉）")
        if state.shares > 0 and prev_f >= prev_s and cur_f < cur_s:
            return Signal(date, "sell", close, reason="快线下穿慢线（死叉）")
        return None

    def build_assumptions(self) -> str:
        fast = int(self._cfg("fastPeriod", 5))
        slow = int(self._cfg("slowPeriod", 20))
        return (
            f"双均线策略：快线 MA({fast}) 上穿慢线 MA({slow}) 时全仓买入，下穿时全仓卖出。"
            "按当日收盘价成交、100 股整数倍、T+1 可卖。"
            "费用包含佣金（最低 5 元）、印花税（卖出 0.05%）及过户费。"
            "结果仅用于研究，不代表未来收益。"
        )
