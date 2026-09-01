"""多因子模型：ADX 市场状态过滤器 + 动态模块切换 + 僵局保护。

- ADX >= 阈值 → 趋势市 → 激活唐奇安突破模块
- ADX < 阈值  → 震荡市 → 激活布林带反转模块
- 模块连续亏损达到上限 → 冻结（资金保持现金，不移交）
- 入口用 ADX 确认趋势，出口用唐奇安反向突破（不依赖 ADX，避免双重延迟）
"""

from __future__ import annotations

from typing import Any

from backend.indicators import adx, bollinger, donchian
from backend.strategy_base import BaseStrategy, ExecutionState, Signal


class MultiFactorStrategy(BaseStrategy):
    id = "multi_factor"
    label = "多因子"
    config_schema = [
        {"key": "adxPeriod", "label": "ADX 周期", "type": "int", "default": 14, "min": 5, "max": 60},
        {"key": "adxThreshold", "label": "ADX 阈值", "type": "int", "default": 25, "min": 10, "max": 50},
        {"key": "maxConsecutiveLosses", "label": "最大连续亏损", "type": "int", "default": 10, "min": 2, "max": 50},
        {"key": "rangePeriod", "label": "震荡MA周期", "type": "int", "default": 20, "min": 5, "max": 120},
        {"key": "rangeStd", "label": "震荡标准差", "type": "float", "default": 2.0, "min": 0.5, "max": 4.0},
        {"key": "trendPeriod", "label": "趋势通道周期", "type": "int", "default": 20, "min": 5, "max": 120},
        {"key": "trendAdxPeriod", "label": "趋势ADX周期", "type": "int", "default": 14, "min": 5, "max": 60},
        {"key": "trendAdxThreshold", "label": "趋势ADX阈值", "type": "int", "default": 25, "min": 10, "max": 50},
    ]

    def __init__(self) -> None:
        super().__init__()
        self._module_stats: dict[str, dict[str, Any]] = {
            "range": {"trades": 0, "consecutiveLosses": 0, "frozen": False, "frozenPeriods": []},
            "trend": {"trades": 0, "consecutiveLosses": 0, "frozen": False, "frozenPeriods": []},
        }
        self._pending_buy_cost: dict[str, float] = {}

    def _module_for(self, index: int) -> str:
        adx_series = adx(self._bars, int(self._cfg("adxPeriod", 14)))
        val = adx_series[index]
        threshold = float(self._cfg("adxThreshold", 25))
        return "trend" if val is not None and val >= threshold else "range"

    def signal_at(self, index: int, state: ExecutionState) -> Signal | None:
        module = self._module_for(index)
        bars = self._bars
        close = float(bars[index]["close"])
        date = bars[index].get("date", "")
        sig: Signal | None = None

        if module == "range":
            period = int(self._cfg("rangePeriod", 20))
            num_std = float(self._cfg("rangeStd", 2.0))
            mid, upper, lower = bollinger([float(b["close"]) for b in bars], period, num_std)
            if mid[index] is not None:
                if state.shares == 0 and close < lower[index]:
                    sig = Signal(
                        date, "buy", close, reason=f"震荡市：跌破下轨 {lower[index]:.2f} 均值回归买入", module="range"
                    )
                elif state.shares > 0 and close > upper[index]:
                    sig = Signal(
                        date, "sell", close, reason=f"震荡市：上穿上轨 {upper[index]:.2f} 卖出", module="range"
                    )
        else:
            period = int(self._cfg("trendPeriod", 20))
            adx_period = int(self._cfg("trendAdxPeriod", 14))
            adx_threshold = float(self._cfg("trendAdxThreshold", 25))
            upper, lower = donchian(bars, period)
            if upper[index] is not None:
                if state.shares == 0:
                    adx_val = adx(bars, adx_period)[index]
                    if close > upper[index] and adx_val is not None and adx_val > adx_threshold:
                        sig = Signal(
                            date,
                            "buy",
                            close,
                            reason=f"趋势市：突破上轨 {upper[index]:.2f} 且 ADX={adx_val:.1f}",
                            module="trend",
                        )
                elif close < lower[index]:
                    sig = Signal(
                        date, "sell", close, reason=f"趋势市：跌破下轨 {lower[index]:.2f} 趋势衰竭", module="trend"
                    )

        if sig is None or sig.module is None:
            return None
        return self._apply_freeze(sig)

    def _apply_freeze(self, sig: Signal) -> Signal | None:
        """冻结检查：模块冻结时压制信号并计数（供子类复用，保证父类抑制逻辑生效）。"""
        module = sig.module
        if module is None:
            return sig
        stats = self._module_stats[module]
        if stats["frozen"]:
            stats["frozenPeriods"][-1]["suppressedSignals"] = stats["frozenPeriods"][-1].get("suppressedSignals", 0) + 1
            return None  # 冻结中：信号被压制，资金保持现金
        return sig

    def on_trade(self, trade: dict[str, Any]) -> None:
        module = trade.get("module")
        if not module:
            return
        stats = self._module_stats[module]
        stats["trades"] += 1
        if trade["side"] == "buy":
            self._pending_buy_cost[module] = trade["price"] * trade["shares"] + trade["fee"]
        elif trade["side"] == "sell":
            proceeds = trade["price"] * trade["shares"] - trade["fee"]
            cost = self._pending_buy_cost.pop(module, proceeds)
            pnl = proceeds - cost
            if pnl < 0:
                stats["consecutiveLosses"] += 1
            else:
                stats["consecutiveLosses"] = 0
            max_losses = int(self._cfg("maxConsecutiveLosses", 10))
            if stats["consecutiveLosses"] >= max_losses:
                stats["frozen"] = True
                stats["frozenPeriods"].append({"start": trade["date"], "end": None, "suppressedSignals": 0})

    def backtest(self, bars: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
        self._module_stats = {
            "range": {"trades": 0, "consecutiveLosses": 0, "frozen": False, "frozenPeriods": []},
            "trend": {"trades": 0, "consecutiveLosses": 0, "frozen": False, "frozenPeriods": []},
        }
        self._pending_buy_cost = {}
        result = super().backtest(bars, config)
        # 冻结期信息（end 在冻结解除时设置，目前为永久冻结）
        result["moduleUsage"] = self._module_stats
        result["theoreticalIfUnfrozen"] = [
            {
                "module": m,
                "frozenPeriods": stats["frozenPeriods"],
            }
            for m, stats in self._module_stats.items()
            if stats["frozenPeriods"]
        ]
        return result

    def build_assumptions(self) -> str:
        adx_threshold = float(self._cfg("adxThreshold", 25))
        max_losses = int(self._cfg("maxConsecutiveLosses", 10))
        return (
            f"多因子模型：ADX 市场状态过滤器（≥{adx_threshold:.0f} 为趋势市，激活唐奇安突破；"
            f"否则为震荡市，激活布林带反转）。入口用 ADX 确认趋势，出口用通道反向突破（不依赖 ADX，避免双重延迟）。"
            f"模块连续亏损达 {max_losses} 笔后冻结，资金保持现金；盈利后计数器复位。"
            f"ADX 为滞后指标，市场状态切换存在延迟，此为已知局限。"
            "按当日收盘价成交、100 股整数倍、T+1 可卖。"
            "费用包含佣金（最低 5 元）、印花税（卖出 0.05%）及过户费。"
            "结果仅用于研究，不代表未来收益。"
        )
