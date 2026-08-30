# 追加风险指标实施计划

> **For agentic workers:** Use superpowers:executing-plans (inline) to implement this plan task-by-task.

**Goal:** 网格回测指标追加胜率、最长回撤持续期、单格平均收益、利润因子，完善策略评估维度。

**Architecture:** 纯后端 `grid_strategy.py` 指标计算（additive，不破坏现有指标）+ 前端显示。

**Tech Stack:** Python（statistics），Vue 3 全局构建。验证：pytest（TDD）+ `node --check` + 浏览器手动。

---

### Task 1: 分支准备

- [x] `git flow feature start risk-metrics`

---

### Task 2: 后端指标计算（TDD）

**Files:** `backend/grid_strategy.py`, `tests/test_grid_strategy.py`

- [x] **Step 1: 先写失败测试**

`tests/test_grid_strategy.py` 追加：

```python
def test_metrics_include_new_risk_fields():
    result = backtest_grid(sample_bars(), lower=8, upper=12, grid_count=4, capital=100000, fee_bps=3)
    m = result["metrics"]
    for key in ("winRatePct", "maxDrawdownDurationDays", "avgGridReturnPct", "profitFactor"):
        assert key in m, f"missing {key}"
    if m["winRatePct"] is not None:
        assert 0 <= m["winRatePct"] <= 100
    assert m["maxDrawdownDurationDays"] >= 0


def test_risk_metrics_round_trip_accuracy():
    # 手工构造的可预测场景：指定价格序列使网格明确买卖
    bars = [
        {"date": "2026-01-02", "open": 10, "high": 10, "low": 10, "close": 10},
        {"date": "2026-01-03", "open": 10, "high": 8, "low": 8, "close": 8},
        {"date": "2026-01-06", "open": 8, "high": 12, "low": 8, "close": 12},
        {"date": "2026-01-07", "open": 12, "high": 12, "low": 12, "close": 12},
    ]
    result = backtest_grid(bars, lower=8, upper=12, grid_count=4, capital=100000, fee_bps=3)
    m = result["metrics"]
    assert m["winRatePct"] is not None
    # 买入在跌、卖出在涨 → 应盈利
    assert m["avgGridReturnPct"] > 0
```

- [x] **Step 2: 跑测试确认红**

`python -m pytest tests/test_grid_strategy.py -q` → 2 failed。

- [x] **Step 3: 实现**

`backend/grid_strategy.py` 末尾追加两个辅助函数和 `backtest_grid` 内指标计算：

```python
def _round_trip_returns(trades: list[dict]) -> list[float]:
    """FIFO 配对买卖，返回每笔完整 round trip 的收益率。"""
    buy_queue: list[list[float]] = []  # [shares, cost, fee_per_share]
    returns = []
    for t in trades:
        if t["side"] == "buy":
            buy_queue.append([float(t["shares"]), float(t["price"]), float(t["fee"]) / float(t["shares"])])
        elif t["side"] == "sell":
            remaining = float(t["shares"])
            sell_proceeds = remaining * float(t["price"]) - float(t["fee"])
            buy_cost = 0.0
            while remaining > 0.001 and buy_queue:
                entry = buy_queue[0]
                consume = min(entry[0], remaining)
                buy_cost += consume * (entry[1] + entry[2])
                entry[0] -= consume
                remaining -= consume
                if entry[0] < 0.001:
                    buy_queue.pop(0)
            if buy_cost > 0:
                returns.append((sell_proceeds - buy_cost) / buy_cost)
    return returns


def _max_drawdown_duration(equity_curve: list[float]) -> int:
    """从权益曲线计算最长回撤持续期（交易日数）。"""
    if not equity_curve:
        return 0
    peak_idx = 0
    max_duration = 0
    for i, eq in enumerate(equity_curve):
        if eq >= equity_curve[peak_idx]:
            peak_idx = i
        else:
            duration = i - peak_idx
            if duration > max_duration:
                max_duration = duration
    return max_duration
```

在 `metrics` dict 构建后（`metrics = {...}` 块之后）追加：

```python
    round_trip_returns = _round_trip_returns(trades)
    win_count = sum(1 for r in round_trip_returns if r > 0)
    total_count = len(round_trip_returns)
    gross_profit = sum(r for r in round_trip_returns if r > 0)
    gross_loss = abs(sum(r for r in round_trip_returns if r < 0))
    metrics["winRatePct"] = round(win_count / total_count * 100, 1) if total_count else None
    metrics["avgGridReturnPct"] = round(mean(round_trip_returns) * 100, 2) if round_trip_returns else None
    metrics["medianGridReturnPct"] = round(median(round_trip_returns) * 100, 2) if round_trip_returns else None
    metrics["maxDrawdownDurationDays"] = _max_drawdown_duration(equity_curve)
    metrics["profitFactor"] = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (None if not total_count else float("inf"))
```

- [x] **Step 4: 跑测试确认绿 + 提交**

`python -m pytest tests/test_grid_strategy.py -q` → 全绿；`python -m pytest tests/ -q` → 全量回归。

```bash
git add backend/grid_strategy.py tests/test_grid_strategy.py
git commit -m "feat: 网格回测追加胜率、最长回撤、单格收益与利润因子"
```

---

### Task 3: 前端显示

**Files:** `frontend/index.html`

- [x] **Step 1: index.html 追加三项指标**

`grid-metrics-secondary` 行（`gridResult.metrics.turnoverMultiple` 之后）追加：

```html
<div><span>胜率</span><strong>{{ gridResult.metrics.winRatePct != null ? gridResult.metrics.winRatePct.toFixed(1) + '%' : '--' }}</strong></div>
<div><span>最长回撤</span><strong>{{ gridResult.metrics.maxDrawdownDurationDays != null ? gridResult.metrics.maxDrawdownDurationDays + ' 天' : '--' }}</strong></div>
<div><span>单格收益</span><strong>{{ gridResult.metrics.avgGridReturnPct != null ? gridResult.metrics.avgGridReturnPct.toFixed(2) + '%' : '--' }}</strong></div>
```

- [x] **Step 2: 验证 + 提交**

`node --check frontend/app.js` → 通过（index.html 不含 JS 需要检查，但此项只改模板，无语法检查必要）。

```bash
git add frontend/index.html
git commit -m "feat: 指标展示追加胜率、最长回撤与单格收益"
```

---

### Task 4: 回归、验证与收尾

- [x] **Step 1: 全量回归**

`python -m pytest tests/ -q` + `node --check frontend/app.js` → 全绿。

- [x] **Step 2: 浏览器手动验证**

- 跑一次网格回测 → 指标卡出现「胜率」「最长回撤」「单格收益」数值合理
- 空数据场景不报错（如无完整 round trip 时显示 `--`）

- [x] **Step 3: 完成分支**

```bash
git flow feature finish risk-metrics
```