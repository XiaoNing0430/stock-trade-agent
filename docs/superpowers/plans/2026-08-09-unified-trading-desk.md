# Unified Trading Desk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn Atlas into a unified desktop-first trading desk, fix critical mobile navigation issues, and make grid backtests comparable and diagnostically trustworthy.

**Architecture:** Keep quantitative calculations in `backend/grid_strategy.py` and expose additive API fields through the existing FastAPI routes. Keep the current Vue 3 no-build frontend, deriving dashboard state in `frontend/app.js`, rendering semantic sections in `frontend/index.html`, and using `frontend/styles.css` for the single-scroll desktop model and mobile navigation.

**Tech Stack:** Python 3, FastAPI, pytest, Vue 3 global build, vanilla CSS, Lucide icons

---

## File Map

- Modify `backend/grid_strategy.py`: benchmark, equity curves, risk/cost metrics, candidate quality and sorting.
- Modify `backend/app.py`: add data-window metadata to grid preview, backtest, and optimization responses.
- Modify `frontend/app.js`: dashboard derivations, comparison chart formatter, settings tab state, dirty state, and mobile navigation state.
- Modify `frontend/index.html`: unified dashboard, backtest report, settings tabs, execution tabs, and mobile navigation markup.
- Modify `frontend/styles.css`: dashboard/report components, desktop single-scroll behavior, grouped settings, and responsive mobile layout.
- Modify `tests/test_grid_strategy.py`: quantitative metric and candidate-quality tests.
- Modify `tests/test_backend_api.py`: additive grid API contract tests.
- Create `tests/test_frontend_contract.py`: static contracts for required navigation, report, settings, and layout hooks.

### Task 1: Add Comparable Backtest Metrics

**Files:**
- Modify: `backend/grid_strategy.py:50`
- Modify: `tests/test_grid_strategy.py:30`

- [x] **Step 1: Write failing tests for the benchmark and risk metrics**

Append to `tests/test_grid_strategy.py`:

```python
def test_backtest_reports_buy_hold_excess_risk_and_cost_metrics():
    closes = [10] + [10 + index * 0.04 + (0.06 if index % 2 else -0.03) for index in range(1, 24)] + [11]
    bars = [
        {"date": f"2026-02-{index + 1:02d}", "open": close, "high": close + 0.3, "low": close - 0.3, "close": close, "volume": 1000}
        for index, close in enumerate(closes)
    ]

    result = backtest_grid(bars, 8, 12, 4, 100000, security_type="ETF")
    metrics = result["metrics"]

    assert metrics["benchmarkReturnPct"] == 9.9
    assert metrics["excessReturnPct"] == round(metrics["returnPct"] - 9.9, 2)
    assert metrics["annualizedVolatilityPct"] is not None
    assert metrics["sharpeRatio"] is not None
    assert metrics["totalFees"] > 0
    assert metrics["turnoverRatio"] > 0
    assert len(result["equityCurve"]) == len(bars)
    assert len(result["benchmarkCurve"]) == len(bars)


def test_short_or_zero_volatility_history_omits_risk_adjusted_metrics():
    bars = [
        {"date": f"2026-01-{day:02d}", "open": 10, "high": 10.01, "low": 9.99, "close": 10, "volume": 1000}
        for day in range(1, 11)
    ]

    result = backtest_grid(bars, 8, 12, 4, 100000)

    assert result["metrics"]["annualizedReturnPct"] is None
    assert result["metrics"]["annualizedVolatilityPct"] is None
    assert result["metrics"]["sharpeRatio"] is None
```

- [x] **Step 2: Run the new tests and verify they fail**

Run:

```powershell
python -m pytest tests/test_grid_strategy.py::test_backtest_reports_buy_hold_excess_risk_and_cost_metrics tests/test_grid_strategy.py::test_short_or_zero_volatility_history_omits_risk_adjusted_metrics -v
```

Expected: FAIL because `benchmarkReturnPct`, curves, and risk metrics do not exist.

- [x] **Step 3: Add focused metric helpers**

At the top of `backend/grid_strategy.py`, import `sqrt` and `stdev`, then add:

```python
from math import ceil, floor, sqrt
from statistics import median, stdev


def _daily_returns(values: list[float]) -> list[float]:
    return [values[index] / values[index - 1] - 1 for index in range(1, len(values)) if values[index - 1] > 0]


def _risk_metrics(equity_curve: list[float]) -> tuple[float | None, float | None]:
    returns = _daily_returns(equity_curve)
    if len(returns) < 19:
        return None, None
    volatility = stdev(returns)
    if volatility == 0:
        return None, None
    annualized_volatility = volatility * sqrt(252)
    sharpe = (sum(returns) / len(returns)) / volatility * sqrt(252)
    return annualized_volatility, sharpe


def _buy_and_hold_curve(
    bars: list[dict[str, Any]], capital: float, fee_bps: float,
    security_type: str, exchange: str,
) -> tuple[list[float], float]:
    first_close = float(bars[0]["close"])
    commission_rate = fee_bps / 10000

    def buy_fee(value: float) -> float:
        commission = max(5.0, value * commission_rate)
        transfer = value * 0.00001 if security_type == "股票" and exchange == "上交所" else 0.0
        return commission + transfer

    shares = floor(capital / first_close / 100) * 100
    while shares and shares * first_close + buy_fee(shares * first_close) > capital:
        shares -= 100
    value = shares * first_close
    cash = capital - value - (buy_fee(value) if shares else 0)
    return [cash + shares * float(bar["close"]) for bar in bars], buy_fee(value) if shares else 0.0


def _normalized_curve(bars: list[dict[str, Any]], values: list[float], capital: float) -> list[dict[str, Any]]:
    return [
        {"date": str(bar.get("date") or ""), "value": round(value / capital, 6)}
        for bar, value in zip(bars, values)
    ]
```

- [x] **Step 4: Extend `backtest_grid` without changing existing fields**

Replace the initial position debit with an explicit fee value:

```python
    initial_value = initial_lots * first_close
    initial_fee = fee("buy", initial_value) if initial_lots else 0.0
    cash -= initial_value + initial_fee
```

Keep appending `cash + shares * close` to `equity_curve` on every processed or skipped bar. Before returning, compute:

```python
    benchmark_equity, benchmark_fee = _buy_and_hold_curve(bars, capital, fee_bps, security_type, exchange)
    benchmark_return = benchmark_equity[-1] / capital - 1
    annualized_volatility, sharpe = _risk_metrics(equity_curve)
    total_fees = initial_fee + sum(float(item["fee"]) for item in trades)
    traded_value = initial_value + sum(float(item["price"]) * int(item["shares"]) for item in trades)

    metrics.update({
        "benchmarkReturnPct": round(benchmark_return * 100, 2),
        "excessReturnPct": round((total_return - benchmark_return) * 100, 2),
        "annualizedVolatilityPct": round(annualized_volatility * 100, 2) if annualized_volatility is not None else None,
        "sharpeRatio": round(sharpe, 2) if sharpe is not None else None,
        "totalFees": round(total_fees, 2),
        "turnoverRatio": round(traded_value / capital, 2),
        "benchmarkEntryFee": round(benchmark_fee, 2),
    })
```

Return these additive top-level fields:

```python
        "equityCurve": _normalized_curve(bars, equity_curve, capital),
        "benchmarkCurve": _normalized_curve(bars, benchmark_equity, capital),
```

- [x] **Step 5: Run focused and existing strategy tests**

Run:

```powershell
python -m pytest tests/test_grid_strategy.py -v
```

Expected: all strategy tests PASS.

- [x] **Step 6: Commit the metric work**

```powershell
git add backend/grid_strategy.py tests/test_grid_strategy.py
git commit -m "feat: add comparable grid backtest metrics"
```

### Task 2: Add Candidate Robustness and Ranking

**Files:**
- Modify: `backend/grid_strategy.py:166`
- Modify: `tests/test_grid_strategy.py:98`

- [x] **Step 1: Write failing candidate-quality tests**

Append to `tests/test_grid_strategy.py`:

```python
from backend.grid_strategy import candidate_quality


def test_candidate_quality_flags_overfit_and_non_positive_excess():
    quality = candidate_quality(
        {"returnPct": 18, "excessReturnPct": 7, "tradeCount": 12, "buyCount": 6, "sellCount": 6},
        {"returnPct": 3, "excessReturnPct": -1, "tradeCount": 4, "buyCount": 3, "sellCount": 1},
        validation_days=30,
    )

    assert quality["stabilityGapPct"] == 15
    assert quality["recommended"] is False
    assert "可能过拟合" in quality["warnings"]
    assert "样本外无正超额" in quality["warnings"]


def test_candidate_quality_flags_short_and_one_sided_validation():
    quality = candidate_quality(
        {"returnPct": 4, "excessReturnPct": 2, "tradeCount": 4, "buyCount": 2, "sellCount": 2},
        {"returnPct": 3, "excessReturnPct": 1, "tradeCount": 2, "buyCount": 2, "sellCount": 0},
        validation_days=12,
    )

    assert quality["recommended"] is False
    assert "样本外过短" in quality["warnings"]
    assert "样本外成交方向不完整" in quality["warnings"]
```

- [x] **Step 2: Verify the tests fail**

Run:

```powershell
python -m pytest tests/test_grid_strategy.py::test_candidate_quality_flags_overfit_and_non_positive_excess tests/test_grid_strategy.py::test_candidate_quality_flags_short_and_one_sided_validation -v
```

Expected: collection FAIL because `candidate_quality` is not defined.

- [x] **Step 3: Implement candidate quality and stable sort keys**

Add to `backend/grid_strategy.py`:

```python
def candidate_quality(training: dict[str, Any], validation: dict[str, Any], validation_days: int) -> dict[str, Any]:
    gap = abs(float(training["returnPct"]) - float(validation["returnPct"]))
    warnings = []
    if validation_days < 20:
        warnings.append("样本外过短")
    if gap > 10:
        warnings.append("可能过拟合")
    if float(validation.get("excessReturnPct") or 0) <= 0:
        warnings.append("样本外无正超额")
    if not validation.get("tradeCount"):
        warnings.append("样本外无成交")
    elif not validation.get("buyCount") or not validation.get("sellCount"):
        warnings.append("样本外成交方向不完整")
    return {"stabilityGapPct": round(gap, 2), "warnings": warnings, "recommended": not warnings}


def _candidate_sort_key(candidate: dict[str, Any]) -> tuple[float, float, float]:
    metrics = candidate["metrics"]
    return (
        float(metrics.get("excessReturnPct") or 0),
        -float(metrics["maxDrawdownPct"]),
        -float(candidate["quality"]["stabilityGapPct"]),
    )
```

When building each candidate, add:

```python
            quality = candidate_quality(in_sample["metrics"], out_of_sample["metrics"], len(validation_bars))
            candidates.append({
                "gridCount": grid_count,
                "lower": round(lower, 2),
                "upper": round(upper, 2),
                "step": round((upper - lower) / grid_count, 3),
                "inSampleMetrics": in_sample["metrics"],
                "quality": quality,
                **out_of_sample,
            })
```

Return `sorted(candidates, key=_candidate_sort_key, reverse=True)`.

- [x] **Step 4: Update the existing ranking test**

Replace its final assertion with:

```python
    assert "quality" in candidates[0]
    sort_keys = [
        (
            item["metrics"]["excessReturnPct"],
            -item["metrics"]["maxDrawdownPct"],
            -item["quality"]["stabilityGapPct"],
        )
        for item in candidates
    ]
    assert sort_keys == sorted(sort_keys, reverse=True)
```

- [x] **Step 5: Run the full strategy test file and commit**

Run `python -m pytest tests/test_grid_strategy.py -v`.

Expected: all tests PASS.

```powershell
git add backend/grid_strategy.py tests/test_grid_strategy.py
git commit -m "feat: rank grid candidates by robustness"
```

### Task 3: Expose Backtest Data Provenance

**Files:**
- Modify: `backend/app.py:128-176`
- Modify: `tests/test_backend_api.py`

- [x] **Step 1: Write a failing grid API contract test**

Append to `tests/test_backend_api.py`:

```python
def test_grid_backtest_returns_data_window_and_comparison_metrics(monkeypatch):
    history = [
        {"date": "2026-01-02", "open": 10, "high": 10.2, "low": 9.8, "close": 10, "volume": 1000},
        {"date": "2026-01-03", "open": 10, "high": 11.2, "low": 9.2, "close": 11, "volume": 1000},
    ]
    monkeypatch.setattr(app_module, "load_history", lambda code, limit: history)
    monkeypatch.setattr(app_module, "save_market_bars", lambda code, rows: "2026-01-03")

    with TestClient(app_module.create_app()) as client:
        response = client.post("/api/grid/backtest", json={"code": "588000", "lower": 8, "upper": 12})

    payload = response.json()
    assert response.status_code == 200
    assert payload["dataWindow"] == {
        "startDate": "2026-01-02",
        "endDate": "2026-01-03",
        "tradingDays": 2,
        "adjustment": "前复权",
        "provider": "Tencent public quote API",
        "dataAsOf": "2026-01-03",
    }
    assert "benchmarkReturnPct" in payload["metrics"]
```

- [x] **Step 2: Run the test and verify it fails**

Run `python -m pytest tests/test_backend_api.py::test_grid_backtest_returns_data_window_and_comparison_metrics -v`.

Expected: FAIL because `dataWindow` is absent.

- [x] **Step 3: Add one metadata helper and reuse it across grid routes**

Add near `create_app` in `backend/app.py`:

```python
def history_metadata(history: list[dict], data_as_of: str | None) -> dict:
    if not history:
        raise ValueError("历史日线为空")
    return {
        "startDate": str(history[0]["date"]),
        "endDate": str(history[-1]["date"]),
        "tradingDays": len(history),
        "adjustment": "前复权",
        "provider": "Tencent public quote API",
        "dataAsOf": data_as_of,
    }
```

Add `"dataWindow": history_metadata(history, data_as_of)` to preview, backtest, and optimize responses. Keep `config.dataAsOf` for compatibility.

- [x] **Step 4: Run API regression tests and commit**

Run `python -m pytest tests/test_backend_api.py -v`.

Expected: all API tests PASS.

```powershell
git add backend/app.py tests/test_backend_api.py
git commit -m "feat: expose grid backtest provenance"
```

### Task 4: Build the Unified Trading Desk

**Files:**
- Modify: `frontend/app.js:55-375,1086-1180`
- Modify: `frontend/index.html:95-330`
- Modify: `frontend/styles.css:865-1180`
- Create: `tests/test_frontend_contract.py`

- [x] **Step 1: Create failing static frontend contracts**

Create `tests/test_frontend_contract.py`:

```python
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
CSS = (ROOT / "frontend" / "styles.css").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")


def test_overview_contains_unified_trading_desk_sections():
    assert "今日交易台" in HTML
    assert "发现机会" in HTML
    assert "验证策略" in HTML
    assert "执行跟踪" in HTML
    assert "stopAlertCount" in JS
    assert ".desk-workflows" in CSS


def test_screener_uses_page_scroll_contract():
    assert "overflow-y: auto" in CSS
    assert ".screener-view .results-table-wrap" in CSS
```

- [x] **Step 2: Run the contract test and verify it fails**

Run `python -m pytest tests/test_frontend_contract.py -v`.

Expected: FAIL because the unified desk hooks do not exist.

- [x] **Step 3: Add dashboard derivations to `frontend/app.js`**

Add computed values after `unreadAlerts`:

```javascript
    const stopAlertCount = computed(() => alerts.value.filter((alert) => {
      const text = `${alert.title || ''}${alert.message || ''}`;
      return !alert.read && text.includes('止损');
    }).length);
    const staleStrategyCount = computed(() => gridStrategies.value.filter((strategy) => {
      if (!strategy.lastBacktestAt) return true;
      return Date.now() - new Date(strategy.lastBacktestAt).getTime() > 36 * 60 * 60 * 1000;
    }).length);
    const latestStrategyMetrics = computed(() => gridStrategies.value.find((strategy) => strategy.latestMetrics)?.latestMetrics || null);
```

Expose these values from `setup()`.

- [x] **Step 4: Replace the overview summary with the approved hierarchy**

In `frontend/index.html`, retain the existing market chart and watchlist, but place this status strip and workflow section before them:

```html
<div class="desk-status-grid">
  <section class="desk-status"><span>市场状态</span><strong>{{ breadth.up >= breadth.down ? '偏强' : '偏弱' }}</strong><small>上涨 {{ breadth.up }} · 下跌 {{ breadth.down }}</small></section>
  <section class="desk-status"><span>候选标的</span><strong>{{ filteredRows.length }}</strong><small>{{ presetName }}</small></section>
  <section class="desk-status"><span>运行中策略</span><strong>{{ gridStrategies.filter(item => item.status === '启用').length }}</strong><small>{{ staleStrategyCount }} 个待复核</small></section>
  <section class="desk-status desk-status-risk"><span>待处理提醒</span><strong>{{ unreadAlerts }}</strong><small>含 {{ stopAlertCount }} 个止损信号</small></section>
</div>
<div class="desk-workflows">
  <section class="desk-workflow"><h3>发现机会</h3><p>{{ filteredRows.length }} 只标的通过 {{ presetName }} 初筛。</p><button class="button button-primary" type="button" @click="switchView('screener')">打开选股器</button></section>
  <section class="desk-workflow"><h3>验证策略</h3><p v-if="latestStrategyMetrics">最近样本外超额 {{ formatPct(latestStrategyMetrics.excessReturnPct) }}</p><p v-else>还没有可比较的策略结果。</p><button class="button button-secondary" type="button" @click="switchView('grid')">继续策略研究</button></section>
  <section class="desk-workflow"><h3>执行跟踪</h3><p>{{ stopAlertCount ? `${stopAlertCount} 个止损信号需要优先处理。` : `${unreadAlerts} 条提醒待处理。` }}</p><button class="button button-primary" type="button" @click="switchView('monitor')">处理提醒</button></section>
</div>
```

- [x] **Step 5: Add restrained operational styles**

Add:

```css
.desk-status-grid {
  display: grid;
  grid-template-columns: 1.35fr repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 10px;
}

.desk-status,
.desk-workflow {
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
}

.desk-status span,
.desk-status small {
  display: block;
  color: var(--muted);
  font-size: 10px;
}

.desk-status strong {
  display: block;
  margin: 5px 0 3px;
  color: var(--ink);
  font-size: 22px;
}

.desk-status-risk strong { color: var(--red); }

.desk-workflows {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.desk-workflow {
  display: grid;
  min-height: 150px;
  align-content: start;
}

.desk-workflow h3 { margin: 0; font-size: 14px; }
.desk-workflow p { min-height: 36px; color: var(--muted); font-size: 11px; line-height: 1.55; }
.desk-workflow .button { align-self: end; justify-self: start; }
```

- [x] **Step 6: Run static, syntax, and backend tests**

Run:

```powershell
python -m pytest tests/test_frontend_contract.py -v
node --check frontend/app.js
python -m pytest -q
```

Expected: all commands PASS.

- [x] **Step 7: Commit the unified desk**

```powershell
git add frontend/app.js frontend/index.html frontend/styles.css tests/test_frontend_contract.py
git commit -m "feat: add unified trading desk overview"
```

### Task 5: Render the Quantitative Backtest Report

**Files:**
- Modify: `frontend/app.js:120-175,1020-1040`
- Modify: `frontend/index.html:469-486`
- Modify: `frontend/styles.css:1880-2300`
- Modify: `tests/test_frontend_contract.py`

- [x] **Step 1: Add failing report contracts**

Append:

```python
def test_grid_report_exposes_comparison_and_robustness_sections():
    for text in ("持有基准", "超额收益", "年化波动", "夏普比率", "稳健性检查", "模型边界"):
        assert text in HTML
    assert "comparisonChartSvg" in JS
    assert ".backtest-report" in CSS
```

- [x] **Step 2: Verify the new contract fails**

Run `python -m pytest tests/test_frontend_contract.py::test_grid_report_exposes_comparison_and_robustness_sections -v`.

Expected: FAIL on the first missing label.

- [x] **Step 3: Add a two-series SVG formatter**

Add beside `chartSvg` in `frontend/app.js`:

```javascript
function comparisonChartSvg(strategyCurve, benchmarkCurve) {
  const rows = (strategyCurve || []).map((point, index) => ({
    date: point.date,
    strategy: Number(point.value),
    benchmark: Number(benchmarkCurve?.[index]?.value)
  })).filter((point) => Number.isFinite(point.strategy) && Number.isFinite(point.benchmark));
  if (rows.length < 2) return '<div class="chart-empty">暂无足够的权益曲线</div>';
  const width = 720, height = 180, pad = 12;
  const values = rows.flatMap((point) => [point.strategy, point.benchmark]);
  const min = Math.min(...values), max = Math.max(...values), span = Math.max(max - min, 0.001);
  const points = (key) => rows.map((point, index) => {
    const x = pad + index * (width - pad * 2) / (rows.length - 1);
    const y = height - pad - (point[key] - min) * (height - pad * 2) / span;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="策略与持有基准权益曲线"><polyline class="equity-line strategy" points="${points('strategy')}"></polyline><polyline class="equity-line benchmark" points="${points('benchmark')}"></polyline></svg>`;
}
```

Expose `comparisonChartSvg` from `setup()`.

- [x] **Step 4: Replace the four-metric result block**

Replace the `v-if="gridResult"` body with:

```html
<div v-if="gridResult" class="backtest-report">
  <div class="backtest-meta">
    <strong>{{ gridInstrument?.name || gridResult.code }} · {{ gridDraft.mode === 'trend' ? '趋势网格' : '经典网格' }}</strong>
    <span>{{ gridResult.dataWindow.startDate }} 至 {{ gridResult.dataWindow.endDate }} · {{ gridResult.dataWindow.tradingDays }} 个交易日 · {{ gridResult.dataWindow.adjustment }} · {{ gridResult.dataWindow.provider }}</span>
  </div>
  <div class="backtest-metrics">
    <div><span>策略收益</span><strong :class="trendClass(gridResult.metrics.returnPct)">{{ formatPct(gridResult.metrics.returnPct) }}</strong></div>
    <div><span>持有基准</span><strong>{{ formatPct(gridResult.metrics.benchmarkReturnPct) }}</strong></div>
    <div><span>超额收益</span><strong :class="trendClass(gridResult.metrics.excessReturnPct)">{{ formatPct(gridResult.metrics.excessReturnPct) }}</strong></div>
    <div><span>最大回撤</span><strong>{{ gridResult.metrics.maxDrawdownPct.toFixed(2) }}%</strong></div>
    <div><span>年化波动</span><strong>{{ gridResult.metrics.annualizedVolatilityPct == null ? '--' : `${gridResult.metrics.annualizedVolatilityPct.toFixed(2)}%` }}</strong></div>
    <div><span>夏普比率</span><strong>{{ gridResult.metrics.sharpeRatio == null ? '--' : gridResult.metrics.sharpeRatio.toFixed(2) }}</strong></div>
  </div>
  <div class="equity-comparison" v-html="comparisonChartSvg(gridResult.equityCurve, gridResult.benchmarkCurve)"></div>
  <div class="backtest-detail-grid">
    <div><span>成交次数</span><strong>{{ gridResult.metrics.tradeCount }}</strong></div>
    <div><span>总费用</span><strong>{{ formatMoney(gridResult.metrics.totalFees) }}</strong></div>
    <div><span>换手倍数</span><strong>{{ gridResult.metrics.turnoverRatio.toFixed(2) }}</strong></div>
  </div>
  <p class="model-boundary">{{ gridResult.assumptions }} 日线无法还原盘口排队、部分成交和市场冲击；结果仅用于策略研究。</p>
</div>
```

In the candidate table render `candidate.metrics.excessReturnPct` and:

```html
<span :class="['quality-badge', { 'is-warning': !candidate.quality.recommended }]">
  {{ candidate.quality.recommended ? '推荐' : candidate.quality.warnings.join(' · ') }}
</span>
```

- [x] **Step 5: Add report styles and candidate warning states**

Add:

```css
.backtest-report { display: grid; gap: 12px; }
.backtest-meta { display: grid; gap: 3px; }
.backtest-meta span { color: var(--muted); font-size: 10px; }
.backtest-metrics { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 7px; }
.backtest-metrics > div,
.backtest-detail-grid > div { padding: 10px; border: 1px solid var(--line); border-radius: 5px; background: var(--surface-soft); }
.backtest-metrics span,
.backtest-detail-grid span { display: block; margin-bottom: 5px; color: var(--muted); font-size: 9px; }
.backtest-metrics strong { font-size: 16px; }
.equity-comparison { min-height: 180px; border-bottom: 1px solid var(--line); }
.equity-comparison svg { display: block; width: 100%; height: 180px; }
.equity-line { fill: none; stroke-width: 2.5; }
.equity-line.strategy { stroke: var(--coral); }
.equity-line.benchmark { stroke: var(--blue); }
.backtest-detail-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 7px; }
.model-boundary { margin: 0; padding: 10px; border-left: 3px solid var(--gold); background: var(--gold-soft); color: var(--muted-strong); font-size: 10px; line-height: 1.55; }
.quality-badge { display: inline-flex; padding: 4px 6px; border-radius: 4px; background: var(--green-soft); color: var(--green); font-size: 9px; }
.quality-badge.is-warning { background: var(--gold-soft); color: var(--gold); }

@media (max-width: 900px) {
  .backtest-metrics { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
```

- [x] **Step 6: Run frontend contracts and syntax checks**

Run:

```powershell
python -m pytest tests/test_frontend_contract.py -v
node --check frontend/app.js
```

Expected: PASS.

- [x] **Step 7: Commit the report UI**

```powershell
git add frontend/app.js frontend/index.html frontend/styles.css tests/test_frontend_contract.py
git commit -m "feat: show trustworthy grid backtest report"
```

### Task 6: Fix Desktop Scrolling and Group Settings

**Files:**
- Modify: `frontend/app.js:230-255,480-535`
- Modify: `frontend/index.html:590-635`
- Modify: `frontend/styles.css:602-664,2687-2730,2930-2965`
- Modify: `tests/test_frontend_contract.py`

- [x] **Step 1: Add failing settings and scroll contracts**

Append:

```python
def test_settings_are_grouped_into_tabs_and_save_tracks_dirty_state():
    for text in ("工作台", "数据获取", "连接状态"):
        assert f">{text}<" in HTML
    assert "settingsDirty" in JS
    assert ".settings-tabs" in CSS


def test_desktop_content_uses_one_vertical_scroll_owner():
    assert ".content-area" in CSS
    assert "position: sticky" in CSS
    assert "overflow-x: auto" in CSS
```

- [x] **Step 2: Verify the contracts fail**

Run `python -m pytest tests/test_frontend_contract.py -v`.

Expected: FAIL on missing settings hooks.

- [x] **Step 3: Add settings tab and dirty state**

In `frontend/app.js` add:

```javascript
    const settingsTab = ref('workspace');
    const settingsSavedSnapshot = ref(JSON.stringify({ ...settingsDraft }));
    const settingsDirty = computed(() => JSON.stringify({ ...settingsDraft }) !== settingsSavedSnapshot.value);
```

After settings load and successful save, set `settingsSavedSnapshot.value = JSON.stringify({ ...settingsDraft })`. Expose all three values.

- [x] **Step 4: Group settings markup**

Add the tablist and group wrapper:

```html
<div class="settings-tabs" role="tablist" aria-label="设置分类">
  <button type="button" role="tab" :aria-selected="settingsTab === 'workspace'" @click="settingsTab = 'workspace'">工作台</button>
  <button type="button" role="tab" :aria-selected="settingsTab === 'data'" @click="settingsTab = 'data'">数据获取</button>
  <button type="button" role="tab" :aria-selected="settingsTab === 'status'" @click="settingsTab = 'status'">连接状态</button>
</div>
<div v-if="settingsTab === 'workspace'" class="settings-group">
  <label class="settings-field-row"><span><strong>工作区名称</strong><small>用于本浏览器工作台</small></span><input v-model.trim="settingsDraft.workspaceName" aria-label="工作区名称"></label>
  <label class="settings-field-row"><span><strong>默认账户资金</strong><small>新建计划和网格策略的参考资金</small></span><span class="number-input"><input v-model.number="settingsDraft.defaultCapital" type="number" min="1000" step="1000" aria-label="默认账户资金"><span>元</span></span></label>
</div>
<div v-else-if="settingsTab === 'data'" class="settings-group">
  <label class="settings-field-row"><span><strong>行情刷新间隔</strong><small>盯盘标的存在时自动刷新</small></span><span class="number-input"><input v-model.number="settingsDraft.refreshInterval" type="number" min="5" max="300" aria-label="行情刷新间隔"><span>秒</span></span></label>
  <label class="settings-field-row"><span><strong>自动故障切换</strong><small>首选来源异常时尝试可用备选来源</small></span><span class="toggle"><input v-model="settingsDraft.fallbackEnabled" type="checkbox"><span class="toggle-track"><span></span></span></span></label>
  <label class="settings-field-row"><span><strong>实时行情来源</strong><small>盘中报价来源</small></span><select v-model="settingsDraft.realtimeSource" aria-label="实时行情来源"><option value="tencent">腾讯公开行情</option></select></label>
  <label class="settings-field-row"><span><strong>历史日线来源</strong><small>用于走势和网格回测</small></span><select v-model="settingsDraft.historySource" aria-label="历史日线来源"><option value="tencent">腾讯公开行情</option><option value="akshare" disabled>AkShare（待安装）</option><option value="tushare" disabled>Tushare（待配置 Token）</option></select></label>
  <label class="settings-field-row"><span><strong>选股指标来源</strong><small>用于候选池估值和量价指标</small></span><select v-model="settingsDraft.screenerSource" aria-label="选股指标来源"><option value="tencent">腾讯公开行情</option><option value="akshare" disabled>AkShare（待安装）</option><option value="tushare" disabled>Tushare（待配置 Token）</option></select></label>
</div>
<div v-else class="settings-group">
  <div v-for="source in dataSources" :key="source.id" class="settings-field-row"><span><strong>{{ source.name }}</strong><small>{{ source.available ? '连接可用' : source.reason || '暂不可用' }}</small></span><span :class="['setting-status', { 'setting-status-muted': !source.available }]">{{ source.available ? '可用' : source.tushareConfigured ? '待安装' : '未配置' }}</span></div>
</div>
```

Bind the save button as:

```html
<button :class="['button', settingsDirty ? 'button-primary' : 'button-secondary']" type="button" :disabled="settingsLoading || !settingsDirty" @click="saveSettings">
  <i data-lucide="save" aria-hidden="true"></i>保存设置
</button>
```

Add:

```css
.settings-tabs { display: flex; gap: 4px; margin-bottom: 12px; border-bottom: 1px solid var(--line); }
.settings-tabs button { padding: 9px 12px; border: 0; border-bottom: 2px solid transparent; background: transparent; color: var(--muted); }
.settings-tabs button[aria-selected="true"] { border-bottom-color: var(--coral); color: var(--ink); }
.settings-group { display: grid; gap: 1px; border: 1px solid var(--line); border-radius: 6px; overflow: hidden; }
.settings-field-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(180px, 280px); align-items: center; gap: 20px; padding: 16px 18px; border-bottom: 1px solid var(--line); background: var(--surface); }
.settings-field-row:last-child { border-bottom: 0; }
```

- [x] **Step 5: Replace nested desktop scrolling**

Update desktop CSS so `.content-area` owns vertical scrolling:

```css
.content-area { overflow-x: hidden; overflow-y: auto; }
.view-panel.is-active { overflow: visible; }
.screener-view { display: block !important; overflow: visible !important; }
.screener-view .screener-layout { height: auto; }
.screener-view .filter-panel { align-self: start; overflow: visible; position: sticky; top: 0; }
.screener-view .results-table-wrap { overflow-x: auto; overflow-y: visible; }
```

Remove the fixed screener grid rows and panel `overflow-y: auto`. Preserve table horizontal scrolling.

- [x] **Step 6: Run contracts, syntax, and full tests**

Run `python -m pytest tests/test_frontend_contract.py -v`, `node --check frontend/app.js`, and `python -m pytest -q`.

Expected: all PASS.

- [x] **Step 7: Commit desktop and settings changes**

```powershell
git add frontend/app.js frontend/index.html frontend/styles.css tests/test_frontend_contract.py
git commit -m "feat: simplify desktop flow and settings"
```

### Task 7: Add Labeled Mobile Navigation

**Files:**
- Modify: `frontend/app.js:55-75,930-940,1086-1180`
- Modify: `frontend/index.html:20-80,490-590,635-650`
- Modify: `frontend/styles.css:2972-3150`
- Modify: `tests/test_frontend_contract.py`

- [x] **Step 1: Add a failing mobile navigation contract**

Append:

```python
def test_mobile_navigation_has_visible_labels_and_execution_group():
    assert 'class="mobile-nav"' in HTML
    for label in ("总览", "选股", "网格", "执行", "更多"):
        assert f"label: '{label}'" in JS
    assert "<span>{{ item.label }}</span>" in HTML
    assert 'class="execution-tabs"' in HTML
    assert ".mobile-nav" in CSS
```

- [x] **Step 2: Verify the contract fails**

Run `python -m pytest tests/test_frontend_contract.py::test_mobile_navigation_has_visible_labels_and_execution_group -v`.

Expected: FAIL because `.mobile-nav` is absent.

- [x] **Step 3: Add mobile navigation data and execution switching**

Add to `frontend/app.js`:

```javascript
const MOBILE_NAV_ITEMS = [
  { id: 'overview', label: '总览', icon: 'layout-dashboard', target: 'overview' },
  { id: 'screener', label: '选股', icon: 'scan-search', target: 'screener' },
  { id: 'grid', label: '网格', icon: 'grid-3x3', target: 'grid' },
  { id: 'execution', label: '执行', icon: 'radar', target: 'monitor' },
  { id: 'more', label: '更多', icon: 'ellipsis', target: 'settings' },
];
```

Expose `mobileNavItems`, and add:

```javascript
    function mobileNavActive(item) {
      if (item.id === 'execution') return ['plans', 'monitor'].includes(view.value);
      return view.value === item.target;
    }
```

- [x] **Step 4: Add semantic mobile markup**

Keep the existing desktop sidebar and add before the toast region:

```html
<nav class="mobile-nav" aria-label="移动端主导航">
  <button v-for="item in mobileNavItems" :key="item.id" type="button" :class="{ 'is-active': mobileNavActive(item) }" @click="switchView(item.target)">
    <i :data-lucide="item.icon" aria-hidden="true"></i><span>{{ item.label }}</span>
  </button>
</nav>
```

Add to the plan and monitor view headings:

```html
<div class="execution-tabs" role="tablist" aria-label="执行工作区">
  <button type="button" role="tab" :aria-selected="view === 'plans'" @click="switchView('plans')">交易计划</button>
  <button type="button" role="tab" :aria-selected="view === 'monitor'" @click="switchView('monitor')">盯盘提醒</button>
</div>
```

- [x] **Step 5: Replace the mobile top navigation CSS**

Add base rules:

```css
.mobile-nav,
.execution-tabs { display: none; }
```

At `max-width: 680px`, replace the top sidebar navigation rules with:

```css
.sidebar { display: none; }
.app-shell { display: block; height: 100dvh; padding-bottom: calc(58px + env(safe-area-inset-bottom)); }
.main-area { height: 100%; }
.content-area { overflow-y: auto; padding: 18px 14px 24px; }
.topbar { gap: 10px; padding: 12px 14px; }
.topbar-context p,
.topbar-eyebrow { display: none; }
.topbar-actions { width: 100%; }
.global-search { flex: 1; width: auto; }
.mobile-nav {
  position: fixed;
  right: 0;
  bottom: 0;
  left: 0;
  z-index: 30;
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  padding: 5px 6px calc(5px + env(safe-area-inset-bottom));
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  background: var(--sidebar);
}
.mobile-nav button { display: grid; min-width: 0; min-height: 44px; place-items: center; gap: 2px; border: 0; background: transparent; color: var(--sidebar-muted); }
.mobile-nav button.is-active { color: #ffffff; }
.mobile-nav svg { width: 17px; height: 17px; }
.mobile-nav span { font-size: 10px; white-space: nowrap; }
.execution-tabs { display: flex; gap: 4px; }
.execution-tabs button { min-height: 34px; padding: 0 10px; border: 1px solid var(--line); border-radius: 5px; background: var(--surface); color: var(--muted); }
.execution-tabs button[aria-selected="true"] { border-color: var(--coral); color: var(--ink); }
```

- [x] **Step 6: Run contracts and syntax checks**

Run:

```powershell
python -m pytest tests/test_frontend_contract.py -v
node --check frontend/app.js
```

Expected: PASS.

- [x] **Step 7: Commit mobile usability changes**

```powershell
git add frontend/app.js frontend/index.html frontend/styles.css tests/test_frontend_contract.py
git commit -m "feat: add labeled mobile trading navigation"
```

### Task 8: End-to-End Verification and Documentation

**Files:**
- Modify: `README.md`
- Modify: `frontend/index.html` asset version query strings

- [x] **Step 1: Update the user-facing capability summary**

Add to the grid strategy paragraph in `README.md`:

```markdown
回测报告同时展示买入持有基准、超额收益、最大回撤、年化波动、夏普比率、交易成本与换手；参数优化以样本外超额收益、回撤和训练/验证稳定性共同排序，并明确披露日线固定路径假设。
```

- [x] **Step 2: Bump static asset versions**

Update the `styles.css` and `app.js` query strings in `frontend/index.html` to one shared new version such as `v=20260809-4` so browsers load the changed assets.

- [x] **Step 3: Run complete automated verification**

Run:

```powershell
python -m pytest -q
node --check frontend/app.js
git diff --check
```

Expected: all tests PASS, JavaScript syntax succeeds, and `git diff --check` prints nothing.

- [x] **Step 4: Start the local app and verify API health**

Run `python server.py` on an available local port, then verify `/api/health`, `/api/grid/backtest`, and `/api/grid/optimize` return 200 responses with the additive metrics and quality fields.

- [x] **Step 5: Perform browser visual QA**

Using the in-app browser, capture and inspect these views at 1280×720 and 1440×900: today desk, screener, grid report, plans, monitor, and all three settings tabs. Repeat core navigation at 390×844.

Acceptance criteria:

- No incoherent overlap or unexpected page-level horizontal overflow.
- The screener has one vertical scroll owner; its table may scroll horizontally.
- Desktop primary actions remain visible without internal panel scrolling.
- Mobile bottom navigation shows all five labels and indicates the active group.
- Grid comparison chart is nonblank and both strategy and benchmark lines render.
- Missing risk metrics display `--`, never `NaN` or misleading zeroes.
- Real-time, cached, historical, and validation states use distinct text.

- [x] **Step 6: Commit documentation and asset versions**

```powershell
git add README.md frontend/index.html
git commit -m "docs: describe trustworthy grid research workflow"
```

- [x] **Step 7: Review the final change set**

Run:

```powershell
git status --short
git log --oneline -8
```

Expected: clean worktree and one focused commit per task group.
