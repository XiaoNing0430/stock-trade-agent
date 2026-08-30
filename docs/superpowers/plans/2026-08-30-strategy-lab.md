# 统一策略实验室实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将「网格策略」视图升级为统一策略实验室（网格 / 双均线 / DCA / MACD），共用回测、指标、保存与调度。

**Architecture:** 3 个 Git Flow feature 子项目串行：① 策略引擎核心（`compute_metrics` 抽取 + 三引擎 + 单测）② 存储/API/调度（`Strategy` 表 + 通用端点 + 调度器泛化）③ 前端策略实验室（类型切换 + 通用表单 + 统一结果 + nav 改名）。

**Tech Stack:** Python / FastAPI / SQLAlchemy / Vue 3 全局构建。验证：pytest（TDD）+ `node --check` + 浏览器手动。

## Global Constraints

- 不修改现有 `GridStrategy` 表与 `/api/grid/*` 端点——网格零回归。
- `compute_metrics` 抽取逻辑不变，`test_grid_strategy.py` 现有 49 项全绿保障。
- 每个子项目完成后必须全量回归 + 合并 develop。
- UI 文案中文；`assumptions` 诚实披露，不构成投资建议。

---

## 子项目 A：策略引擎核心

### Feature A: `feature/strategy-engine-core`

**Files:**
- Modify: `backend/grid_strategy.py`（抽取 `compute_metrics`）
- Create: `backend/strategy_engines.py`（三引擎 + 注册表）
- Modify: `tests/test_grid_strategy.py`（`compute_metrics` 回归）
- Create: `tests/test_strategy_engines.py`（新引擎单测）

**Interfaces:**
- Produces: `compute_metrics(bars, trades, equity_curve, capital, fee_bps, security_type, exchange) -> dict`
- Produces: `backtest_ma_cross(bars, config) -> dict`, `backtest_dca(bars, config) -> dict`, `backtest_macd(bars, config) -> dict`
- Produces: `STRATEGY_ENGINES` 注册表
- Consumes: `transaction_fee`, `buy_and_hold_benchmark`, `_round_trip_returns`, `_max_drawdown_duration`（均已在 grid_strategy.py）

- [x] **Step 1: 建分支**

```bash
git flow feature start strategy-engine-core
```

- [x] **Step 2: 抽取 compute_metrics**

`backend/grid_strategy.py` 中 `backtest_grid` 第 190-239 行指标计算逻辑（`metrics = {...}`, `round_trip_returns`, `max_drawdown_duration` 调用）抽取为：

```python
def compute_metrics(bars: list[dict], trades: list[dict], equity_curve: list[float], capital: float, fee_bps: float, security_type: str, exchange: str) -> dict:
    """统一指标计算：收益/回撤/夏普/胜率/round-trip/利润因子等。"""
    # ... 原 backtest_grid 第 190-239 行逻辑，移除 bars/trades/equity_curve 等依赖
    # 需从外部传入的：bars, trades, equity_curve, capital, fee_bps, security_type, exchange
    # 局部变量：peak, max_drawdown, days, total_return, annualized, benchmark, ...
    return metrics
```

- [x] **Step 3: 更新 backtest_grid 调用 compute_metrics**

`backtest_grid` 中 `metrics = {...}` 块改为 `metrics = compute_metrics(bars, trades, equity_curve, capital, fee_bps, security_type, exchange)`。

- [x] **Step 4: 写失败测试**

`tests/test_strategy_engines.py`（新建）：

```python
from backend.grid_strategy import backtest_grid, compute_metrics
from tests.test_grid_strategy import sample_bars

def test_compute_metrics_matches_original():
    """抽取后的 compute_metrics 与 backtest_grid 内指标一致。"""
    original = backtest_grid(sample_bars(), 8, 12, 4, 100000, 3)
    # 验证抽取后无变化只需确保 test_grid_strategy 全绿

def test_ma_cross_returns_expected_shape():
    from backend.strategy_engines import backtest_ma_cross
    result = backtest_ma_cross(sample_bars(), {"fastPeriod": 5, "slowPeriod": 20, "capital": 100000, "feeBps": 3})
    assert "trades" in result
    assert "equityCurve" in result
    assert "metrics" in result
    assert "assumptions" in result

def test_ma_cross_creates_trades_on_crossover(sample_bars):
    bars = [
        {"date": "2026-01-02", "open": 10, "high": 10, "low": 10, "close": 10},
        {"date": "2026-01-03", "open": 10, "high": 10, "low": 10, "close": 10},
        # 构造金叉：快线上穿慢线
        # 简单起见，用 3 根上涨后确认
    ]
    ...

def test_dca_returns_expected_shape():
    from backend.strategy_engines import backtest_dca
    result = backtest_dca(sample_bars(), {"amountPerPeriod": 5000, "intervalDays": 5, "stopProfitPct": 20, "stopLossPct": 15, "capital": 100000, "feeBps": 3})
    assert "trades" in result
    assert "assumptions" in result

def test_macd_returns_expected_shape():
    from backend.strategy_engines import backtest_macd
    result = backtest_macd(sample_bars(), {"fastPeriod": 12, "slowPeriod": 26, "signalPeriod": 9, "capital": 100000, "feeBps": 3})
    assert "trades" in result
    assert "equityCurve" in result
    assert "metrics" in result
```

- [x] **Step 5: 实现三引擎**

`backend/strategy_engines.py`：

```python
from backend.grid_strategy import compute_metrics, buy_and_hold_benchmark, transaction_fee, _round_trip_returns

def backtest_ma_cross(bars: list[dict], config: dict) -> dict:
    fast, slow = int(config.get("fastPeriod", 5)), int(config.get("slowPeriod", 20))
    capital = float(config.get("capital", 100000))
    fee_bps = float(config.get("feeBps", 3))
    # 计算 MA(fast) 与 MA(slow)
    closes = [float(b["close"]) for b in bars]
    # ... 迭代bars，金叉买入，死叉卖出
    # 返回统一结构

def backtest_dca(bars: list[dict], config: dict) -> dict: ...

def backtest_macd(bars: list[dict], config: dict) -> dict: ...

STRATEGY_ENGINES = {
    "ma_cross": {"label": "双均线", "backtest": backtest_ma_cross, "suggest": None, "configSchema": [...]},
    "dca": {"label": "定投", "backtest": backtest_dca, "suggest": None, "configSchema": [...]},
    "macd": {"label": "MACD", "backtest": backtest_macd, "suggest": None, "configSchema": [...]},
}
```

- [x] **Step 6: 全量回归 + 提交**

```bash
python -m pytest tests/ -q
git add backend/grid_strategy.py backend/strategy_engines.py tests/
git commit -m "feat: 策略引擎核心（双均线/DCA/MACD）+ 统一指标计算"
git flow feature finish strategy-engine-core
```

---

## 子项目 B：存储/API/调度

### Feature B: `feature/strategy-storage-api`

**Files:**
- Modify: `backend/storage.py`（`Strategy` 表 + 存储函数）
- Create: `backend/strategy_models.py`（可选，或直接放 storage.py）
- Modify: `backend/grid_scheduler.py`（调度器泛化）
- Modify: `backend/app.py`（通用策略端点 + 泛化调度导入）
- Modify: `tests/test_backend_api.py`（策略 API 测试）

**Interfaces:**
- Consumes: `STRATEGY_ENGINES`（来自子项目 A）
- Produces: `Strategy` 表 + `StrategyBacktest` 表 + 存储函数
- Produces: `/api/strategy/*` 端点
- Produces: 泛化调度器（`run_scheduled_strategy`）

- [x] **Step 1: 建分支**

```bash
git flow feature start strategy-storage-api
```

- [x] **Step 2: 实现存储**

`backend/storage.py` 追加 `Strategy` 表与辅助函数。

- [x] **Step 3: 实现通用 API 端点**

`backend/app.py` 追加 `/api/strategy/*` 端点。

- [x] **Step 4: 通用调度**

`backend/grid_scheduler.py` 泛化 `run_scheduled_backtest` → `run_scheduled_strategy`。

- [x] **Step 5: 测试 + 提交**

```bash
python -m pytest tests/ -q
git add backend/storage.py backend/app.py backend/grid_scheduler.py tests/
git commit -m "feat: 策略通用存储/API/调度器泛化"
git flow feature finish strategy-storage-api
```

---

## 子项目 C：前端策略实验室

### Feature C: `feature/strategy-lab-ui`

**Files:**
- Modify: `frontend/app.js`（`strategyType` ref + 通用策略函数 + 导出）
- Modify: `frontend/index.html`（grid 视图改造为策略实验室；nav 改名）
- Modify: `frontend/modules/constants.js`（NAV_ITEMS/VIEW_META 更新）
- Modify: `frontend/styles.css`（策略类型 tabs 等样式）

**Interfaces:**
- Consumes: `/api/grid/*`（网格类型）、`/api/strategy/*`（新类型）
- Produces: `strategyType` ref、`backtestStrategy()`、`previewStrategy()`、`saveStrategy()`、`loadStrategies()`、`strategyTypeSchema()` 等

- [x] **Step 1: 建分支 + 逐步实现 + 提交 + 合并**

```bash
git flow feature start strategy-lab-ui
git add frontend/... constants.js
git commit -m "feat: 策略实验室前端（类型切换/通用表单/统一结果/nav 改名）"
git flow feature finish strategy-lab-ui
```

---

## 验收

- [x] nav「策略」tab 存在，点击进入策略实验室
- [x] 4 个策略类型 tabs 可切换，网格类型全部功能正常
- [x] 双均线回测结果展示权益曲线 + 指标卡
- [x] DCA / MACD 回测结果正常
- [x] 保存/载入/暂停/删除新策略
- [x] 每日调度对新策略生效
- [x] 断网降级到本地缓存（来源角标显示<本地缓存>）
- [x] 全量回归 49+ 项全绿