# 追加风险指标设计 — 2026-08-30

## 目标

在网格回测现有指标（收益/回撤/夏普/成交/换手等）基础上，追加回撤持续期、胜率、单格收益分布等风险指标，完善策略评估维度。

## 非目标

- 不改变现有回测算法逻辑。
- 不改变现有测试数据构造（`sample_bars()` 4 个交易日仍可跑通）。
- 不涉及前端大的布局重构，仅在现有指标行（`grid-metrics`）追加显示。

## 数据层（backend/grid_strategy.py）

`backtest_grid` 的 `metrics` dict 追加以下字段（均为 additive，不破坏现有使用者）：

### 1. 胜率与单格收益

从 `trades` 列表将买卖配对（FIFO 先进先出，与 `lots_held` 逻辑一致）：

```python
def _round_trip_stats(trades: list[dict]) -> dict:
    buy_queue = []  # [(shares, cost_per_share, fee_per_share)]
    round_trips = []  # 每笔完整买卖的收益
    for t in trades:
        if t["side"] == "buy":
            buy_queue.append([t["shares"], t["price"], t["fee"] / t["shares"]])
        else:
            remaining = t["shares"]
            sell_proceeds = remaining * t["price"] - t["fee"]
            buy_cost = 0
            while remaining > 0 and buy_queue:
                entry = buy_queue[0]
                consume = min(entry[0], remaining)
                buy_cost += consume * (entry[1] + entry[2])
                entry[0] -= consume
                remaining -= consume
                if entry[0] == 0:
                    buy_queue.pop(0)
            if buy_cost > 0:
                round_trips.append((sell_proceeds - buy_cost) / buy_cost)  # 收益率
    return round_trips
```

指标追加：
- `winRatePct`: 盈利 round trip 占比 * 100
- `avgGridReturnPct`: round trip 收益率均值 * 100
- `medianGridReturnPct`: round trip 收益率中位数 * 100
- `avgGridReturnPct` 和 `medianGridReturnPct` 为空（无完整 round trip）时设为 `None`

### 2. 最长回撤持续期

```python
def _max_drawdown_duration(equity_curve: list[float], bars: list[dict]) -> int:
    peak_idx = 0
    max_duration = 0
    for i, eq in enumerate(equity_curve):
        if eq >= equity_curve[peak_idx]:
            peak_idx = i
        else:
            duration = i - peak_idx
            if duration > max_duration:
                max_duration = duration
    return max_duration  # 交易日数
```

指标追加：
- `maxDrawdownDurationDays`: 从峰值到恢复（或到结束）的最长交易日数

### 3. 利润因子

- `profitFactor`: 总盈利 / 总亏损（绝对值）；无亏损时返回 `None`

### 4. 测试

`test_grid_strategy.py` 追加：
```python
def test_metrics_include_new_risk_fields():
    result = backtest_grid(sample_bars(), lower=8, upper=12, grid_count=4, capital=100000, fee_bps=3)
    m = result["metrics"]
    assert "winRatePct" in m
    assert "maxDrawdownDurationDays" in m
    assert "avgGridReturnPct" in m
    assert "profitFactor" in m
    if m["winRatePct"] is not None:
        assert 0 <= m["winRatePct"] <= 100
```

## 前端（frontend/index.html + app.js）

`grid-metrics-secondary` 行追加三项（若指标不为 null）：

```html
<div><span>胜率</span><strong>{{ gridResult.metrics.winRatePct != null ? gridResult.metrics.winRatePct.toFixed(1) + '%' : '--' }}</strong></div>
<div><span>最长回撤</span><strong>{{ gridResult.metrics.maxDrawdownDurationDays != null ? gridResult.metrics.maxDrawdownDurationDays + ' 天' : '--' }}</strong></div>
<div><span>单格收益</span><strong>{{ gridResult.metrics.avgGridReturnPct != null ? gridResult.metrics.avgGridReturnPct.toFixed(2) + '%' : '--' }}</strong></div>
```

若行内元素超过 6 个可换行，用现有 `grid-metrics` 弹性布局自动适应。

## 验证

- pytest: `test_grid_strategy.py` 新增断言通过，现有 47 项回归全绿。
- `node --check`。
- 手动：跑一次网格回测 → 结果卡显示"胜率"/"最长回撤"/"单格收益"（数值合理）。