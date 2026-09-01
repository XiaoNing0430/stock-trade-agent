"""定投策略：每 N 个交易日固定金额买入，止盈/止损线全仓卖出。"""

from backend.strategy_base import BaseStrategy, Signal


class DcaStrategy(BaseStrategy):
    id = "dca"
    label = "定投"
    config_schema = [
        {"key": "amountPerPeriod", "label": "每期投入", "type": "int", "default": 5000, "min": 1000, "step": 1000},
        {"key": "intervalDays", "label": "间隔交易日", "type": "int", "default": 5, "min": 1, "max": 60},
        {"key": "stopProfitPct", "label": "止盈 %", "type": "float", "default": 20, "min": 1, "max": 200},
        {"key": "stopLossPct", "label": "止损 %", "type": "float", "default": 15, "min": 1, "max": 100},
    ]

    def __init__(self) -> None:
        super().__init__()
        self._pending = 0.0  # 资金不足一手时滚入下一期

    def backtest(self, bars, config):
        self._pending = 0.0
        return super().backtest(bars, config)

    def signal_at(self, index, state):
        amount_per = float(self._cfg("amountPerPeriod", 5000))
        interval = int(self._cfg("intervalDays", 5))
        stop_profit = float(self._cfg("stopProfitPct", 20)) / 100
        stop_loss = float(self._cfg("stopLossPct", 15)) / 100
        if amount_per <= 0 or interval <= 0:
            raise ValueError("amountPerPeriod 和 intervalDays 必须大于 0")
        bars = self._bars
        close = float(bars[index]["close"])
        date = bars[index].get("date", "")
        if index % interval == 0:
            self._pending += amount_per  # 每期先入账
            invest = min(self._pending, state.cash)
            return Signal(date, "buy", close, amount=invest, reason="定期定额买入")
        if state.shares > 0 and state.position_cost > 0:
            return_pct = state.shares * close / state.position_cost - 1
            if return_pct >= stop_profit or return_pct <= -stop_loss:
                tag = "止盈" if return_pct >= stop_profit else "止损"
                return Signal(date, "sell", close, reason=f"{tag}线触发")
        return None

    def on_trade(self, trade) -> None:
        # 买入成交后：从 pending 中扣除实际花费（含费用）；未花完的部分滚入下一期
        # 卖出不重置 pending（与原版语义一致：pending 只代表未投入的定投资金）
        if trade["side"] == "buy":
            spent = trade["price"] * trade["shares"] + trade["fee"]
            self._pending = max(0.0, self._pending - spent)

    def build_assumptions(self) -> str:
        amount_per = float(self._cfg("amountPerPeriod", 5000))
        interval = int(self._cfg("intervalDays", 5))
        stop_profit = float(self._cfg("stopProfitPct", 20))
        stop_loss = float(self._cfg("stopLossPct", 15))
        return (
            f"定投（DCA）：每 {interval} 个交易日投入 {amount_per:.0f} 元，"
            f"止盈 {stop_profit:.0f}% / 止损 {stop_loss:.0f}%。"
            "资金不足一手时滚入下一期。按当日收盘价成交、100 股整数倍。"
            "费用包含佣金（最低 5 元）、印花税（卖出 0.05%）及过户费。"
            "结果仅用于研究，不代表未来收益。"
        )
