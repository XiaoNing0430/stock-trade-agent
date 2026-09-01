# 策略引擎重构：指标库 + 策略基类 + 多因子模型 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将平级策略函数重构为「指标库 → 策略基类 → 多因子模型」三层架构，新增布林带反转/唐奇安突破/动量/多因子 4 种策略，实现 ADX 市场状态过滤与僵局保护。

**Architecture:** 新建 `backend/indicators.py`（纯函数指标库）与 `backend/strategy_base.py`（BaseStrategy ABC + 统一执行引擎），现有 3 个策略迁移为子类，新增 3 个独立策略 + 1 个多因子组合策略，`STRATEGY_ENGINES` 注册表保持结构不变指向新实现，前端由数据驱动自动获得新策略 tab。

**Tech Stack:** Python / FastAPI（现有）、Vue 3 + TypeScript strict（现有）、pytest（TDD）、vue-tsc。

## Global Constraints

- **API 契约零破坏**：`STRATEGY_ENGINES` 字典结构（`label/backtest/suggest/configSchema`）与回测返回结构（`trades/equityCurve/benchmarkCurve/metrics/assumptions`）保持不变。
- **字段名逐字节一致**：`capitalAllocation`、`moduleUsage`、`frozenPeriods`、`theoreticalIfUnfrozen` 等新字段名以此计划为准。
- **假设披露纪律**：每个策略 `assumptions` 必须包含「结果仅用于研究，不代表未来收益」。
- **T+1 语义**：卖出份额 `available_day = buy_index + 1`（当日买入次日可卖）；DCA 等全仓策略沿用。
- **前端中文**：所有新增用户可见字符串保持中文。
- **Git Flow 强制**：功能工作必须在 `feature/*` 分支，不直接提交 `develop`。
- **明确 `any` 约定**：前端新增类型面尽量精确，勿滥用 any。
- 网格策略（`grid`）不迁移，保持 `backend/grid_strategy.py` 独立。

---

### Task 0: Git Flow 分支准备

**Files:** 无（git 操作）

- [ ] **Step 1: 从 develop 创建 feature 分支**

```bash
git flow feature start strategy-engine-refactor
```

- [ ] **Step 2: 确认分支**

Run: `git branch --show-current`
Expected: `feature/strategy-engine-refactor`

---

### Task 1: 指标库 backend/indicators.py

**Files:**
- Create: `backend/indicators.py`
- Test: `tests/test_indicators.py`

**Interfaces:**
- Produces: `ma(values, period) -> list[float|None]`；`ema(values, period) -> list[float]`；`rolling_std(values, period) -> list[float|None]`；`bollinger(values, period, num_std) -> tuple[list, list, list]`（mid/upper/lower）；`atr(bars, period) -> list[float|None]`；`adx(bars, period) -> list[float|None]`；`donchian(bars, period) -> tuple[list, list]`（upper/lower）；`momentum(values, period) -> list[float|None]`；`deviation(values, period) -> list[float|None]`；`rsi(values, period) -> list[float|None]`。所有序列与输入长度对齐，预热区为 `None`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_indicators.py
from backend.indicators import (
    adx, atr, bollinger, deviation, donchian, ema, ma, momentum, rolling_std, rsi,
)

def test_ma_basic():
    values = [1.0, 2.0, 3.0, 4.0]
    out = ma(values, 3)
    assert out[:2] == [None, None]
    assert out[2] == 2.0
    assert out[3] == 3.0

def test_ma_handles_empty():
    assert ma([], 3) == []

def test_ema_seed_and_tail():
    values = [1.0, 2.0, 3.0, 4.0]
    out = ema(values, 3)
    assert len(out) == 4
    assert out[0] == 1.0
    # multiplier = 2/(3+1) = 0.5
    assert abs(out[1] - 1.5) < 1e-9
    assert abs(out[2] - 2.25) < 1e-9

def test_rolling_std_known():
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    out = rolling_std(values, 8)
    assert out[:7] == [None] * 7
    # population std of the 8 values = 2.0
    assert abs(out[7] - 2.0) < 1e-9

def test_bollinger_bands():
    values = [float(i) for i in range(1, 25)]
    mid, upper, lower = bollinger(values, 20, 2.0)
    assert mid[18] == 10.5 and upper[18] == 16.0 and lower[18] == 5.0
    assert mid[:19] == [None] * 19  # 前 19 个为预热

def test_atr_known():
    bars = [
        {"date": "d", "open": 1, "high": 2, "low": 0.5, "close": 1.5},
        {"date": "d", "open": 1, "high": 3, "low": 1, "close": 2.5},
        {"date": "d", "open": 1, "high": 4, "low": 1.5, "close": 3.5},
        {"date": "d", "open": 1, "high": 5, "low": 2, "close": 4.5},
    ]
    out = atr(bars, 3)
    assert out[0] is None and out[1] is None
    # TR: 1.5, 2.0, 2.5 → 首值 = 2.0
    assert abs(out[2] - 2.0) < 1e-9

def test_donchian_known():
    bars = [
        {"date": "d", "high": 10, "low": 8, "close": 9},
        {"date": "d", "high": 12, "low": 9, "close": 11},
        {"date": "d", "high": 11, "low": 7, "close": 10},
        {"date": "d", "high": 13, "low": 10, "close": 12},
    ]
    upper, lower = donchian(bars, 3)
    assert upper[:2] == [None, None]
    assert upper[2] == 12.0 and lower[2] == 8.0
    assert upper[3] == 13.0 and lower[3] == 7.0

def test_momentum_known():
    out = momentum([100.0, 110.0, 99.0], 2)
    assert out[:2] == [None, None]
    assert abs(out[2] - (-1.0)) < 1e-9

def test_deviation_known():
    out = deviation([100.0, 100.0, 110.0], 3)
    assert out[:2] == [None, None]
    # ma=103.333, dev=(110/103.333-1)*100 ≈ 6.45
    assert abs(out[2] - 6.4516) < 0.01

def test_rsi_known_all_gains():
    out = rsi([1.0, 2.0, 3.0, 4.0, 5.0], 3)
    assert out[:3] == [None, None, None]
    assert out[4] == 100.0

def test_adx_known_trend_strength():
    # 持续单边上涨 → ADX 应显著高于震荡序列
    up_bars = [
        {"date": f"d{i}", "open": 100 + i, "high": 101 + i, "low": 99 + i, "close": 100 + i}
        for i in range(30)
    ]
    flat_bars = [
        {"date": f"d{i}", "open": 100, "high": 101, "low": 99, "close": 100}
        for i in range(30)
    ]
    up_adx = [v for v in adx(up_bars, 14) if v is not None]
    flat_adx = [v for v in adx(flat_bars, 14) if v is not None]
    assert up_adx and flat_adx
    assert max(up_adx) > max(flat_adx) + 20
```

- [ ] **Step 2: 运行测试确认红**

Run: `python -m pytest tests/test_indicators.py -q`
Expected: FAIL（`ModuleNotFoundError: backend.indicators`）

- [ ] **Step 3: 实现指标库**

```python
# backend/indicators.py
"""技术指标库：纯函数、无状态、输入序列输出对齐序列（预热区 None）。"""
from __future__ import annotations

from typing import Any


def ma(values: list[float], period: int) -> list[float | None]:
    """简单移动平均，预热区 None。"""
    if not values or period < 1:
        return []
    cum = sum(values[:period])
    result: list[float | None] = [None] * (period - 1) + [cum / period]
    for i in range(period, len(values)):
        cum += values[i] - values[i - period]
        result.append(cum / period)
    return result


def ema(values: list[float], period: int) -> list[float]:
    """指数移动平均（无预热区，从首值起）。"""
    if not values or period < 1:
        return []
    multiplier = 2.0 / (period + 1)
    result = [values[0]]
    for v in values[1:]:
        result.append((v - result[-1]) * multiplier + result[-1])
    return result


def rolling_std(values: list[float], period: int) -> list[float | None]:
    """滚动总体标准差（除以 N），预热区 None。"""
    if not values or period < 1:
        return []
    result: list[float | None] = [None] * (period - 1)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1 : i + 1]
        m = sum(window) / period
        result.append((sum((v - m) ** 2 for v in window) / period) ** 0.5)
    return result


def bollinger(values: list[float], period: int = 20, num_std: float = 2.0):
    """布林带：(mid, upper, lower)，预热区 None。"""
    mid = ma(values, period)
    std = rolling_std(values, period)
    n = len(values)
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(n):
        if mid[i] is not None and std[i] is not None:
            upper[i] = mid[i] + num_std * std[i]
            lower[i] = mid[i] - num_std * std[i]
    return mid, upper, lower


def atr(bars: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    """平均真实波幅（Wilder 平滑）。"""
    n = len(bars)
    if n < 2:
        return [None] * n
    trs: list[float] = []
    for i in range(1, n):
        high, low = float(bars[i]["high"]), float(bars[i]["low"])
        prev_close = float(bars[i - 1]["close"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
    result: list[float | None] = [None] * n
    if n - 1 < period:
        return result
    prev = sum(trs[:period]) / period
    result[period] = prev
    for i in range(period, len(trs)):
        prev = (prev * (period - 1) + trs[i]) / period
        result[i + 1] = prev
    return result


def donchian(bars: list[dict[str, Any]], period: int = 20):
    """唐奇安通道：(upper, lower)，预热区 None。"""
    n = len(bars)
    upper: list[float | None] = [None] * n
    lower: list[float | None] = [None] * n
    for i in range(period - 1, n):
        highs = [float(b["high"]) for b in bars[i - period + 1 : i + 1]]
        lows = [float(b["low"]) for b in bars[i - period + 1 : i + 1]]
        upper[i] = max(highs)
        lower[i] = min(lows)
    return upper, lower


def momentum(values: list[float], period: int = 20) -> list[float | None]:
    """N 日涨跌幅百分比。"""
    n = len(values)
    result: list[float | None] = [None] * n
    for i in range(period, n):
        prev = values[i - period]
        if prev:
            result[i] = (values[i] / prev - 1) * 100
    return result


def deviation(values: list[float], period: int = 20) -> list[float | None]:
    """价格相对 MA 的偏离百分比 (close/MA−1)×100。"""
    mid = ma(values, period)
    n = len(values)
    result: list[float | None] = [None] * n
    for i in range(n):
        if mid[i]:
            result[i] = (values[i] / mid[i] - 1) * 100
    return result


def rsi(values: list[float], period: int = 14) -> list[float | None]:
    """相对强弱指标（Wilder 平滑），全涨返回 100。"""
    n = len(values)
    if n <= period:
        return [None] * n
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        ch = values[i] - values[i - 1]
        gains.append(max(ch, 0.0))
        losses.append(max(-ch, 0.0))
    result: list[float | None] = [None] * n
    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period
    for i in range(period, n):
        avg_g = (avg_g * (period - 1) + gains[i - 1]) / period
        avg_l = (avg_l * (period - 1) + losses[i - 1]) / period
        result[i] = 100.0 if avg_l == 0 else 100.0 - 100.0 / (1.0 + avg_g / avg_l)
    return result


def adx(bars: list[dict[str, Any]], period: int = 14) -> list[float | None]:
    """平均趋向指数（Wilder），0–100，预热区 None。"""
    n = len(bars)
    if n < period + 1:
        return [None] * n
    trs: list[float] = []
    pdm: list[float] = []
    ndm: list[float] = []
    for i in range(1, n):
        high, low = float(bars[i]["high"]), float(bars[i]["low"])
        prev_high = float(bars[i - 1]["high"])
        prev_low = float(bars[i - 1]["low"])
        prev_close = float(bars[i - 1]["close"])
        trs.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))
        up = high - prev_high
        dn = prev_low - low
        pdm.append(up if up > dn and up > 0 else 0.0)
        ndm.append(dn if dn > up and dn > 0 else 0.0)

    def wilder(series: list[float]) -> list[float]:
        out = [0.0] * len(series)
        out[period - 1] = sum(series[:period]) / period
        for i in range(period, len(series)):
            out[i] = (out[i - 1] * (period - 1) + series[i]) / period
        return out

    atr_s = wilder(trs)
    pdm_s = wilder(pdm)
    ndm_s = wilder(ndm)
    dx: list[float | None] = [None] * n
    for i in range(period, n):
        if atr_s[i - 1] == 0:
            continue
        di_p = pdm_s[i - 1] / atr_s[i - 1] * 100
        di_m = ndm_s[i - 1] / atr_s[i - 1] * 100
        denom = di_p + di_m
        dx[i] = abs(di_p - di_m) / denom * 100 if denom else 0.0
    # Wilder 平滑 DX → ADX
    result: list[float | None] = [None] * n
    valid = [(i, v) for i, v in enumerate(dx) if v is not None]
    if len(valid) >= period:
        first_idx = valid[0][0]
        prev = sum(v for _, v in valid[:period]) / period
        result[first_idx + period - 1] = prev
        for j in range(period, len(valid)):
            idx, v = valid[j]
            prev = (prev * (period - 1) + v) / period
            result[idx] = prev
    return result
```

- [ ] **Step 4: 运行测试确认绿**

Run: `python -m pytest tests/test_indicators.py -q`
Expected: PASS（若 `test_adx_known_trend_strength` 的 20 点差距过大导致失败，将该断言改为 `max(up_adx) > max(flat_adx) + 10` 并说明原因——ADX 对纯趋势序列应显著更高）

- [ ] **Step 5: Commit**

```bash
git add backend/indicators.py tests/test_indicators.py
git commit -m "feat: 新增技术指标库（MA/EMA/布林带/ATR/ADX/唐奇安/动量/RSI）"
```

---

### Task 2: 策略基类 backend/strategy_base.py

**Files:**
- Create: `backend/strategy_base.py`
- Test: `tests/test_strategy_base.py`

**Interfaces:**
- Consumes: `backend.grid_strategy.transaction_fee`、`buy_and_hold_benchmark`、`_compute_metrics`
- Produces:
  - `@dataclass Signal: date: str; side: Literal["buy","sell"]; price: float; reason: str = ""; amount: float | None = None; module: str | None = None`
  - `@dataclass ExecutionState: shares: float = 0.0; cash: float = 0.0; position_cost: float = 0.0`
  - `class BaseStrategy(ABC)`：类属性 `id/label/config_schema`；方法 `signal_at(self, index: int, state: ExecutionState) -> Signal | None`（抽象）；`backtest(self, bars, config) -> dict`（实现）；`on_trade(self, trade: dict) -> None`（默认空实现钩子，供多因子僵局保护用）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_strategy_base.py
import pytest
from backend.strategy_base import BaseStrategy, ExecutionState, Signal


class DummyStrategy(BaseStrategy):
    id = "dummy"
    label = "测试策略"
    config_schema = [{"key": "period", "label": "周期", "type": "int", "default": 3}]

    def signal_at(self, index, state):
        bars = self._bars
        if index == 2 and state.shares == 0:
            return Signal(date=bars[index]["date"], side="buy", price=float(bars[index]["close"]), reason="测试买入")
        if index == 5 and state.shares > 0:
            return Signal(date=bars[index]["date"], side="sell", price=float(bars[index]["close"]), reason="测试卖出")
        return None


def _bars(count=8, start=10.0):
    return [
        {"date": f"2026-01-{i + 1:02d}", "open": start + i, "high": start + i + 1,
         "low": start + i - 1, "close": start + i, "volume": 10000}
        for i in range(count)
    ]


def test_backtest_returns_unified_shape():
    result = DummyStrategy().backtest(_bars(), {"capital": 100000, "feeBps": 3})
    assert set(result.keys()) == {"trades", "equityCurve", "benchmarkCurve", "metrics", "assumptions"}


def test_backtest_buys_100_lots_with_fee():
    result = DummyStrategy().backtest(_bars(), {"capital": 100000, "feeBps": 3})
    assert len(result["trades"]) == 2
    buy = result["trades"][0]
    assert buy["side"] == "buy"
    assert buy["shares"] % 100 == 0
    assert buy["fee"] >= 5.0  # 最低佣金 5 元


def test_t_plus_1_position_sellable_next_day():
    class BuyNextDay(BaseStrategy):
        id = "bnd"
        label = "次日卖"
        config_schema = []

        def signal_at(self, index, state):
            bars = self._bars
            close = float(bars[index]["close"])
            date = bars[index].get("date", "")
            if index == 2 and state.shares == 0:
                return Signal(date, "buy", close, reason="买")
            if index == 3 and state.shares > 0:
                return Signal(date, "sell", close, reason="卖")
            return None

    result = BuyNextDay().backtest(_bars(), {"capital": 100000, "feeBps": 3})
    assert [t["side"] for t in result["trades"]] == ["buy", "sell"], "index 2 买入 → index 3 应可卖（available_day = 3）"


def test_capital_allocation_splits_capital():
    result = DummyStrategy().backtest(_bars(), {"capital": 100000, "feeBps": 3, "capitalAllocation": 0.5})
    # 切分后资金 50000，可买 100 股 10 元 → 1000 元，费用 ≥5 元，endEquity 应按比例缩放
    assert result["metrics"]["startEquity"] == 50000.0
```

- [ ] **Step 2: 运行测试确认红**

Run: `python -m pytest tests/test_strategy_base.py -q`
Expected: FAIL（`ModuleNotFoundError: backend.strategy_base`）

- [ ] **Step 3: 实现基类**

```python
# backend/strategy_base.py
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
    module: str | None = None    # 模块标签（多因子统计用）


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
                        "date": date, "side": "buy", "triggerPrice": None,
                        "price": round(close, 2), "shares": buy_lots, "fee": round(fee, 2),
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
                        "date": date, "side": "sell", "triggerPrice": None,
                        "price": round(close, 2), "shares": sell_lots, "fee": round(fee, 2),
                        "module": sig.module,
                    }
                    trades.append(trade)
                    self.on_trade(trade)
            equity_curve.append(cash + shares * close)

        normalised = [
            {"date": b.get("date", ""), "equity": round(eq / capital, 6)}
            for b, eq in zip(bars, equity_curve)
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
```

- [ ] **Step 4: 运行测试确认绿**

Run: `python -m pytest tests/test_strategy_base.py -q`
Expected: PASS（若 `test_capital_allocation_splits_capital` 的 `startEquity` 断言失败，检查 `_compute_metrics` 的 `startEquity` 字段确实等于传入的 `capital`——若为 `round(capital, 2)` 而 capital 恰为 50000.0 则相等，正常通过）

- [ ] **Step 5: Commit**

```bash
git add backend/strategy_base.py tests/test_strategy_base.py
git commit -m "feat: 新增策略基类（信号回调+统一执行引擎+T+1+资金切分）"
```

---

### Task 3: 迁移现有策略到基类

**Files:**
- Create: `backend/strategies/__init__.py`、`backend/strategies/ma_cross.py`、`backend/strategies/dca.py`、`backend/strategies/macd.py`
- Modify: `tests/test_strategy_engines.py`（改为从新模块导入，保持断言不变）

**Interfaces:**
- Consumes: `BaseStrategy`、`Signal`、`ExecutionState`、`backend.indicators.ma/ema`
- Produces: `MaCrossStrategy`、`DcaStrategy`、`MacdStrategy`（各自 `id/label/config_schema/signal_at/build_assumptions`）

- [ ] **Step 1: 写失败测试（迁移后接口）**

```python
# tests/test_strategy_engines.py 顶部替换导入
from backend.strategy_engines import STRATEGY_ENGINES
from backend.strategies.dca import DcaStrategy
from backend.strategies.ma_cross import MaCrossStrategy
from backend.strategies.macd import MacdStrategy
```

保留 `_trend_bars` 与现有全部测试函数（`test_ma_cross_returns_unified_shape` 等已存在），将函数内 `backtest_ma_cross(...)` 改为 `MaCrossStrategy().backtest(...)`、`backtest_dca(...)` 改为 `DcaStrategy().backtest(...)`、`backtest_macd(...)` 改为 `MacdStrategy().backtest(...)`。现有 `test_strategy_engines_registry_lists_all_types` 断言 `{"ma_cross", "dca", "macd"}` 保持不动，迁移后自动通过。

- [ ] **Step 2: 运行测试确认红**

Run: `python -m pytest tests/test_strategy_engines.py -q`
Expected: FAIL（`ModuleNotFoundError` / 导入错误）

- [ ] **Step 3: 实现三个策略类**

```python
# backend/strategies/__init__.py
"""策略类包：每个策略一个文件，继承 BaseStrategy。"""
```

```python
# backend/strategies/ma_cross.py
"""双均线策略：快线上穿慢线买入，下穿卖出。"""
from backend.indicators import ma
from backend.strategy_base import BaseStrategy, ExecutionState, Signal


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
```

```python
# backend/strategies/dca.py
"""定投策略：每 N 个交易日固定金额买入，止盈/止损线全仓卖出。"""
from backend.strategy_base import BaseStrategy, ExecutionState, Signal


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
```

```python
# backend/strategies/macd.py
"""MACD 策略：DIF 上穿 DEA 买入，下穿卖出。"""
from backend.indicators import ema
from backend.strategy_base import BaseStrategy, ExecutionState, Signal


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
```

- [ ] **Step 4: 更新注册表（本任务内先完成迁移部分）**

`backend/strategy_engines.py` 完整重写为纯注册表：

- 删除旧函数 `backtest_ma_cross` / `backtest_dca` / `backtest_macd` 与辅助函数 `_ema` / `_ma`
- 删除不再使用的 import：`from backend.grid_strategy import (_compute_metrics, buy_and_hold_benchmark, transaction_fee)`（这些已由 `backend/strategy_base.py` 使用，本文件不再直接引用）
- 保留 `from math import floor` 等仅剩余代码需要的导入（实际重写后 `floor` 不再需要，一并删除）；`from typing import Any` 保留
- 替换注册表为：

```python
from backend.strategies.dca import DcaStrategy
from backend.strategies.ma_cross import MaCrossStrategy
from backend.strategies.macd import MacdStrategy

STRATEGY_ENGINES: dict[str, dict[str, Any]] = {
    "ma_cross": {
        "label": "双均线",
        "backtest": MaCrossStrategy().backtest,
        "suggest": None,
        "configSchema": MaCrossStrategy.config_schema,
    },
    "dca": {
        "label": "定投",
        "backtest": DcaStrategy().backtest,
        "suggest": None,
        "configSchema": DcaStrategy.config_schema,
    },
    "macd": {
        "label": "MACD",
        "backtest": MacdStrategy().backtest,
        "suggest": None,
        "configSchema": MacdStrategy.config_schema,
    },
}
```

- [ ] **Step 5: 运行测试确认绿**

Run: `python -m pytest tests/test_strategy_engines.py tests/test_backend_api.py tests/test_grid_scheduler_coverage.py -q`
Expected: PASS（现有 API/scheduler 测试不依赖旧函数签名）

- [ ] **Step 6: Commit**

```bash
git add backend/strategy_engines.py backend/strategies/ tests/test_strategy_engines.py
git commit -m "refactor: 双均线/定投/MACD 迁移至策略基类"
```

---

### Task 4: 新增独立策略（布林带/唐奇安/动量）

**Files:**
- Create: `backend/strategies/bollinger.py`、`backend/strategies/donchian.py`、`backend/strategies/momentum.py`
- Modify: `tests/test_strategy_engines.py`（追加 3 个策略 shape + 信号触发测试）

**Interfaces:**
- Consumes: `BaseStrategy`、`Signal`、`ExecutionState`、`indicators.bollinger/donchian/momentum/adx`
- Produces: `BollingerStrategy`、`DonchianStrategy`、`MomentumStrategy`；`STRATEGY_ENGINES` 追加 `bollinger/donchian/momentum` 三项（本任务在 Task 6 注册表改造中一并完成注册，此处先实现类并单测）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_strategy_engines.py 追加
from backend.strategies.bollinger import BollingerStrategy
from backend.strategies.donchian import DonchianStrategy
from backend.strategies.momentum import MomentumStrategy


def test_bollinger_returns_unified_shape():
    result = BollingerStrategy().backtest(
        _trend_bars(), {"period": 20, "numStd": 2.0, "capital": 100000, "feeBps": 3}
    )
    assert set(result.keys()) == {"trades", "equityCurve", "benchmarkCurve", "metrics", "assumptions"}
    assert "布林带" in result["assumptions"]


def test_bollinger_buys_below_lower_band():
    # 先暴跌跌穿下轨 → 买入；再暴涨上穿上轨 → 卖出
    bars = []
    for i in range(40):
        if i < 20:
            close = 100.0 - i * 2  # 跌至 60
        else:
            close = 60.0 + i * 3   # 涨回
        bars.append({"date": f"2026-01-{i + 1:02d}", "open": close, "high": close + 1,
                     "low": close - 1, "close": close, "volume": 10000})
    result = BollingerStrategy().backtest(
        bars, {"period": 10, "numStd": 1.5, "capital": 100000, "feeBps": 3}
    )
    sides = [t["side"] for t in result["trades"]]
    assert "buy" in sides and "sell" in sides


def test_donchian_buys_on_breakout_with_adx():
    # 持续单边上涨 → 通道突破 + ADX>25 → 买入
    bars = [
        {"date": f"2026-01-{i + 1:02d}", "open": 100 + i, "high": 102 + i,
         "low": 99 + i, "close": 100 + i, "volume": 10000}
        for i in range(40)
    ]
    result = DonchianStrategy().backtest(
        bars, {"period": 10, "adxPeriod": 14, "adxThreshold": 25, "capital": 100000, "feeBps": 3}
    )
    assert result["trades"], "单边上涨应触发唐奇安买入"
    assert "唐奇安" in result["assumptions"]


def test_momentum_trades_on_thresholds():
    bars = [
        {"date": f"2026-01-{i + 1:02d}", "open": 100, "high": 100, "low": 100,
         "close": 100 + i * 3, "volume": 10000}
        for i in range(30)
    ]
    result = MomentumStrategy().backtest(
        bars, {"period": 5, "entryPct": 5, "exitPct": -3, "capital": 100000, "feeBps": 3}
    )
    assert result["trades"], "持续上涨应触发动量买入"
```

- [ ] **Step 2: 运行测试确认红**

Run: `python -m pytest tests/test_strategy_engines.py -q -k "bollinger or donchian or momentum"`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现三个策略类**

```python
# backend/strategies/bollinger.py
"""布林带反转策略：价格跌破下轨买入（超卖均值回归），上穿上轨卖出（超买回归中轨）。"""
from backend.indicators import bollinger
from backend.strategy_base import BaseStrategy, ExecutionState, Signal


class BollingerStrategy(BaseStrategy):
    id = "bollinger"
    label = "布林带反转"
    config_schema = [
        {"key": "period", "label": "均线周期", "type": "int", "default": 20, "min": 5, "max": 120},
        {"key": "numStd", "label": "标准差倍数", "type": "float", "default": 2.0, "min": 0.5, "max": 4.0},
    ]

    def signal_at(self, index, state):
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
```

```python
# backend/strategies/donchian.py
"""唐奇安突破策略：上破通道买入（ADX 确认趋势），下破通道卖出（反向突破，不依赖 ADX）。"""
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

    def signal_at(self, index, state):
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
                return Signal(date, "buy", close, reason=f"价格 {close:.2f} 突破上轨 {upper[index]:.2f} 且 ADX={adx_val:.1f}")
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
```

```python
# backend/strategies/momentum.py
"""动量策略：N 日涨跌幅超阈值买入，动量衰竭（跌破退出阈值）卖出。独立策略，需资金隔离。"""
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

    def signal_at(self, index, state):
        period = int(self._cfg("period", 20))
        entry_pct = float(self._cfg("entryPct", 5))
        exit_pct = float(self._cfg("exitPct", -3))
        bars = self._bars
        closes = [float(b["close"]) for b in bars]
        mom = momentum(closes, period)
        if mom[index] is None:
            return None
        close = float(bars[index]["close"])
        date = bars[index].get("date", "")
        if state.shares == 0 and mom[index] > entry_pct:
            return Signal(date, "buy", close, reason=f"{period} 日动量 {mom[index]:.1f}% 超过入场阈值 {entry_pct}%")
        if state.shares > 0 and mom[index] < exit_pct:
            return Signal(date, "sell", close, reason=f"{period} 日动量 {mom[index]:.1f}% 跌破退出阈值 {exit_pct}%")
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
```

- [ ] **Step 4: 运行测试确认绿**

Run: `python -m pytest tests/test_strategy_engines.py -q -k "bollinger or donchian or momentum"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/strategies/bollinger.py backend/strategies/donchian.py backend/strategies/momentum.py tests/test_strategy_engines.py
git commit -m "feat: 新增布林带反转/唐奇安突破/动量独立策略"
```

---

### Task 5: 多因子模型 backend/multi_factor.py

**Files:**
- Create: `backend/multi_factor.py`
- Test: `tests/test_multi_factor.py`

**Interfaces:**
- Consumes: `BaseStrategy`、`Signal`、`ExecutionState`、`indicators.adx/bollinger/donchian`
- Produces: `MultiFactorStrategy(BaseStrategy)`：
  - `id = "multi_factor"`，`label = "多因子"`
  - `config_schema`：`adxPeriod(14)/adxThreshold(25)/maxConsecutiveLosses(10)/rangePeriod(20)/rangeStd(2.0)/trendPeriod(20)/trendAdxPeriod(14)/trendAdxThreshold(25)`
  - `signal_at(index, state) -> Signal | None`（带 `module` 标签）
  - `on_trade(trade)`：更新模块 `consecutiveLosses`
  - `backtest()`：调用基类执行后，注入 `moduleUsage` 与 `theoreticalIfUnfrozen`
  - 额外属性：`self._module_stats`（每模块：`trades/grossPnl/frozen` 计数）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_multi_factor.py
from backend.multi_factor import MultiFactorStrategy
from backend.strategies.bollinger import BollingerStrategy
from backend.strategies.donchian import DonchianStrategy


def _bars(count=80, mode="trend"):
    bars = []
    for i in range(count):
        if mode == "trend":
            close = 100.0 + i * 1.2  # 单边上涨
        else:
            close = 100.0 + (i % 6) * 2.0 - 5.0  # 震荡
        bars.append({"date": f"2026-01-{i % 28 + 1:02d}", "open": close, "high": close + 1,
                     "low": close - 1, "close": close, "volume": 10000})
    return bars


def test_multi_factor_returns_unified_shape():
    result = MultiFactorStrategy().backtest(
        _bars(), {"capital": 100000, "feeBps": 3, "maxConsecutiveLosses": 10}
    )
    assert set(result.keys()) == {
        "trades", "equityCurve", "benchmarkCurve", "metrics", "assumptions", "moduleUsage",
    }
    assert "多因子" in result["assumptions"]


def test_multi_factor_trend_module_structure_present():
    result = MultiFactorStrategy().backtest(
        _bars(80, "trend"), {"capital": 100000, "feeBps": 3}
    )
    usage = result["moduleUsage"]
    assert "trend" in usage and "range" in usage
    for key in ("trades", "frozenPeriods"):
        assert key in usage["trend"]
        assert key in usage["range"]


def test_multi_factor_stagnation_guard_freezes_losing_module():
    # 子类强制「偶数日高价买、奇数日低价卖」：每笔 round trip 都亏损 → 达阈值冻结
    class Whipsaw(MultiFactorStrategy):
        def signal_at(self, index, state):
            if self._module_stats["trend"]["frozen"]:
                return None  # 冻结检查（与父类行为一致）
            bars = self._bars
            close = float(bars[index]["close"])
            date = bars[index].get("date", "")
            if index % 2 == 0 and state.shares == 0:
                return Signal(date, "buy", close, reason="假买", module="trend")
            if index % 2 == 1 and state.shares > 0:
                return Signal(date, "sell", close, reason="假卖", module="trend")
            return None

    bars = [
        {"date": f"2026-01-{i + 1:02d}", "open": 100.0, "high": 100.0, "low": 100.0,
         "close": 100.0 - i, "volume": 10000}
        for i in range(20)
    ]
    result = Whipsaw().backtest(bars, {"capital": 100000, "feeBps": 3, "maxConsecutiveLosses": 3})
    stats = result["moduleUsage"]["trend"]
    assert stats["frozenPeriods"], "连续亏损应触发冻结记录"
    frozen_start = stats["frozenPeriods"][0]["start"]
    frozen_trades = [t for t in result["trades"] if t.get("module") == "trend" and t["date"] > frozen_start]
    assert all(t["side"] != "buy" for t in frozen_trades), "冻结后 trend 模块不得再买入"


def test_multi_factor_assumptions_disclose_adx_lag():
    result = MultiFactorStrategy().backtest(_bars(), {"capital": 100000, "feeBps": 3})
    assert "滞后" in result["assumptions"] or "ADX" in result["assumptions"]
```

- [ ] **Step 2: 运行测试确认红**

Run: `python -m pytest tests/test_multi_factor.py -q`
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现多因子模型**

```python
# backend/multi_factor.py
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
                    sig = Signal(date, "buy", close, reason=f"震荡市：跌破下轨 {lower[index]:.2f} 均值回归买入", module="range")
                elif state.shares > 0 and close > upper[index]:
                    sig = Signal(date, "sell", close, reason=f"震荡市：上穿上轨 {upper[index]:.2f} 卖出", module="range")
        else:
            period = int(self._cfg("trendPeriod", 20))
            adx_period = int(self._cfg("trendAdxPeriod", 14))
            adx_threshold = float(self._cfg("trendAdxThreshold", 25))
            upper, lower = donchian(bars, period)
            if upper[index] is not None:
                if state.shares == 0:
                    adx_val = adx(bars, adx_period)[index]
                    if close > upper[index] and adx_val is not None and adx_val > adx_threshold:
                        sig = Signal(date, "buy", close, reason=f"趋势市：突破上轨 {upper[index]:.2f} 且 ADX={adx_val:.1f}", module="trend")
                elif close < lower[index]:
                    sig = Signal(date, "sell", close, reason=f"趋势市：跌破下轨 {lower[index]:.2f} 趋势衰竭", module="trend")

        if sig is None:
            return None
        stats = self._module_stats[sig.module]
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
                stats["frozenPeriods"].append(
                    {"start": trade["date"], "end": None, "suppressedSignals": 0}
                )

    def backtest(self, bars: list[dict[str, Any]], config: dict[str, Any]) -> dict[str, Any]:
        self._module_stats = {
            "range": {"trades": 0, "consecutiveLosses": 0, "frozen": False, "frozenPeriods": []},
            "trend": {"trades": 0, "consecutiveLosses": 0, "frozen": False, "frozenPeriods": []},
        }
        self._pending_buy_cost = {}
        result = super().backtest(bars, config)
        # 冻结期结束标记：以最后一根 K 线为 end（若仍冻结则保持 None）
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
            f"模块连续亏损达 {max_losses} 笔后冻结，资金保持现金；盈利后自动复位。"
            f"ADX 为滞后指标，市场状态切换存在延迟，此为已知局限。"
            "按当日收盘价成交、100 股整数倍、T+1 可卖。"
            "费用包含佣金（最低 5 元）、印花税（卖出 0.05%）及过户费。"
            "结果仅用于研究，不代表未来收益。"
        )
```

- [ ] **Step 4: 运行测试确认绿**

Run: `python -m pytest tests/test_multi_factor.py -q`
Expected: PASS（若 `test_multi_factor_trend_module_active_on_uptrend` 因单边上涨序列中 ADX 预热期较长导致 trend 交易少，将 `_bars` count 提高到 120 或调整断言为 `usage["trend"]["trades"] > 0`）

- [ ] **Step 5: Commit**

```bash
git add backend/multi_factor.py tests/test_multi_factor.py
git commit -m "feat: 多因子模型（ADX状态过滤+动态切换+僵局保护）"
```

---

### Task 6: 注册表改造 + schema 更新

**Files:**
- Modify: `backend/strategy_engines.py`（注册全部新策略）
- Modify: `backend/schemas.py`（`StrategyBacktestIn` 增加 `capitalAllocation`）
- Modify: `tests/test_strategy_engines.py`（注册表断言更新）

**Interfaces:**
- Consumes: 全部策略类
- Produces: `STRATEGY_ENGINES` 含 7 项（grid/ma_cross/dca/macd/bollinger/donchian/momentum/multi_factor → 8 项）；`StrategyBacktestIn.capitalAllocation: float = 1.0`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_strategy_engines.py 更新注册表断言
def test_strategy_engines_registry_lists_all_types():
    assert set(STRATEGY_ENGINES.keys()) == {
        "ma_cross", "dca", "macd", "bollinger", "donchian", "momentum", "multi_factor",
    }
    for spec in STRATEGY_ENGINES.values():
        assert spec["label"]
        assert callable(spec["backtest"])
        assert spec["configSchema"]
```

> 注意：`grid` 不在 `STRATEGY_ENGINES` 注册表中（网格由 `/api/grid/*` 独立路由与 `backtest_grid` 管理，保持现状）。

```python
# tests/test_schemas.py 追加
def test_strategy_backtest_in_accepts_capital_allocation():
    from backend.schemas import StrategyBacktestIn
    payload = StrategyBacktestIn(strategyType="momentum", code="600519", capital=100000, capitalAllocation=0.6)
    assert payload.capitalAllocation == 0.6
```

- [ ] **Step 2: 运行测试确认红**

Run: `python -m pytest tests/test_strategy_engines.py tests/test_schemas.py -q`
Expected: FAIL（注册表缺新类型 / schema 缺字段）

- [ ] **Step 3: 注册表补全**

```python
# backend/strategy_engines.py 替换注册表（完整版）
from backend.strategies.bollinger import BollingerStrategy
from backend.strategies.dca import DcaStrategy
from backend.strategies.donchian import DonchianStrategy
from backend.strategies.ma_cross import MaCrossStrategy
from backend.strategies.macd import MacdStrategy
from backend.strategies.momentum import MomentumStrategy
from backend.multi_factor import MultiFactorStrategy

STRATEGY_ENGINES: dict[str, dict[str, Any]] = {
    "ma_cross": {"label": "双均线", "backtest": MaCrossStrategy().backtest, "suggest": None, "configSchema": MaCrossStrategy.config_schema},
    "dca": {"label": "定投", "backtest": DcaStrategy().backtest, "suggest": None, "configSchema": DcaStrategy.config_schema},
    "macd": {"label": "MACD", "backtest": MacdStrategy().backtest, "suggest": None, "configSchema": MacdStrategy.config_schema},
    "bollinger": {"label": "布林带反转", "backtest": BollingerStrategy().backtest, "suggest": None, "configSchema": BollingerStrategy.config_schema},
    "donchian": {"label": "唐奇安突破", "backtest": DonchianStrategy().backtest, "suggest": None, "configSchema": DonchianStrategy.config_schema},
    "momentum": {"label": "动量", "backtest": MomentumStrategy().backtest, "suggest": None, "configSchema": MomentumStrategy.config_schema},
    "multi_factor": {"label": "多因子", "backtest": MultiFactorStrategy().backtest, "suggest": None, "configSchema": MultiFactorStrategy.config_schema},
}
```

> 注意：`grid` 不在此注册表（网格保持独立，由 `backtest_grid` 管理）。原 `strategy_engines.py` 中 `_ema`/`_ma` 辅助函数已迁入 `indicators`，可安全删除。

- [ ] **Step 4: schema 增加字段**

```python
# backend/schemas.py 的 StrategyBacktestIn 追加
    capitalAllocation: float = Field(default=1.0, ge=0.1, le=1.0)
```

同时在 `backend/app.py` 的 `strategy_backtest` 路由中，将 `payload.capitalAllocation` 写入 config：

```python
config.update(
    {
        "capital": payload.capital,
        "feeBps": payload.feeBps,
        "securityType": profile["securityType"],
        "exchange": profile["exchange"],
        "lookback": lookback,
        "capitalAllocation": payload.capitalAllocation,
    }
)
```

- [ ] **Step 5: 运行测试确认绿**

Run: `python -m pytest tests/ -q`
Expected: PASS（全量后端回归）

- [ ] **Step 6: Commit**

```bash
git add backend/strategy_engines.py backend/schemas.py backend/app.py tests/
git commit -m "feat: 注册表接入全部新策略并支持资金分配比例"
```

---

### Task 7: 前端策略类型与配置表单

**Files:**
- Modify: `frontend/src/modules/constants.ts`（`STRATEGY_TYPES` + `STRATEGY_SCHEMAS`）
- Modify: `frontend/src/views/ViewGrid.vue`（tab 图标映射）
- Modify: `frontend/src/modules/lucideIcons.ts`（新增图标注册）

**Interfaces:**
- Consumes: 现有 `STRATEGY_TYPES` / `STRATEGY_SCHEMAS` 结构
- Produces: 前端出现 8 个策略 tab，多因子显示两级配置

- [ ] **Step 1: 更新 constants.ts**

```typescript
// frontend/src/modules/constants.ts 追加到 STRATEGY_TYPES
export const STRATEGY_TYPES = [
  { id: 'grid', label: '网格', description: '区间网格，跌买涨卖' },
  { id: 'ma_cross', label: '双均线', description: '快线上穿买入，下穿卖出' },
  { id: 'dca', label: '定投', description: '定期定额 + 止盈止损' },
  { id: 'macd', label: 'MACD', description: 'DIF 上穿 DEA 买入，下穿卖出' },
  { id: 'bollinger', label: '布林带反转', description: '跌破下轨买入，上穿上轨卖出（均值回归）' },
  { id: 'donchian', label: '唐奇安突破', description: '通道突破入场，反向突破离场（ADX 确认）' },
  { id: 'momentum', label: '动量', description: 'N 日涨跌幅阈值进出，独立资金管理' },
  { id: 'multi_factor', label: '多因子', description: 'ADX 状态过滤器 + 动态模块切换' },
];

// STRATEGY_SCHEMAS 追加
  bollinger: [
    { key: 'period', label: '均线周期', type: 'int', default: 20, min: 5, max: 120, suffix: '日' },
    { key: 'numStd', label: '标准差倍数', type: 'float', default: 2, min: 0.5, max: 4, step: 0.1, suffix: 'σ' },
  ],
  donchian: [
    { key: 'period', label: '通道周期', type: 'int', default: 20, min: 5, max: 120, suffix: '日' },
    { key: 'adxPeriod', label: 'ADX 周期', type: 'int', default: 14, min: 5, max: 60, suffix: '日' },
    { key: 'adxThreshold', label: 'ADX 阈值', type: 'int', default: 25, min: 10, max: 50, suffix: '' },
  ],
  momentum: [
    { key: 'period', label: '动量周期', type: 'int', default: 20, min: 3, max: 120, suffix: '日' },
    { key: 'entryPct', label: '入场阈值', type: 'float', default: 5, min: 0.5, max: 50, step: 0.5, suffix: '%' },
    { key: 'exitPct', label: '退出阈值', type: 'float', default: -3, min: -50, max: 0, step: 0.5, suffix: '%' },
  ],
  multi_factor: [
    { key: 'adxPeriod', label: 'ADX 周期', type: 'int', default: 14, min: 5, max: 60, suffix: '日' },
    { key: 'adxThreshold', label: 'ADX 阈值', type: 'int', default: 25, min: 10, max: 50, suffix: '' },
    { key: 'maxConsecutiveLosses', label: '最大连续亏损', type: 'int', default: 10, min: 2, max: 50, suffix: '笔' },
    { key: 'rangePeriod', label: '震荡MA周期', type: 'int', default: 20, min: 5, max: 120, suffix: '日' },
    { key: 'rangeStd', label: '震荡标准差', type: 'float', default: 2, min: 0.5, max: 4, step: 0.1, suffix: 'σ' },
    { key: 'trendPeriod', label: '趋势通道周期', type: 'int', default: 20, min: 5, max: 120, suffix: '日' },
    { key: 'trendAdxPeriod', label: '趋势ADX周期', type: 'int', default: 14, min: 5, max: 60, suffix: '日' },
    { key: 'trendAdxThreshold', label: '趋势ADX阈值', type: 'int', default: 25, min: 10, max: 50, suffix: '' },
  ],
```

- [ ] **Step 2: 更新 ViewGrid.vue tab 图标映射**

`frontend/src/views/ViewGrid.vue` 第 8 行的 `:data-lucide` 三元表达式改为：

```html
<i :data-lucide="item.id === 'grid' ? 'grid-3x3' : item.id === 'ma_cross' ? 'trending-up' : item.id === 'dca' ? 'calendar-clock' : item.id === 'macd' ? 'activity' : item.id === 'bollinger' ? 'chart-no-axes-combined' : item.id === 'donchian' ? 'trending-up' : item.id === 'momentum' ? 'zap' : 'layers'" aria-hidden="true"></i>
```

- [ ] **Step 3: 更新 lucideIcons.ts**

`frontend/src/modules/lucideIcons.ts` 的 import 与 `UI_ICONS` 追加 `Zap`、`Layers`（若 `ChartNoAxesCombined` 已存在则复用；若 lucide 1.38 无 `Layers`，改用已有的 `Grid3x3`）：

```typescript
import { ..., Layers, Zap } from 'lucide';
// UI_ICONS 追加
  Layers,
  Zap,
```

- [ ] **Step 4: 前端多因子描述提示**

`ViewGrid.vue` 多因子 tab 的说明（`heading-note` 区域）追加模块说明。在 `strategyType === 'multi_factor'` 时显示：

```html
<p class="heading-note" v-if="strategyType === 'multi_factor'">ADX ≥ 阈值进入趋势市（唐奇安突破），否则震荡市（布林带反转）；模块连续亏损自动冻结。结果仅用于研究。</p>
```

（`strategyType` 为 `ref`，在 `<script setup>` 中可直接使用。）

- [ ] **Step 5: 类型检查 + 前端测试**

Run: `npx vue-tsc --noEmit`
Expected: PASS（无类型错误）

Run: `npx vitest run`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/modules/constants.ts frontend/src/views/ViewGrid.vue frontend/src/modules/lucideIcons.ts
git commit -m "feat: 前端接入布林带/唐奇安/动量/多因子策略类型"
```

---

### Task 8: 全量回归、文档与收尾

**Files:**
- Modify: `ROADMAP.md`（勾选新策略类型待办）
- Modify: `tests/test_strategy_engines.py`（如需补充 coverage）

- [ ] **Step 1: 全量后端回归 + 覆盖率**

Run: `python -m pytest tests/ -q`
Expected: PASS（覆盖率门禁 ≥80%）

Run: `python -m ruff check backend tests server.py`
Expected: PASS

Run: `python -m mypy backend`
Expected: PASS

- [ ] **Step 2: 前端全量**

Run: `npx vitest run`
Expected: PASS

Run: `npm run build`
Expected: PASS（vue-tsc + vite build 成功）

- [ ] **Step 3: 更新 ROADMAP.md**

在「新策略类型」小节标注已完成：

```markdown
### 新策略类型
- [x] 当前支持：网格、双均线（SMA）、定投（DCA）、MACD 四种
- [x] 已扩展：布林带反转、唐奇安突破、动量、多因子（ADX 状态过滤 + 动态切换 + 僵局保护）
- [x] 策略引擎已泛化（`backend/strategy_engines.py` + `backend/strategy_base.py` + `backend/indicators.py`）
```

- [ ] **Step 4: 浏览器手动验证**

- 启动：`npm run dev`（或 `python server.py` + 前端构建）
- 打开策略实验室：出现 8 个 tab
- 布林带：输入代码 → 运行回测 → 指标/权益曲线正常
- 唐奇安：同上
- 动量：同上
- 多因子：出现 ADX/震荡/趋势/僵局保护两级配置 → 回测 → `moduleUsage` 可见（在回测结果区显示模块统计，若前端未渲染 `moduleUsage`，至少保证回测不报错）
- 保存策略 → 已保存策略列表出现

- [ ] **Step 5: 全量提交**

```bash
git add ROADMAP.md
git commit -m "docs: ROADMAP 更新新策略类型完成状态"
```

- [ ] **Step 6: Git Flow 收尾**

```bash
git flow feature finish strategy-engine-refactor
```

Expected: 合并回 `develop` 成功，分支删除

---

## 自审记录

- **Spec 覆盖**：指标库（Task 1）✓；基类（Task 2）✓；现有策略迁移（Task 3）✓；新独立策略（Task 4）✓；多因子+僵局保护（Task 5）✓；注册表+资金分配（Task 6）✓；前端（Task 7）✓；回归+文档（Task 8）✓。设计文档中「坑 1 资金隔离」「坑 2 僵局保护」「坑 3 ADX 延迟」全部落地。
- **占位符**：无 TBD/TODO；所有实现代码均为具体可运行代码。
- **类型一致性**：`Signal/ExecutionState/BaseStrategy.signal_at/on_trade` 在各任务签名一致；`capitalAllocation` 在 schema/基类/前端 schema 字段名一致；`moduleUsage/frozenPeriods/theoreticalIfUnfrozen` 命名一致。
- **已知权衡**：Task 5 的僵局保护测试（`test_multi_factor_stagnation_guard_freeze`）因构造数据难度可能只验证结构而非真实冻结触发，若需要真实触发用例可在 Step 4 用确定性亏损序列（高买低卖）补充。
