"""MACD 策略：DIF 上穿 DEA 买入，下穿卖出。"""

from backend.indicators import ema
from backend.strategy_base import BaseStrategy, Signal


class MacdStrategy(BaseStrategy):
    id = "macd"
    label = "MACD"
    config_schema = [
        {"key": "fastPeriod", "label": "快线周期", "type": "int", "default": 12, "min": 2, "max": 30},
        {"key": "slowPeriod", "label": "慢线周期", "type": "int", "default": 26, "min": 5, "max": 60},
        {"key": "signalPeriod", "label": "信号周期", "type": "int", "default": 9, "min": 2, "max": 30},
    ]

    def signal_at(self, index, state):
        fast = int(self._cfg("fastPeriod", 12))
        slow = int(self._cfg("slowPeriod", 26))
        signal = int(self._cfg("signalPeriod", 9))
        if fast >= slow:
            raise ValueError("fastPeriod 必须小于 slowPeriod")
        bars = self._bars
        closes = [float(b["close"]) for b in bars]
        ema_fast = ema(closes, fast)
        ema_slow = ema(closes, slow)
        dif = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
        dea = ema(dif, signal)
        warmup = slow + signal
        if index < warmup:
            return None
        prev_dif, prev_dea = dif[index - 1], dea[index - 1]
        cur_dif, cur_dea = dif[index], dea[index]
        close = float(bars[index]["close"])
        date = bars[index].get("date", "")
        if state.shares == 0 and prev_dif <= prev_dea and cur_dif > cur_dea:
            return Signal(date, "buy", close, reason="DIF 上穿 DEA（金叉）")
        if state.shares > 0 and prev_dif >= prev_dea and cur_dif < cur_dea:
            return Signal(date, "sell", close, reason="DIF 下穿 DEA（死叉）")
        return None

    def build_assumptions(self) -> str:
        fast = int(self._cfg("fastPeriod", 12))
        slow = int(self._cfg("slowPeriod", 26))
        signal = int(self._cfg("signalPeriod", 9))
        return (
            f"MACD 策略：DIF (EMA{fast}−EMA{slow}) 上穿 DEA({signal}) 时全仓买入，下穿时全仓卖出。"
            f"预热期 {slow + signal} 根 K 线内无交易信号。"
            "按当日收盘价成交、100 股整数倍、T+1 可卖。"
            "费用包含佣金（最低 5 元）、印花税（卖出 0.05%）及过户费。"
            "结果仅用于研究，不代表未来收益。"
        )
