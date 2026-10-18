# 多策略回测对比 + CSV 导出 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 ViewGrid 新增「对比」tab：同标的多策略类型横向对比 + 已保存策略对比（快照/现跑），对比结果可导出指标/曲线/成交三张 CSV。

**Architecture:** 后端两个无状态只读端点（`/api/strategy/compare` 同 bars 一次取数重放；`/api/strategy/compare-saved` 读库快照 + 现跑，零写库）；前端新模块 `csv.ts`（含公式注入防护）+ 第 13 个 Pinia store `useCompareStore`，曲线叠图复用现成 `multiLineSvg`。

**Tech Stack:** FastAPI + Pydantic v2（后端）；Vue 3 + Pinia + vitest（前端）；pytest（后端测试）。

**Spec:** `docs/superpowers/specs/2026-10-11-strategy-compare-csv-design.md`（已评审通过）

## Global Constraints

- 当前分支 `feature/strategy-compare-csv-export`（Git Flow，已建好），所有提交直接在该分支。
- 用户可见字符串全部中文；错误一律 `api_error(status, code, 中文消息)` → `{"detail": {"error", "code"}}`；Pydantic 校验失败由 app 级 handler 自动转中文契约。
- **既有 API 字段名零改名**；新增字段可接受。
- **零写库红线**：compare / compare-saved 两端点不得调用 `save_grid_strategy` / `save_strategy` / `save_grid_backtest` / `save_strategy_backtest` / `schedule_strategy`（测试断言）。
- compare 端点 `_load_history_with_fallback` **只调 1 次**；trades **不截断**（与单策略端点的 `[-100:]` 有意不同）。
- 响应模型字段名与 spec §3.1/§3.2 逐字一致。
- XSS 纪律：`v-html` 仅限 `chart.ts` 输出（内建 `escapeHtml`）；toast 保持 `textContent`；CSV 单元格过 `csvCell` 公式注入防护。
- 测试一律离线：后端 monkeypatch `app_module._load_history_with_fallback` 等；前端 stub 全局 `fetch`。
- 提交信息：中文主题 + Conventional Commits 前缀。
- 文案口径：网格脚注固定文案「网格区间为样本内自动建议，结果偏乐观」（警示样式 `signal-chip-watch`）。

---

### Task 1: 后端 `/api/strategy/compare` 端点 + schemas

**Files:**
- Modify: `backend/schemas.py`（文件末尾追加模型）
- Modify: `backend/app.py`（导入、常量、helper、新端点）
- Create: `tests/test_strategy_compare.py`

**Interfaces:**
- Consumes: `_load_history_with_fallback(code, limit)` → `(history, dataSource, dataAsOf, provider)`；`backtest_grid` / `suggest_grid` / `buy_and_hold_benchmark`（`backend.grid_strategy`）；`STRATEGY_ENGINES[type]["backtest"](bars, config)` 与 `["configSchema"]`、`["label"]`；`classify_code` / `price_limit_ratio`（`backend.data_source`）。
- Produces: `POST /api/strategy/compare` 响应 `{code, profile, dataSource, dataAsOf, barCount, benchmarkCurve, results: [{strategyType, label, config, metrics, equityCurve, trades, assumptions, error}] | [{strategyType, label, error}]}`；schemas 模型 `CompareRunIn` / `CompareRunOut`（Task 2 复用同文件追加模式）。

- [ ] **Step 1: 写失败测试**

创建 `tests/test_strategy_compare.py`：

```python
"""多策略回测对比端点：同 bars 重放 / 白名单上界 / 部分失败隔离 / trades 不截断 / 一次取数。"""

import pytest
from backend import app as app_module
from backend.strategy_engines import STRATEGY_ENGINES
from fastapi.testclient import TestClient


def _bars(count=120, start=100.0):
    """确定性日线序列（先跌后涨再回落），保证多数策略可产生成交。"""
    bars = []
    for i in range(count):
        progress = i / max(1, count - 1)
        if progress < 0.4:
            factor = 1 - (progress / 0.4) * 0.3
        elif progress < 0.7:
            factor = 0.7 + ((progress - 0.4) / 0.3) * 0.6
        else:
            factor = 1.3 - ((progress - 0.7) / 0.3) * 0.6
        close = round(start * factor, 2)
        bars.append(
            {
                "date": f"2026-{1 + i // 28:02d}-{1 + i % 28:02d}",
                "open": close,
                "high": close,
                "low": close,
                "close": close,
                "volume": 10000,
            }
        )
    return bars


ALL_TYPES = ["grid", *STRATEGY_ENGINES.keys()]


def _patch_history(monkeypatch, bars):
    calls = {"count": 0, "limit": None}

    def fake_load(code, limit, is_index=False):
        calls["count"] += 1
        calls["limit"] = limit
        return bars, "tencent", bars[-1]["date"], "tencent"

    monkeypatch.setattr(app_module, "_load_history_with_fallback", fake_load)
    return calls


def test_compare_runs_all_types_on_shared_bars(monkeypatch):
    bars = _bars()
    calls = _patch_history(monkeypatch, bars)
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/compare",
            json={"code": "600519", "lookback": 120, "capital": 100000, "feeBps": 3, "strategyTypes": ALL_TYPES},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["dataSource"] == "tencent"
    assert data["barCount"] == len(bars)
    assert data["benchmarkCurve"][0]["date"] == bars[0]["date"]
    assert len(data["results"]) == len(ALL_TYPES)
    by_type = {item["strategyType"]: item for item in data["results"]}
    assert set(by_type) == set(ALL_TYPES)
    # grid：自动建议区间 + 默认 8 格 classic
    grid = by_type["grid"]
    assert grid["error"] is None
    assert grid["config"]["gridCount"] == 8
    assert grid["config"]["mode"] == "classic"
    assert 0 < grid["config"]["lower"] < grid["config"]["upper"]
    # 引擎：schema 默认参数补齐
    assert by_type["ma_cross"]["config"]["fastPeriod"] == 5
    assert by_type["ma_cross"]["config"]["slowPeriod"] == 20
    for item in data["results"]:
        assert set(item) == {"strategyType", "label", "config", "metrics", "equityCurve", "trades", "assumptions", "error"}
        assert "benchmarkCurve" not in item  # 顶层仅一份
    # 一次上游取数
    assert calls["count"] == 1
    assert calls["limit"] == 120


def test_compare_whitelist_and_bounds(monkeypatch):
    bars = _bars()
    _patch_history(monkeypatch, bars)
    with TestClient(app_module.create_app()) as client:
        resp_unknown = client.post(
            "/api/strategy/compare",
            json={"code": "600519", "strategyTypes": ["grid", "nope"]},
        )
        resp_empty = client.post("/api/strategy/compare", json={"code": "600519", "strategyTypes": []})
        resp_dup = client.post(
            "/api/strategy/compare",
            json={"code": "600519", "strategyTypes": ["grid", "grid", "grid"]},
        )
        resp_capital = client.post(
            "/api/strategy/compare", json={"code": "600519", "capital": 0, "strategyTypes": ["grid"]}
        )
        resp_lookback = client.post(
            "/api/strategy/compare", json={"code": "600519", "lookback": 500, "strategyTypes": ["grid"]}
        )
    assert resp_unknown.status_code == 422
    body = resp_unknown.json()["detail"]
    assert body["code"] == "VALIDATION_ERROR"
    assert "nope" in body["error"]
    assert resp_empty.status_code == 422
    assert resp_dup.status_code == 200  # 去重保序，不报错
    assert len(resp_dup.json()["results"]) == 1
    assert resp_capital.status_code == 422
    # lookback clamp 20..240
    assert resp_lookback.status_code == 200
    assert resp_lookback.json()["barCount"] <= 240


def test_compare_partial_failure_isolated(monkeypatch):
    bars = _bars()

    def _boom(bars_, config):
        raise ValueError("引擎炸了")

    monkeypatch.setitem(
        STRATEGY_ENGINES, "macd", {**STRATEGY_ENGINES["macd"], "backtest": _boom}
    )
    _patch_history(monkeypatch, bars)
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/compare",
            json={"code": "600519", "strategyTypes": ALL_TYPES},
        )
    assert resp.status_code == 200
    by_type = {item["strategyType"]: item for item in resp.json()["results"]}
    assert "回测失败" in by_type["macd"]["error"]
    assert by_type["ma_cross"]["error"] is None


def test_compare_trades_not_truncated(monkeypatch):
    bars = _bars()
    fake_result = {
        "trades": [
            {"date": f"2026-01-{i % 28 + 1:02d}", "side": "buy", "triggerPrice": None, "price": 100.0, "shares": 100, "fee": 5.0, "module": None}
            for i in range(150)
        ],
        "equityCurve": [{"date": b["date"], "equity": 1.0} for b in bars],
        "benchmarkCurve": [{"date": b["date"], "equity": 1.0} for b in bars],
        "metrics": {"tradeCount": 150},
        "assumptions": "测试",
    }
    monkeypatch.setitem(
        STRATEGY_ENGINES,
        "momentum",
        {**STRATEGY_ENGINES["momentum"], "backtest": lambda bars_, config: fake_result},
    )
    _patch_history(monkeypatch, bars)
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/compare",
            json={"code": "600519", "strategyTypes": ["momentum"]},
        )
    assert resp.status_code == 200
    assert len(resp.json()["results"][0]["trades"]) == 150
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_strategy_compare.py -v`
Expected: FAIL（`CompareRunIn` 不存在 / 404 Not Found）

- [ ] **Step 3: 实现 schemas**

在 `backend/schemas.py` 文件末尾追加：

```python
class CompareResultItem(BaseModel):
    """单策略对比项；error 行仅有 strategyType/label/error。"""

    model_config = ConfigDict(extra="ignore")

    strategyType: str
    label: str = ""
    config: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    equityCurve: list[dict[str, Any]] | None = None
    trades: list[dict[str, Any]] | None = None
    assumptions: str | None = None
    error: str | None = None


class CompareRunIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    lookback: int = 120
    capital: float = Field(default=100000, gt=0)
    feeBps: float = Field(default=3, ge=0)
    strategyTypes: list[str] = Field(default_factory=list)


class CompareRunOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    profile: dict[str, Any] = Field(default_factory=dict)
    dataSource: str
    dataAsOf: str | None = None
    barCount: int = 0
    benchmarkCurve: list[dict[str, Any]] = Field(default_factory=list)
    results: list[CompareResultItem] = Field(default_factory=list)
```

- [ ] **Step 4: 实现端点**

`backend/app.py` 修改四处：

(a) `backend.grid_strategy` 导入行追加 `buy_and_hold_benchmark`：

```python
from backend.grid_strategy import backtest_grid, buy_and_hold_benchmark, optimize_grid, suggest_grid
```

(b) `backend.schemas` 导入块追加 `CompareRunIn,` `CompareRunOut,`（按字母序放在 `CustomStrategyIn,` 之后、`DeleteOut,` 之前——`C` 段）。

(c) 模块级常量与 helper（放在 `logger = logging.getLogger("atlas.assist")` 一组日志器之后，与 `_VALIDATION_TYPE_LABELS` 之前的模块级区域）：

```python
compare_logger = logging.getLogger("atlas.compare")  # 多策略对比端点结构化日志（2026-10-11 spec §3.7）
_COMPARE_ALLOWED_TYPES = {"grid", *STRATEGY_ENGINES.keys()}


def _compare_label(strategy_type: str) -> str:
    return "网格" if strategy_type == "grid" else str(STRATEGY_ENGINES[strategy_type]["label"])


def _engine_default_config(engine: dict[str, Any]) -> dict[str, Any]:
    """按 configSchema 的 default 生成引擎默认参数（与 /api/strategy/preview 补齐逻辑一致）。"""
    return {field["key"]: field.get("default") for field in engine["configSchema"]}
```

(d) 新端点（插在 `strategy_backtest` 端点之后、`@app.get("/api/strategy/strategies")` 之前）：

```python
    @app.post("/api/strategy/compare")
    def strategy_compare(payload: CompareRunIn) -> CompareRunOut:
        """同标的横向对比：一次取数，同一份 bars 重放全部勾选策略（只读，零写库）。"""
        started = time.monotonic()
        try:
            code = payload.code
            profile = classify_code(code)
            lookback = max(20, min(payload.lookback, 240))
            # 白名单 + 去重保序（≤8 由白名单与去重结构性保证，无需独立检查）
            seen: list[str] = []
            for strategy_type in payload.strategyTypes:
                if strategy_type not in _COMPARE_ALLOWED_TYPES:
                    raise api_error(422, ERR_VALIDATION_ERROR, f"未知策略类型：{strategy_type}")
                if strategy_type not in seen:
                    seen.append(strategy_type)
            if not seen:
                raise api_error(422, ERR_VALIDATION_ERROR, "至少勾选一个策略类型")
            history, data_source_flag, data_as_of, _ = _load_history_with_fallback(code, lookback)
            limit_pct = price_limit_ratio(code)
            benchmark_curve = buy_and_hold_benchmark(
                history, payload.capital, payload.feeBps, profile["securityType"], profile["exchange"]
            )["curve"]
            results: list[dict[str, Any]] = []
            failed_types: list[str] = []
            for strategy_type in seen:
                try:
                    if strategy_type == "grid":
                        suggestion = suggest_grid(history, 8, payload.capital, "classic")
                        result = backtest_grid(
                            history,
                            suggestion["lower"],
                            suggestion["upper"],
                            8,
                            payload.capital,
                            payload.feeBps,
                            "classic",
                            profile["securityType"],
                            profile["exchange"],
                            1,
                            5,
                            limit_pct,
                        )
                        config = {
                            "lower": suggestion["lower"],
                            "upper": suggestion["upper"],
                            "gridCount": 8,
                            "mode": "classic",
                            "capital": payload.capital,
                            "feeBps": payload.feeBps,
                            "lookback": lookback,
                            "settlementDays": 1,
                            "slippageBps": 5,
                            "priceLimitPct": limit_pct * 100,
                            "rangeMode": "auto",
                        }
                    else:
                        engine = STRATEGY_ENGINES[strategy_type]
                        config = _engine_default_config(engine)
                        config.update(
                            {
                                "capital": payload.capital,
                                "feeBps": payload.feeBps,
                                "securityType": profile["securityType"],
                                "exchange": profile["exchange"],
                                "lookback": lookback,
                                "capitalAllocation": 1.0,
                            }
                        )
                        result = engine["backtest"](history, config)
                    result.pop("benchmarkCurve", None)  # 基准曲线顶层仅一份
                    results.append(
                        {
                            "strategyType": strategy_type,
                            "label": _compare_label(strategy_type),
                            "config": config,
                            **result,
                            "error": None,
                        }
                    )
                except Exception as exc:  # 单策略失败不拖垮整单（spec §3.1）
                    failed_types.append(strategy_type)
                    results.append(
                        {
                            "strategyType": strategy_type,
                            "label": _compare_label(strategy_type),
                            "error": f"回测失败：{exc}",
                        }
                    )
            compare_logger.info(
                "strategy.compare",
                extra={
                    "code": code,
                    "strategyTypes": seen,
                    "lookback": lookback,
                    "capital": payload.capital,
                    "feeBps": payload.feeBps,
                    "elapsedMs": int((time.monotonic() - started) * 1000),
                    "resultStatus": "partial_failure" if failed_types else "success",
                    "dataSource": data_source_flag,
                    "failedTypes": failed_types,
                },
            )
            return CompareRunOut.model_validate(
                {
                    "code": code,
                    "profile": profile,
                    "dataSource": data_source_flag,
                    "dataAsOf": data_as_of,
                    "barCount": len(history),
                    "benchmarkCurve": benchmark_curve,
                    "results": results,
                }
            )
        except HTTPException:
            raise
        except Exception as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc)) from exc
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_strategy_compare.py -v`
Expected: 4 passed

Run: `python -m ruff check backend tests && python -m mypy backend`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add backend/schemas.py backend/app.py tests/test_strategy_compare.py
git commit -m "feat: 新增 /api/strategy/compare 同标的多策略横向对比端点"
```

---

### Task 2: 后端 `/api/strategy/compare-saved` 端点（snapshot + rerun，零写库）

**Files:**
- Modify: `backend/schemas.py`
- Modify: `backend/app.py`
- Modify: `tests/test_strategy_compare.py`

**Interfaces:**
- Consumes: Task 1 的模式（`api_error` / `compare_logger` / `_load_history_with_fallback`）；`get_grid_strategy(id)` / `get_strategy(id)` → dict | None（含 `workspaceId`、`latestMetrics`、`config` 等，见 `storage._grid_strategy_dict` / `_strategy_dict`）；`backtest_grid` / `STRATEGY_ENGINES`。
- Produces: `POST /api/strategy/compare-saved` 响应 `{rerun: bool, results: [CompareSavedItem]}`——snapshot 项含 `{id, found, source, name, strategyType, code, status, schedule, capital, feeBps, lastBacktestAt, latestMetrics, missingReason}`；rerun 项含 `{id, found, source, name, strategyType, code, config, metrics, trades, assumptions, dataSource, dataAsOf, error}`；缺失项 `{id, found: false, missingReason}`。

- [ ] **Step 1: 写失败测试**

在 `tests/test_strategy_compare.py` 末尾追加：

```python
# ===== compare-saved：快照读库 + 现跑零写库 =====


def _grid_row(**overrides):
    row = {
        "id": "grid-1",
        "workspaceId": "default",
        "code": "600519",
        "name": "网格A",
        "lower": 85.0,
        "upper": 115.0,
        "gridCount": 8,
        "capital": 100000.0,
        "feeBps": 3.0,
        "mode": "classic",
        "lookback": 120,
        "settlementDays": 1,
        "slippageBps": 5,
        "schedule": "manual",
        "status": "启用",
        "nextRunAt": None,
        "lastBacktestAt": "2026-10-10T15:20:00+00:00",
        "latestMetrics": {"returnPct": 5.0, "maxDrawdownPct": 3.0},
        "updatedAt": "2026-10-10T15:20:00+00:00",
    }
    row.update(overrides)
    return row


def _strategy_row(**overrides):
    row = {
        "id": "strategy-1",
        "workspaceId": "default",
        "code": "600519",
        "name": "双均线A",
        "strategyType": "ma_cross",
        "config": {
            "fastPeriod": 5,
            "slowPeriod": 20,
            "capital": 100000,
            "feeBps": 3,
            "lookback": 120,
            "capitalAllocation": 1.0,
            "securityType": "股票",
            "exchange": "上交所",
        },
        "capital": 100000.0,
        "feeBps": 3.0,
        "schedule": "manual",
        "status": "启用",
        "nextRunAt": None,
        "lastBacktestAt": None,
        "latestMetrics": None,
        "updatedAt": "2026-10-10T15:20:00+00:00",
    }
    row.update(overrides)
    return row


def _patch_saved(monkeypatch, grid_rows, strategy_rows):
    def fake_get_grid(strategy_id):
        return next((r for r in grid_rows if r["id"] == strategy_id), None)

    def fake_get_strategy(strategy_id):
        return next((r for r in strategy_rows if r["id"] == strategy_id), None)

    monkeypatch.setattr(app_module, "get_grid_strategy", fake_get_grid)
    monkeypatch.setattr(app_module, "get_strategy", fake_get_strategy)
    # 零写库断言：所有写路径录制器
    calls: list[str] = []

    def _recorder(name):
        def _fn(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"对比端点不得写库：{name}")

        return _fn

    for name in (
        "save_grid_strategy",
        "save_strategy",
        "save_grid_backtest",
        "save_strategy_backtest",
        "schedule_strategy",
    ):
        monkeypatch.setattr(app_module, name, _recorder(name))
    return calls


def test_compare_saved_snapshot_reads_library(monkeypatch):
    _patch_history(monkeypatch, _bars())
    _patch_saved(
        monkeypatch,
        [_grid_row(), _grid_row(id="grid-ws", workspaceId="other"), _grid_row(id="grid-never", latestMetrics=None, lastBacktestAt=None)],
        [_strategy_row()],
    )
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/compare-saved?workspace=default",
            json={"mode": "snapshot", "ids": ["grid-1", "strategy-1", "grid-never", "grid-ws", "nope"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rerun"] is False
    items = {item["id"]: item for item in data["results"]}
    assert items["grid-1"]["found"] is True
    assert items["grid-1"]["source"] == "grid"
    assert items["grid-1"]["latestMetrics"]["returnPct"] == 5.0
    assert items["strategy-1"]["source"] == "strategy"
    assert items["strategy-1"]["strategyType"] == "ma_cross"
    assert items["grid-never"]["latestMetrics"] is None
    assert items["grid-never"]["missingReason"] == "从未回测"
    assert items["grid-ws"]["found"] is False
    assert items["grid-ws"]["missingReason"] == "不存在或不属于当前工作区"
    assert items["nope"]["found"] is False


def test_compare_saved_rerun_runs_without_side_effects(monkeypatch):
    bars = _bars()
    _patch_history(monkeypatch, bars)
    _patch_saved(monkeypatch, [_grid_row()], [_strategy_row()])
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/compare-saved",
            json={"mode": "rerun", "ids": ["grid-1", "strategy-1"]},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["rerun"] is True
    by_id = {item["id"]: item for item in data["results"]}
    grid_item = by_id["grid-1"]
    assert grid_item["metrics"]["tradeCount"] >= 0
    assert grid_item["config"]["lower"] == 85.0
    assert grid_item["config"]["gridCount"] == 8
    assert grid_item["dataSource"] == "tencent"
    assert "equityCurve" not in grid_item  # rerun 不含曲线
    assert "benchmarkCurve" not in grid_item
    engine_item = by_id["strategy-1"]
    assert engine_item["metrics"]["tradeCount"] >= 0
    assert engine_item["strategyType"] == "ma_cross"
    assert "equityCurve" not in engine_item


def test_compare_saved_rerun_partial_failure(monkeypatch):
    bars = _bars()

    def _boom(bars_, config):
        raise ValueError("引擎炸了")

    monkeypatch.setitem(
        STRATEGY_ENGINES, "ma_cross", {**STRATEGY_ENGINES["ma_cross"], "backtest": _boom}
    )
    _patch_history(monkeypatch, bars)
    _patch_saved(monkeypatch, [_grid_row()], [_strategy_row()])
    with TestClient(app_module.create_app()) as client:
        resp = client.post(
            "/api/strategy/compare-saved",
            json={"mode": "rerun", "ids": ["grid-1", "strategy-1"]},
        )
    assert resp.status_code == 200
    by_id = {item["id"]: item for item in resp.json()["results"]}
    assert by_id["grid-1"]["error"] is None
    assert "回测失败" in by_id["strategy-1"]["error"]
    assert by_id["strategy-1"]["metrics"] is None


def test_compare_saved_bounds(monkeypatch):
    _patch_history(monkeypatch, _bars())
    _patch_saved(monkeypatch, [], [])
    with TestClient(app_module.create_app()) as client:
        resp_empty = client.post("/api/strategy/compare-saved", json={"mode": "snapshot", "ids": []})
        resp_too_many = client.post(
            "/api/strategy/compare-saved",
            json={"mode": "snapshot", "ids": [f"x{i}" for i in range(11)]},
        )
        resp_mode = client.post(
            "/api/strategy/compare-saved", json={"mode": "weird", "ids": ["a"]}
        )
    assert resp_empty.status_code == 422
    assert resp_too_many.status_code == 422
    assert resp_mode.status_code == 422
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_strategy_compare.py -v -k saved`
Expected: 新增 4 个 FAIL（404）

- [ ] **Step 3: 实现 schemas**

`backend/schemas.py` 在 `CompareRunOut` 之后追加：

```python
class CompareSavedItem(BaseModel):
    """已保存策略对比项：snapshot / rerun / 缺失三种形状合一，缺省键为 None。"""

    model_config = ConfigDict(extra="ignore")

    id: str
    found: bool = True
    source: str | None = None  # "grid" | "strategy"
    name: str | None = None
    strategyType: str | None = None
    code: str | None = None
    status: str | None = None
    schedule: str | None = None
    capital: float | None = None
    feeBps: float | None = None
    lastBacktestAt: str | None = None
    latestMetrics: dict[str, Any] | None = None
    config: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    trades: list[dict[str, Any]] | None = None
    assumptions: str | None = None
    dataSource: str | None = None
    dataAsOf: str | None = None
    missingReason: str | None = None
    error: str | None = None


class CompareSavedIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    mode: str = "snapshot"  # snapshot（读库快照）| rerun（现跑回测）
    ids: list[str] = Field(default_factory=list)


class CompareSavedOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    rerun: bool = False
    results: list[CompareSavedItem] = Field(default_factory=list)
```

- [ ] **Step 4: 实现端点**

`backend/app.py`：schemas 导入块追加 `CompareSavedIn,` `CompareSavedOut,`（与 Task 1 同段按字母序）；端点插在 `strategy_compare` 之后：

```python
    @app.post("/api/strategy/compare-saved")
    def strategy_compare_saved(
        payload: CompareSavedIn, workspace_id: str = Query(default="default", alias="workspace")
    ) -> CompareSavedOut:
        """已保存策略对比：snapshot 纯读库 / rerun 按各自参数现跑（只读，零写库，不调度）。"""
        started = time.monotonic()
        try:
            if payload.mode not in {"snapshot", "rerun"}:
                raise api_error(422, ERR_VALIDATION_ERROR, "mode 必须为 snapshot 或 rerun")
            ids: list[str] = []
            for item in payload.ids:
                if item and item not in ids:
                    ids.append(item)
            if not ids:
                raise api_error(422, ERR_VALIDATION_ERROR, "至少选择一个已保存策略")
            if len(ids) > 10:
                raise api_error(422, ERR_VALIDATION_ERROR, "最多同时对比 10 个已保存策略")
            results: list[dict[str, Any]] = []
            failed_ids: list[str] = []
            missing_count = 0
            for strategy_id in ids:
                grid_row = get_grid_strategy(strategy_id)
                generic_row = None if grid_row else get_strategy(strategy_id)
                source = "grid" if grid_row else ("strategy" if generic_row else None)
                row = grid_row or generic_row
                if row is None or row.get("workspaceId") != workspace_id:
                    missing_count += 1
                    results.append(
                        {"id": strategy_id, "found": False, "missingReason": "不存在或不属于当前工作区"}
                    )
                    continue
                base = {
                    "id": strategy_id,
                    "found": True,
                    "source": source,
                    "name": row.get("name", ""),
                    "strategyType": "grid" if source == "grid" else str(row.get("strategyType", "")),
                    "code": row.get("code", ""),
                }
                if payload.mode == "snapshot":
                    latest = row.get("latestMetrics")
                    results.append(
                        {
                            **base,
                            "status": row.get("status", ""),
                            "schedule": row.get("schedule", ""),
                            "capital": row.get("capital"),
                            "feeBps": row.get("feeBps"),
                            "lastBacktestAt": row.get("lastBacktestAt"),
                            "latestMetrics": latest,
                            "missingReason": None if latest else "从未回测",
                        }
                    )
                    continue
                # rerun：按各自保存的参数在各自 code 上现跑（不落库不调度）
                try:
                    code = str(row["code"])
                    profile = classify_code(code)
                    if source == "grid":
                        lookback = max(20, min(int(row.get("lookback") or 120), 240))
                        history, data_source_flag, data_as_of, _ = _load_history_with_fallback(code, lookback)
                        limit_pct = price_limit_ratio(code)
                        result = backtest_grid(
                            history,
                            float(row["lower"]),
                            float(row["upper"]),
                            int(row["gridCount"]),
                            float(row["capital"]),
                            float(row["feeBps"]),
                            str(row.get("mode") or "classic"),
                            profile["securityType"],
                            profile["exchange"],
                            int(row.get("settlementDays") or 1),
                            float(row.get("slippageBps") or 5),
                            limit_pct,
                        )
                        config = {
                            "lower": row["lower"],
                            "upper": row["upper"],
                            "gridCount": row["gridCount"],
                            "mode": row.get("mode"),
                            "capital": row["capital"],
                            "feeBps": row["feeBps"],
                            "lookback": lookback,
                            "settlementDays": row.get("settlementDays"),
                            "slippageBps": row.get("slippageBps"),
                            "priceLimitPct": limit_pct * 100,
                        }
                    else:
                        config = dict(row.get("config") or {})
                        lookback = max(20, min(int(config.get("lookback") or 120), 240))
                        history, data_source_flag, data_as_of, _ = _load_history_with_fallback(code, lookback)
                        result = STRATEGY_ENGINES[str(row["strategyType"])]["backtest"](history, config)
                    results.append(
                        {
                            **base,
                            "config": config,
                            "metrics": result["metrics"],
                            "trades": result["trades"],
                            "assumptions": result["assumptions"],
                            "dataSource": data_source_flag,
                            "dataAsOf": data_as_of,
                            "error": None,
                        }
                    )
                except Exception as exc:  # 单策略失败逐项披露（spec §3.2）
                    failed_ids.append(strategy_id)
                    results.append({**base, "error": f"回测失败：{exc}"})
            compare_logger.info(
                "strategy.compare_saved",
                extra={
                    "mode": payload.mode,
                    "idCount": len(ids),
                    "elapsedMs": int((time.monotonic() - started) * 1000),
                    "resultStatus": "partial_failure" if failed_ids or missing_count else "success",
                    "failedIds": failed_ids,
                    "missingCount": missing_count,
                },
            )
            return CompareSavedOut.model_validate({"rerun": payload.mode == "rerun", "results": results})
        except HTTPException:
            raise
        except Exception as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc)) from exc
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_strategy_compare.py -v`
Expected: 8 passed（Task 1 的 4 个 + 本任务 4 个）

Run: `python -m ruff check backend tests && python -m mypy backend`
Expected: 全绿

- [ ] **Step 6: 提交**

```bash
git add backend/schemas.py backend/app.py tests/test_strategy_compare.py
git commit -m "feat: 新增 /api/strategy/compare-saved 已保存策略对比（快照+现跑，零写库）"
```

---

### Task 3: 前端 `modules/csv.ts`（组装器 + 公式注入防护）

**Files:**
- Create: `frontend/src/modules/csv.ts`
- Create: `tests/frontend/csv.test.ts`

**Interfaces:**
- Consumes: 无（纯函数模块）。
- Produces: `csvCell(value: unknown): string`、`buildCsv(headers: string[], rows: unknown[][]): string`、`downloadCsv(filename: string, csv: string): void`、`METRIC_LABELS: Record<string, string>`、`summarizeConfig(config): string`、`buildCompareMetricsCsv(rows: CompareMetricRow[]): string`、`buildCompareCurvesCsv(run: CompareCurvesRun): string`、`buildCompareTradesCsv(rows: CompareTradesRow[]): string`（Task 4 store 消费）。

- [ ] **Step 1: 写失败测试**

创建 `tests/frontend/csv.test.ts`：

```ts
import { describe, expect, it, vi, afterEach } from 'vitest';
import {
  buildCompareCurvesCsv,
  buildCompareMetricsCsv,
  buildCompareTradesCsv,
  buildCsv,
  csvCell,
  downloadCsv,
  summarizeConfig,
} from '@/modules/csv';

describe('csvCell 公式注入防护', () => {
  it.each([
    ['=cmd', "'=cmd"],
    ['+1+1', "'+1+1"],
    ['-1;drop', "'-1;drop"],
    ['@sum', "'@sum"],
    ['\tx', "'\tx"],
    ['\rx', "'\rx"],
  ])('危险前缀 %s 加撇号', (input, expected) => {
    expect(csvCell(input)).toBe(expected);
  });

  it('正常文本 / 数字 / 布尔 / null 不加撇号', () => {
    expect(csvCell('贵州茅台')).toBe('贵州茅台');
    expect(csvCell(-12.5)).toBe('-12.5');
    expect(csvCell(true)).toBe('true');
    expect(csvCell(null)).toBe('');
    expect(csvCell(undefined)).toBe('');
  });
});

describe('buildCsv', () => {
  it('表头与行按逗号/换行拼接', () => {
    expect(buildCsv(['a', 'b'], [[1, 'x'], [null, 'y,z']])).toBe('a,b\n1,x\n,y,z');
  });
});

describe('summarizeConfig', () => {
  it('按插入序拼 key=value，空配置给占位', () => {
    expect(summarizeConfig({ fastPeriod: 5, slowPeriod: 20 })).toBe('fastPeriod=5, slowPeriod=20');
    expect(summarizeConfig({ gridCount: 8, mode: 'classic', lower: 90 })).toBe('gridCount=8, mode=classic, lower=90');
    expect(summarizeConfig(null)).toBe('');
  });
});

describe('buildCompareMetricsCsv', () => {
  it('行=策略，列=中文表头全集，null 落空单元格', () => {
    const csv = buildCompareMetricsCsv([
      { label: '网格', type: 'grid', params: 'gridCount=8', metrics: { returnPct: 5.2, winRatePct: null } },
      { label: 'MACD', type: 'macd', params: '', metrics: null },
    ]);
    const lines = csv.split('\n');
    expect(lines[0]).toContain('区间收益%');
    expect(lines[0]).toContain('夏普比率');
    expect(lines[1]).toContain('网格');
    expect(lines[1]).toContain('5.2');
    expect(lines[2]).toContain('MACD');
  });
});

describe('buildCompareCurvesCsv 宽表', () => {
  it('日期 + 每策略一列 + 基准列；error 策略整列省略', () => {
    const csv = buildCompareCurvesCsv({
      benchmarkCurve: [
        { date: '2026-01-01', equity: 1 },
        { date: '2026-01-02', equity: 1.01 },
      ],
      results: [
        { label: '网格', equityCurve: [{ date: '2026-01-01', equity: 1 }, { date: '2026-01-02', equity: 1.05 }] },
        { label: 'MACD', equityCurve: null },
      ],
    });
    const lines = csv.split('\n');
    expect(lines[0]).toBe('日期,网格 净值,基准净值');
    expect(lines[1]).toBe('2026-01-01,1,1');
    expect(lines[2]).toBe('2026-01-02,1.05,1.01');
  });
});

describe('buildCompareTradesCsv 长表', () => {
  it('每笔成交一行；triggerPrice/module 为 null 落空', () => {
    const csv = buildCompareTradesCsv([
      {
        label: '网格',
        trades: [{ date: '2026-01-05', side: 'buy', triggerPrice: 90.5, price: 90.6, shares: 100, fee: 5 }],
      },
      { label: '双均线', trades: [{ date: '2026-01-06', side: 'sell', triggerPrice: null, price: 100, shares: 200, fee: 5, module: 'range' }] },
    ]);
    const lines = csv.split('\n');
    expect(lines[0]).toBe('策略,日期,方向,触发价,成交价,股数,费用,模块');
    expect(lines[1]).toBe('网格,2026-01-05,buy,90.5,90.6,100,5,');
    expect(lines[2]).toBe('双均线,2026-01-06,sell,,100,200,5,range');
  });
});

describe('downloadCsv', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('BOM + Blob + 文件名下载', () => {
    const createObjectURL = vi.fn(() => 'blob:mock');
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const click = vi.fn();
    const append = vi.fn();
    const link: Record<string, unknown> = {};
    vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
      if (tag === 'a') {
        return { ...link, click, style: {} } as unknown as HTMLAnchorElement;
      }
      return document.createElementNS('', tag);
    });
    vi.spyOn(document.body, 'appendChild').mockImplementation(append as never);
    downloadCsv('atlas-compare-metrics-1.csv', 'a,b');
    const blob = createObjectURL.mock.calls[0][0] as Blob;
    expect(blob.type).toBe('text/csv;charset=utf-8;');
    void blob.text().then((text: string) => expect(text.charCodeAt(0)).toBe(0xfeff));
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/csv.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现 `frontend/src/modules/csv.ts`**

```ts
// CSV 组装与下载（多策略对比导出用）。
// 纪律：csvCell 对 = + - @ \t \r 开头的字符串加 "'" 前缀（Excel 公式注入标准缓解，spec §4.3）；
// downloadCsv 统一 BOM + Blob，与 useScreenerStore.exportCsv 先例一致。

export function csvCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  const text = String(value);
  return /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
}

export function buildCsv(headers: string[], rows: unknown[][]): string {
  const line = (row: unknown[]) => row.map((cell) => csvCell(cell)).join(',');
  return [line(headers), ...rows.map(line)].join('\n');
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** 指标中文表头映射（spec §6 全集，列顺序固定）。 */
export const METRIC_LABELS: Record<string, string> = {
  returnPct: '区间收益%',
  annualizedReturnPct: '年化收益%',
  benchmarkReturnPct: '基准收益%',
  excessReturnPct: '超额收益%',
  maxDrawdownPct: '最大回撤%',
  maxDrawdownDurationDays: '最长回撤天数',
  annualizedVolatilityPct: '年化波动%',
  sharpeRatio: '夏普比率',
  winRatePct: '胜率%',
  profitFactor: '利润因子',
  avgGridReturnPct: '单格平均收益%',
  medianGridReturnPct: '单格收益中位%',
  tradeCount: '成交次数',
  buyCount: '买入次数',
  sellCount: '卖出次数',
  totalFees: '总费用',
  turnoverMultiple: '换手倍数',
  startEquity: '期初权益',
  endEquity: '期末权益',
  skippedLimitUpDays: '涨停跳过天数',
  skippedLimitDownDays: '跌停跳过天数',
  skippedSuspensionDays: '停牌天数',
  onePriceLimitUpDays: '一字涨停天数',
  onePriceLimitDownDays: '一字跌停天数',
};

export interface CompareMetricRow {
  label: string;
  type: string;
  params: string;
  metrics: Record<string, unknown> | null;
}

/** 参数摘要：按插入序拼 key=value（spec §4.3）。 */
export function summarizeConfig(config: Record<string, unknown> | null | undefined): string {
  if (!config || typeof config !== 'object') return '';
  return Object.entries(config)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => `${key}=${value}`)
    .join(', ');
}

export function buildCompareMetricsCsv(rows: CompareMetricRow[]): string {
  const keys = Object.keys(METRIC_LABELS);
  const headers = ['策略', '类型', '参数', ...keys.map((key) => METRIC_LABELS[key])];
  const body = rows.map((row) => {
    const metrics = row.metrics || {};
    return [row.label, row.type, row.params, ...keys.map((key) => (metrics[key] ?? null) as unknown)];
  });
  return buildCsv(headers, body);
}

export interface CompareCurvesRun {
  benchmarkCurve: { date: string; equity: number }[] | null;
  results: { label: string; equityCurve: { date: string; equity: number }[] | null }[];
}

/** 宽表：日期 + 每策略一列 + 基准列；error 策略无曲线整列省略（spec §4.3）。 */
export function buildCompareCurvesCsv(run: CompareCurvesRun): string {
  const okResults = (run.results || []).filter((item) => Array.isArray(item.equityCurve));
  const benchmark = run.benchmarkCurve || [];
  const headers = ['日期', ...okResults.map((item) => `${item.label} 净值`), '基准净值'];
  const body: unknown[][] = [];
  for (let i = 0; i < benchmark.length; i++) {
    body.push([
      benchmark[i]?.date ?? '',
      ...okResults.map((item) => item.equityCurve?.[i]?.equity ?? null),
      benchmark[i]?.equity ?? null,
    ]);
  }
  return buildCsv(headers, body);
}

export interface CompareTradesRow {
  label: string;
  trades: Record<string, unknown>[] | null;
}

/** 长表：策略 / 日期 / 方向 / 触发价 / 成交价 / 股数 / 费用 / 模块。 */
export function buildCompareTradesCsv(rows: CompareTradesRow[]): string {
  const headers = ['策略', '日期', '方向', '触发价', '成交价', '股数', '费用', '模块'];
  const body: unknown[][] = [];
  for (const row of rows) {
    for (const trade of row.trades || []) {
      body.push([
        row.label,
        trade.date,
        trade.side,
        trade.triggerPrice ?? null,
        trade.price,
        trade.shares,
        trade.fee,
        trade.module ?? null,
      ]);
    }
  }
  return buildCsv(headers, body);
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run tests/frontend/csv.test.ts`
Expected: 全部 passed

Run: `npx vue-tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 5: 提交**

```bash
git add frontend/src/modules/csv.ts tests/frontend/csv.test.ts
git commit -m "feat: 新增 csv 模块——对比导出组装器与 CSV 公式注入防护"
```

---

### Task 4: 前端 `useCompareStore`（第 13 个 store）

**Files:**
- Modify: `frontend/src/modules/constants.ts`（`STRATEGY_TYPES` 加 compare 项 + 新导出 `COMPARE_STRATEGY_TYPES`）
- Create: `frontend/src/stores/useCompareStore.ts`
- Create: `tests/frontend/useCompareStore.test.ts`

**Interfaces:**
- Consumes: `workspace.requestJson` / `workspace.showToast`；`COMPARE_STRATEGY_TYPES`（本任务加入 constants）；Task 3 的 csv.ts 函数。
- Produces: store state `runLoading / runResult / selectedTypes / savedLoading / savedResult / savedSelection / compareDraft`；actions `toggleType / runCompare / toggleSaved / savedOptions / compareSaved(mode) / exportRunCsv(kind) / exportSavedCsv(kind)`；computed `runChartSvg / runSelectedCount`。ViewGrid（Task 5）消费。

- [ ] **Step 1: 写失败测试**

创建 `tests/frontend/useCompareStore.test.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useCompareStore } from '@/stores/useCompareStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';

const downloadCsv = vi.fn();
vi.mock('@/modules/csv', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  downloadCsv: (...a: unknown[]) => downloadCsv(...a),
}));

function jsonResponse(payload: unknown, ok = true, status = 200) {
  return { ok, status, headers: { get: () => null }, json: async () => payload };
}

const RUN_PAYLOAD = {
  code: '600519',
  profile: {},
  dataSource: 'tencent',
  dataAsOf: '2026-08-30',
  barCount: 60,
  benchmarkCurve: [{ date: '2026-01-01', equity: 1 }],
  results: [
    {
      strategyType: 'grid',
      label: '网格',
      config: { gridCount: 8, lower: 90, upper: 110 },
      metrics: { returnPct: 5.2, maxDrawdownPct: 3 },
      equityCurve: [{ date: '2026-01-01', equity: 1.0 }],
      trades: [{ date: '2026-01-02', side: 'buy', triggerPrice: 90, price: 90.1, shares: 100, fee: 5 }],
      assumptions: '假设',
      error: null,
    },
    { strategyType: 'macd', label: 'MACD', error: '回测失败：引擎炸了' },
  ],
};

const SAVED_PAYLOAD = {
  rerun: false,
  results: [
    { id: 'grid-1', found: true, source: 'grid', name: '网格A', strategyType: 'grid', code: '600519', latestMetrics: { returnPct: 5 }, missingReason: null },
    { id: 'nope', found: false, missingReason: '不存在或不属于当前工作区' },
  ],
};

describe('useCompareStore', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    setActivePinia(createPinia());
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    downloadCsv.mockClear();
  });

  it('默认勾选 8 个回测策略类型（不含 compare tab 自身）', () => {
    const store = useCompareStore();
    expect(store.selectedTypes).toHaveLength(8);
    expect(store.selectedTypes).not.toContain('compare');
    expect(store.selectedTypes).toContain('grid');
    expect(store.selectedTypes).toContain('multi_factor');
  });

  it('toggleType 勾选/取消', () => {
    const store = useCompareStore();
    store.toggleType('grid');
    expect(store.selectedTypes).not.toContain('grid');
    store.toggleType('grid');
    expect(store.selectedTypes).toContain('grid');
  });

  it('runCompare 发送勾选类型并保存结果；全空时中文提示不发请求', async () => {
    const workspace = useWorkspaceStore();
    const toastSpy = vi.spyOn(workspace, 'showToast');
    fetchMock.mockResolvedValue(jsonResponse(RUN_PAYLOAD));
    const store = useCompareStore();
    store.compareDraft.code = '600519';
    await store.runCompare();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, options] = fetchMock.mock.calls[0];
    expect(options.url ?? '/api/strategy/compare').toBe('/api/strategy/compare');
    expect(JSON.parse(options.body).strategyTypes).toHaveLength(8);
    expect(store.runResult?.results).toHaveLength(2);
    expect(store.runLoading).toBe(false);
    // 全空 → 不发请求
    store.selectedTypes = [];
    await store.runCompare();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(toastSpy).toHaveBeenCalledWith('至少勾选一个策略类型', 'error');
  });

  it('runCompare 422 时中文 toast 且不保存结果', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: { error: '未知策略类型：nope', code: 'VALIDATION_ERROR' } }, false, 422)
    );
    const workspace = useWorkspaceStore();
    const toastSpy = vi.spyOn(workspace, 'showToast');
    const store = useCompareStore();
    await store.runCompare();
    expect(store.runResult).toBeNull();
    expect(toastSpy).toHaveBeenCalledWith('未知策略类型：nope', 'error');
  });

  it('runChartSvg：成功策略实线 + 基准虚线，error 策略跳过', () => {
    const store = useCompareStore();
    store.runResult = RUN_PAYLOAD;
    expect(store.runChartSvg).toContain('chart-line');
    expect(store.runChartSvg).toContain('网格');
    expect(store.runChartSvg).not.toContain('MACD');
  });

  it('compareSaved(snapshot) 读库并保存结果', async () => {
    fetchMock.mockResolvedValue(jsonResponse(SAVED_PAYLOAD));
    const store = useCompareStore();
    store.savedSelection = ['grid-1', 'nope'];
    await store.compareSaved('snapshot');
    expect(store.savedResult?.rerun).toBe(false);
    expect(store.savedLoading).toBe(false);
  });

  it('exportRunCsv 三种导出走 downloadCsv 且文件名正确', () => {
    const store = useCompareStore();
    store.runResult = RUN_PAYLOAD;
    store.exportRunCsv('metrics');
    store.exportRunCsv('curves');
    store.exportRunCsv('trades');
    expect(downloadCsv).toHaveBeenCalledTimes(3);
    expect(String(downloadCsv.mock.calls[0][0])).toMatch(/^atlas-compare-metrics-\d+\.csv$/);
    expect(String(downloadCsv.mock.calls[1][0])).toMatch(/^atlas-compare-curves-\d+\.csv$/);
    expect(String(downloadCsv.mock.calls[2][0])).toMatch(/^atlas-compare-trades-\d+\.csv$/);
    const tradesCsv = String(downloadCsv.mock.calls[2][1]);
    expect(tradesCsv).toContain('网格');
    expect(tradesCsv).not.toContain('MACD'); // error 策略无成交
  });

  it('exportSavedCsv：snapshot 只有 metrics 可导，rerun 才有 trades', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        rerun: true,
        results: [
          {
            id: 'grid-1',
            found: true,
            source: 'grid',
            name: '网格A',
            strategyType: 'grid',
            code: '600519',
            config: { gridCount: 8 },
            metrics: { returnPct: 6 },
            trades: [{ date: '2026-01-02', side: 'buy', price: 90, shares: 100, fee: 5 }],
            assumptions: '假设',
            dataSource: 'tencent',
            dataAsOf: '2026-08-30',
            error: null,
          },
        ],
      })
    );
    const store = useCompareStore();
    store.savedSelection = ['grid-1'];
    await store.compareSaved('rerun');
    store.exportSavedCsv('trades');
    expect(downloadCsv).toHaveBeenCalledTimes(1);
    expect(String(downloadCsv.mock.calls[0][1])).toContain('网格A');
    // snapshot 无 trades：导出 trades 时提示且不下载
    downloadCsv.mockClear();
    store.savedResult = SAVED_PAYLOAD;
    const workspace = useWorkspaceStore();
    const toastSpy = vi.spyOn(workspace, 'showToast');
    store.exportSavedCsv('trades');
    expect(downloadCsv).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith('快照模式无成交明细，请先用「重新回测并对比」', 'error');
  });

  it('savedOptions 合并网格与普通策略', () => {
    const store = useCompareStore();
    const { useGridStore } = require('@/stores/useGridStore') as typeof import('@/stores/useGridStore');
    const grid = useGridStore();
    grid.gridStrategies = [{ id: 'grid-1', name: '网格A', code: '600519', mode: 'classic', status: '启用', lastBacktestAt: '2026-10-10' }];
    const { useStrategyStore } = require('@/stores/useStrategyStore') as typeof import('@/stores/useStrategyStore');
    useStrategyStore().strategies = [
      { id: 'strategy-1', name: '双均线A', code: '600519', strategyType: 'ma_cross', status: '启用', lastBacktestAt: null },
    ];
    expect(store.savedOptions.map((option) => option.key)).toEqual(['grid-1', 'strategy-1']);
    expect(store.savedOptions[0].typeLabel).toBe('经典网格');
    expect(store.savedOptions[1].typeLabel).toBe('双均线');
  });
});
```

注意：`require` 在 vitest ESM 下不可用——把 `savedOptions` 用例改为顶部静态导入（`import { useGridStore } from '@/stores/useGridStore'; import { useStrategyStore } from '@/stores/useStrategyStore';`），在用例内直接调用 `useGridStore()` / `useStrategyStore()`（pinia 已激活）。

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/useCompareStore.test.ts`
Expected: FAIL（store 不存在）

- [ ] **Step 3: 实现 constants 增量**

`frontend/src/modules/constants.ts`：`STRATEGY_TYPES` 数组末尾追加一项，并在其后新增导出：

```ts
export const STRATEGY_TYPES = [
  { id: 'grid', label: '网格', description: '区间网格，跌买涨卖' },
  { id: 'ma_cross', label: '双均线', description: '快线上穿买入，下穿卖出' },
  { id: 'dca', label: '定投', description: '定期定额 + 止盈止损' },
  { id: 'macd', label: 'MACD', description: 'DIF 上穿 DEA 买入，下穿卖出' },
  { id: 'bollinger', label: '布林带反转', description: '跌破下轨买入，上穿上轨卖出（均值回归）' },
  { id: 'donchian', label: '唐奇安突破', description: '通道突破入场，反向突破离场（ADX 确认）' },
  { id: 'momentum', label: '动量', description: 'N 日涨跌幅阈值进出，独立资金管理' },
  { id: 'multi_factor', label: '多因子', description: 'ADX 状态过滤器 + 动态模块切换' },
  { id: 'compare', label: '对比', description: '多策略同标的横向对比' },
];

// 对比 tab 的参与策略勾选集（= 全部回测策略类型，不含 compare tab 自身）
export const COMPARE_STRATEGY_TYPES = STRATEGY_TYPES.filter((item) => item.id !== 'compare');
```

（保持既有条目逐字不变，只追加。）

- [ ] **Step 4: 实现 store**

创建 `frontend/src/stores/useCompareStore.ts`：

```ts
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { multiLineSvg, type MultiLineSeries } from '@/modules/chart';
import { COMPARE_STRATEGY_TYPES, STRATEGY_TYPES as STRATEGY_TYPES_LIST } from '@/modules/constants';
import {
  buildCompareCurvesCsv,
  buildCompareMetricsCsv,
  buildCompareTradesCsv,
  downloadCsv,
  summarizeConfig,
  type CompareMetricRow,
} from '@/modules/csv';
import { useWorkspaceStore } from './useWorkspaceStore';
import { useGridStore } from './useGridStore';
import { useStrategyStore } from './useStrategyStore';

export type CompareExportKind = 'metrics' | 'curves' | 'trades';
export type CompareSavedMode = 'snapshot' | 'rerun';

const COMPARE_COLORS = ['#2563eb', '#059669', '#d97706', '#dc2626', '#7c3aed', '#0891b2', '#ca8a04', '#e11d48'];
const COMPARE_SAVED_LIMIT = 10;

/**
 * 多策略对比 store：同标的横向对比 + 已保存策略对比（快照/rerun）。
 * 对比结果纯内存不落库（spec §2 非目标）；CSV 组装全部委托 modules/csv。
 */
export const useCompareStore = defineStore('compare', () => {
  const workspace = useWorkspaceStore();
  const runLoading = ref(false);
  const runResult = ref<any>(null);
  const selectedTypes = ref<string[]>(COMPARE_STRATEGY_TYPES.map((item) => item.id));
  const compareDraft = ref({ code: '', lookback: 120, capital: 100000, feeBps: 3 });
  const savedLoading = ref(false);
  const savedResult = ref<any>(null);
  const savedSelection = ref<string[]>([]);

  function toggleType(id: string) {
    selectedTypes.value = selectedTypes.value.includes(id)
      ? selectedTypes.value.filter((item) => item !== id)
      : [...selectedTypes.value, id];
  }

  async function runCompare() {
    if (!selectedTypes.value.length) {
      workspace.showToast('至少勾选一个策略类型', 'error');
      return;
    }
    runLoading.value = true;
    try {
      const payload = await workspace.requestJson('/api/strategy/compare', {
        method: 'POST',
        body: JSON.stringify({ ...compareDraft.value, strategyTypes: selectedTypes.value }),
      });
      runResult.value = payload;
      workspace.showToast('对比完成');
    } catch (error: any) {
      workspace.showToast(error.message || '策略对比失败', 'error');
    } finally {
      runLoading.value = false;
    }
  }

  const runSeries = computed<MultiLineSeries[]>(() => {
    const run = runResult.value;
    if (!run) return [];
    const series: MultiLineSeries[] = (run.results || [])
      .filter((item: any) => Array.isArray(item.equityCurve))
      .map((item: any, index: number) => ({
        label: String(item.label || item.strategyType),
        points: item.equityCurve.map((point: any) => (typeof point?.equity === 'number' ? point.equity : null)),
        style: 'solid' as const,
        color: COMPARE_COLORS[index % COMPARE_COLORS.length],
      }));
    if (Array.isArray(run.benchmarkCurve)) {
      series.push({
        label: '基准',
        points: run.benchmarkCurve.map((point: any) => (typeof point?.equity === 'number' ? point.equity : null)),
        style: 'dash',
        color: '#6b7280',
      });
    }
    return series;
  });

  const runChartSvg = computed(() =>
    runSeries.value.length
      ? multiLineSvg(runSeries.value, { height: 220, legend: true, ariaLabel: '多策略归一化净值对比' })
      : ''
  );

  function bestValue(key: string, mode: 'max' | 'min'): number | null {
    const run = runResult.value;
    if (!run) return null;
    const values = (run.results || [])
      .map((item: any) => item?.metrics?.[key])
      .filter((value: any) => typeof value === 'number');
    if (!values.length) return null;
    return mode === 'max' ? Math.max(...values) : Math.min(...values);
  }

  function isBest(item: any, key: string, mode: 'max' | 'min'): boolean {
    const value = item?.metrics?.[key];
    if (typeof value !== 'number') return false;
    const best = bestValue(key, mode);
    return best !== null && value === best;
  }

  const savedOptions = computed(() => {
    const grid = useGridStore().gridStrategies.map((strategy: any) => ({
      key: String(strategy.id),
      id: String(strategy.id),
      name: String(strategy.name || ''),
      code: String(strategy.code || ''),
      typeLabel: strategy.mode === 'trend' ? '趋势网格' : '经典网格',
      status: String(strategy.status || ''),
      lastBacktestAt: strategy.lastBacktestAt || null,
    }));
    const generic = useStrategyStore().strategies.map((strategy: any) => ({
      key: String(strategy.id),
      id: String(strategy.id),
      name: String(strategy.name || ''),
      code: String(strategy.code || ''),
      typeLabel: (STRATEGY_TYPES_LIST.find((item) => item.id === strategy.strategyType) || {}).label || String(strategy.strategyType || ''),
      status: String(strategy.status || ''),
      lastBacktestAt: strategy.lastBacktestAt || null,
    }));
    return [...grid, ...generic];
  });

  function toggleSaved(key: string) {
    savedSelection.value = savedSelection.value.includes(key)
      ? savedSelection.value.filter((item) => item !== key)
      : savedSelection.value.length >= COMPARE_SAVED_LIMIT
        ? savedSelection.value
        : [...savedSelection.value, key];
  }

  async function compareSaved(mode: CompareSavedMode) {
    if (!savedSelection.value.length) {
      workspace.showToast('至少选择一个已保存策略', 'error');
      return;
    }
    savedLoading.value = true;
    try {
      const payload = await workspace.requestJson('/api/strategy/compare-saved', {
        method: 'POST',
        body: JSON.stringify({ mode, ids: savedSelection.value }),
      });
      savedResult.value = payload;
      workspace.showToast(mode === 'rerun' ? '现跑对比完成' : '快照对比完成');
    } catch (error: any) {
      workspace.showToast(error.message || '已保存策略对比失败', 'error');
    } finally {
      savedLoading.value = false;
    }
  }

  function _metricRows(results: any[]): CompareMetricRow[] {
    return (results || [])
      .filter((item: any) => item && item.found !== false && !item.error)
      .map((item: any) => ({
        label: String(item.label || item.name || item.strategyType),
        type: String(item.strategyType || item.source || ''),
        params: summarizeConfig(item.config),
        metrics: item.metrics ?? null,
      }));
  }

  function exportRunCsv(kind: CompareExportKind) {
    const run = runResult.value;
    if (!run) return;
    if (kind === 'metrics') {
      downloadCsv(`atlas-compare-metrics-${Date.now()}.csv`, buildCompareMetricsCsv(_metricRows(run.results || [])));
    } else if (kind === 'curves') {
      downloadCsv(`atlas-compare-curves-${Date.now()}.csv`, buildCompareCurvesCsv(run));
    } else {
      downloadCsv(
        `atlas-compare-trades-${Date.now()}.csv`,
        buildCompareTradesCsv((run.results || []).filter((item: any) => !item.error).map((item: any) => ({ label: String(item.label || item.strategyType), trades: item.trades })))
      );
    }
    workspace.showToast('CSV 已导出');
  }

  function exportSavedCsv(kind: CompareExportKind) {
    const saved = savedResult.value;
    if (!saved) return;
    if (kind === 'trades' && !saved.rerun) {
      workspace.showToast('快照模式无成交明细，请先用「重新回测并对比」', 'error');
      return;
    }
    if (kind === 'metrics') {
      downloadCsv(`atlas-compare-metrics-${Date.now()}.csv`, buildCompareMetricsCsv(_metricRows(saved.results || [])));
    } else if (kind === 'trades') {
      downloadCsv(
        `atlas-compare-trades-${Date.now()}.csv`,
        buildCompareTradesCsv((saved.results || []).filter((item: any) => !item.error).map((item: any) => ({ label: String(item.name || item.id), trades: item.trades })))
      );
    }
    // saved 模式无 curves 导出（spec §5）
    workspace.showToast('CSV 已导出');
  }

  return {
    runLoading,
    runResult,
    selectedTypes,
    compareDraft,
    savedLoading,
    savedResult,
    savedSelection,
    runChartSvg,
    savedOptions,
    toggleType,
    runCompare,
    toggleSaved,
    compareSaved,
    isBest,
    exportRunCsv,
    exportSavedCsv,
  };
});
```

- [ ] **Step 5: 运行测试确认通过**

Run: `npx vitest run tests/frontend/useCompareStore.test.ts`
Expected: 全部 passed

Run: `npx vue-tsc --noEmit`
Expected: 无类型错误

- [ ] **Step 6: 提交**

```bash
git add frontend/src/modules/constants.ts frontend/src/stores/useCompareStore.ts tests/frontend/useCompareStore.test.ts
git commit -m "feat: 新增 useCompareStore 对比状态仓库与对比策略类型集"
```

---

### Task 5: ViewGrid「对比」tab UI + 冒烟测试

**Files:**
- Modify: `frontend/src/views/ViewGrid.vue`（tab 图标分支 + compare 布局 + saved 区块 + script 接线）
- Create: `tests/frontend/ViewGrid.test.ts`

**Interfaces:**
- Consumes: `useCompareStore`（Task 4 全部导出）；`COMPARE_STRATEGY_TYPES`；`multiLineSvg` 经 store 的 `runChartSvg`。
- Produces: 用户可见「对比」tab（第 9 项）。

- [ ] **Step 1: 写失败冒烟测试**

创建 `tests/frontend/ViewGrid.test.ts`（lucide mock 照抄 ViewPlans.test.ts 模式）：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { flushPromises, mount } from '@vue/test-utils';

vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));

import { useCompareStore } from '@/stores/useCompareStore';
import { useStrategyStore } from '@/stores/useStrategyStore';
import ViewGrid from '@/views/ViewGrid.vue';

const RUN_PAYLOAD = {
  code: '600519',
  profile: {},
  dataSource: 'tencent',
  dataAsOf: '2026-08-30',
  barCount: 60,
  benchmarkCurve: [{ date: '2026-01-01', equity: 1 }],
  results: [
    {
      strategyType: 'grid',
      label: '网格',
      config: { gridCount: 8, lower: 90, upper: 110 },
      metrics: { returnPct: 5.2, maxDrawdownPct: 3, tradeCount: 12, totalFees: 120 },
      equityCurve: [{ date: '2026-01-01', equity: 1 }],
      trades: [],
      assumptions: '网格假设',
      error: null,
    },
    { strategyType: 'macd', label: 'MACD', error: '回测失败：引擎炸了' },
  ],
};

describe('ViewGrid 对比 tab', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('tab 栏含「对比」且切换后渲染对比区块（8 个策略勾选 + 警示脚注）', async () => {
    const wrapper = mount(ViewGrid, { global: { plugins: [] } });
    await wrapper.find('.strategy-tabs').findAll('button').find((b) => b.text().includes('对比'))!.trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('多策略横向对比');
    const checks = wrapper.findAll('.compare-type-check');
    expect(checks).toHaveLength(8);
  });

  it('对比结果渲染：指标行 / error 行 / 网格偏乐观警示 / 导出按钮', async () => {
    const wrapper = mount(ViewGrid, { global: { plugins: [] } });
    const strategy = useStrategyStore();
    strategy.strategyType = 'compare';
    const compare = useCompareStore();
    compare.runResult = RUN_PAYLOAD;
    await flushPromises();
    expect(wrapper.text()).toContain('网格区间为样本内自动建议，结果偏乐观');
    expect(wrapper.text()).toContain('回测失败：引擎炸了');
    expect(wrapper.text()).toContain('5.2%');
    const exportButtons = wrapper.findAll('button').filter((b) => b.text().includes('导出'));
    expect(exportButtons.length).toBe(3);
  });

  it('已保存策略对比：无保存策略时空态文案', async () => {
    const wrapper = mount(ViewGrid, { global: { plugins: [] } });
    useStrategyStore().strategyType = 'compare';
    await flushPromises();
    expect(wrapper.text()).toContain('暂无已保存策略');
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/ViewGrid.test.ts`
Expected: FAIL（无对比 tab / 区块）

- [ ] **Step 3: 实现 ViewGrid.vue**

(a) tab 图标三元链末尾（`item.id === 'momentum' ? 'zap' : 'layers'` 处）补一个分支：把 `: 'layers'` 改为 `: item.id === 'compare' ? 'git-compare' : 'layers'`。

(b) 布局分支：把通用策略分支 `<div v-else class="grid-strategy-layout">` 改为 `<div v-else-if="strategyType !== 'compare'" class="grid-strategy-layout">`，紧随其后插入对比布局（两面板）：

```vue
    <div v-else class="grid-strategy-layout">
      <section class="grid-config-panel surface">
        <div class="surface-heading">
          <div>
            <span class="section-kicker">COMPARISON</span>
            <h3>多策略横向对比</h3>
          </div>
          <span class="draft-status">{{ compare.runLoading ? '计算中' : '日线回测' }}</span>
        </div>
        <div class="form-grid">
          <label class="field field-wide"
            ><span>股票或 ETF 代码</span
            ><input
              v-model.trim="compare.compareDraft.code"
              inputmode="numeric"
              maxlength="6"
              placeholder="例如 600519"
              @keydown.enter.prevent="compare.runCompare()"
          /></label>
          <label class="field"
            ><span>历史窗口</span
            ><select v-model.number="compare.compareDraft.lookback">
              <option :value="60">60 个交易日</option>
              <option :value="120">120 个交易日</option>
              <option :value="240">240 个交易日</option>
            </select></label
          >
          <label class="field"
            ><span>投入资金</span>
            <div class="number-input">
              <input v-model.number="compare.compareDraft.capital" type="number" min="1000" step="1000" /><span>元</span>
            </div></label
          >
          <label class="field"
            ><span>双边费率</span>
            <div class="number-input">
              <input v-model.number="compare.compareDraft.feeBps" type="number" min="0" step="0.1" /><span>BP</span>
            </div></label
          >
          <div class="field field-wide">
            <span>参与策略（{{ compare.selectedTypes.length }}/8）</span>
            <div class="compare-type-checks">
              <label v-for="item in COMPARE_STRATEGY_TYPES" :key="item.id" class="compare-type-check">
                <input
                  type="checkbox"
                  :checked="compare.selectedTypes.includes(item.id)"
                  @change="compare.toggleType(item.id)"
                /><span>{{ item.label }}</span>
              </label>
            </div>
          </div>
        </div>
        <div class="form-footer">
          <span class="form-footnote"
            ><i data-lucide="info" aria-hidden="true"></i>同一份日线在勾选策略间重放对比；引擎参数取默认值</span
          ><button class="button button-primary" type="button" :disabled="compare.runLoading" @click="compare.runCompare()">
            <i data-lucide="git-compare" aria-hidden="true"></i>运行对比
          </button>
        </div>
      </section>
      <section class="grid-result-panel surface">
        <div class="surface-heading">
          <div>
            <span class="section-kicker">COMPARE RESULT</span>
            <h3>对比结果</h3>
          </div>
        </div>
        <div v-if="compare.runResult" class="grid-result-body">
          <p class="grid-provenance">
            <i data-lucide="database" aria-hidden="true"></i
            >{{ compare.runResult.barCount }} 个交易日 · {{ compare.runResult.dataSource === 'local' ? '本地缓存' : '实时拉取' }} · 数据截止
            {{ compare.runResult.dataAsOf || '--' }}
          </p>
          <p class="heading-note">
            <span class="signal-chip signal-chip-watch">网格区间为样本内自动建议，结果偏乐观</span>
          </p>
          <div class="table-responsive">
            <table class="data-table">
              <thead>
                <tr>
                  <th>策略</th>
                  <th class="text-end">区间收益</th>
                  <th class="text-end">年化</th>
                  <th class="text-end">超额</th>
                  <th class="text-end">回撤</th>
                  <th class="text-end">夏普</th>
                  <th class="text-end">胜率</th>
                  <th class="text-end">成交</th>
                  <th class="text-end">费用</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in compare.runResult.results" :key="item.strategyType">
                  <td>{{ item.label }}</td>
                  <template v-if="!item.error">
                    <td class="text-end" :class="[trendClass(item.metrics?.returnPct), { 'is-best': compare.isBest(item, 'returnPct', 'max') }]">
                      {{ formatPct(item.metrics?.returnPct) }}
                    </td>
                    <td class="text-end" :class="{ 'is-best': compare.isBest(item, 'annualizedReturnPct', 'max') }">
                      {{ item.metrics?.annualizedReturnPct != null ? item.metrics.annualizedReturnPct.toFixed(2) + '%' : '--' }}
                    </td>
                    <td class="text-end" :class="trendClass(item.metrics?.excessReturnPct)">
                      {{ formatPct(item.metrics?.excessReturnPct) }}
                    </td>
                    <td class="text-end" :class="{ 'is-best': compare.isBest(item, 'maxDrawdownPct', 'min') }">
                      {{ item.metrics?.maxDrawdownPct != null ? item.metrics.maxDrawdownPct.toFixed(2) + '%' : '--' }}
                    </td>
                    <td class="text-end">{{ item.metrics?.sharpeRatio != null ? item.metrics.sharpeRatio.toFixed(2) : '--' }}</td>
                    <td class="text-end">{{ item.metrics?.winRatePct != null ? item.metrics.winRatePct.toFixed(1) + '%' : '--' }}</td>
                    <td class="text-end">{{ item.metrics?.tradeCount ?? '--' }}</td>
                    <td class="text-end">{{ formatMoney(item.metrics?.totalFees) }}</td>
                  </template>
                  <td v-else colspan="8" class="compare-error-cell">失败：{{ item.error }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div class="grid-equity-chart" v-html="compare.runChartSvg"></div>
          <p v-for="item in compare.runResult.results" :key="'a-' + item.strategyType" class="heading-note grid-assumption">
            {{ item.label }}：{{ item.error || item.assumptions }}
          </p>
          <div class="compare-exports">
            <button class="text-button" type="button" @click="compare.exportRunCsv('metrics')"><i data-lucide="download" aria-hidden="true"></i>导出指标 CSV</button
            ><button class="text-button" type="button" @click="compare.exportRunCsv('curves')"><i data-lucide="download" aria-hidden="true"></i>导出曲线 CSV</button
            ><button class="text-button" type="button" @click="compare.exportRunCsv('trades')"><i data-lucide="download" aria-hidden="true"></i>导出成交 CSV</button>
          </div>
        </div>
        <div v-else class="empty-state">
          <i data-lucide="git-compare" aria-hidden="true"></i><strong>运行多策略对比</strong
          ><span>同一份历史日线在勾选的策略间重放，对比收益、回撤与夏普。</span>
        </div>
      </section>
    </div>
    <div v-if="strategyType === 'compare'" class="grid-lists">
      <section class="surface grid-candidates-panel">
        <div class="surface-heading">
          <div>
            <span class="section-kicker">SAVED COMPARISON</span>
            <h3>已保存策略对比</h3>
          </div>
          <span class="draft-status">已选 {{ compare.savedSelection.length }}/10</span>
        </div>
        <div v-if="compare.savedOptions.length" class="strategy-list">
          <div v-for="option in compare.savedOptions" :key="option.key" class="strategy-row">
            <div class="compare-saved-row">
              <input
                type="checkbox"
                :checked="compare.savedSelection.includes(option.key)"
                :aria-label="'选择 ' + option.name"
                @change="compare.toggleSaved(option.key)"
              /><div>
                <strong>{{ option.name }}</strong
                ><span>{{ option.code }} · {{ option.typeLabel }} · {{ option.status }}</span
                ><span v-if="option.lastBacktestAt">最近回测 {{ option.lastBacktestAt }}</span>
              </div>
            </div>
          </div>
          <div class="form-footer">
            <span class="form-footnote"><i data-lucide="info" aria-hidden="true"></i>对比为只读研究，不更新已存快照</span
            ><span
              ><button class="button button-secondary" type="button" :disabled="compare.savedLoading" @click="compare.compareSaved('snapshot')">
                对比快照</button
              ><button class="button button-primary" type="button" :disabled="compare.savedLoading" @click="compare.compareSaved('rerun')">
                {{ compare.savedLoading ? '正在回测，最长可能数十秒…' : '重新回测并对比' }}</button
              ></span
            >
          </div>
          <div v-if="compare.savedResult" class="table-responsive">
            <table class="data-table">
              <thead>
                <tr>
                  <th>策略</th>
                  <th>类型</th>
                  <th>代码</th>
                  <th class="text-end">区间收益</th>
                  <th class="text-end">超额</th>
                  <th class="text-end">回撤</th>
                  <th class="text-end">夏普</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="item in compare.savedResult.results" :key="item.id">
                  <td>{{ item.name || item.id }}</td>
                  <td>{{ item.strategyType || '--' }}</td>
                  <td>{{ item.code || '--' }}</td>
                  <template v-if="item.found && !item.error">
                    <td class="text-end">{{ formatPct(item.metrics?.returnPct ?? item.latestMetrics?.returnPct ?? null) }}</td>
                    <td class="text-end">{{ formatPct(item.metrics?.excessReturnPct ?? item.latestMetrics?.excessReturnPct ?? null) }}</td>
                    <td class="text-end">{{ item.metrics?.maxDrawdownPct ?? item.latestMetrics?.maxDrawdownPct != null ? ((item.metrics ?? item.latestMetrics).maxDrawdownPct.toFixed(2) + '%') : '--' }}</td>
                    <td class="text-end">{{ (item.metrics ?? item.latestMetrics)?.sharpeRatio != null ? (item.metrics ?? item.latestMetrics).sharpeRatio.toFixed(2) : '--' }}</td>
                    <td>
                      <span v-if="item.missingReason" class="signal-chip signal-chip-watch">{{ item.missingReason }}</span
                      ><span v-else class="signal-chip signal-chip-neutral">已载入</span>
                    </td>
                  </template>
                  <td v-else colspan="5">失败：{{ item.error || item.missingReason }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <div v-if="compare.savedResult" class="compare-exports">
            <button class="text-button" type="button" @click="compare.exportSavedCsv('metrics')"><i data-lucide="download" aria-hidden="true"></i>导出指标 CSV</button
            ><button v-if="compare.savedResult.rerun" class="text-button" type="button" @click="compare.exportSavedCsv('trades')">
              <i data-lucide="download" aria-hidden="true"></i>导出成交 CSV</button
            >
          </div>
        </div>
        <div v-else class="empty-state">
          <strong>暂无已保存策略</strong><span>先到上方运行回测并保存策略。</span>
        </div>
      </section>
    </div>
```

(c) script 接线（`<script setup>` 内追加导入与解构）：

```ts
import { COMPARE_STRATEGY_TYPES } from '@/modules/constants';
import { useCompareStore } from '@/stores/useCompareStore';
// ...既有导入不变

const compare = useCompareStore();
```

(d) 样式追加到 `frontend/src/styles.css` 末尾（checkbox 布局 + 最优高亮 + 导出行）：

```css
.compare-type-checks {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
}

.compare-type-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
}

.compare-saved-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.compare-error-cell {
  color: var(--danger, #dc2626);
}

.is-best {
  font-weight: 700;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.compare-exports {
  display: flex;
  gap: 12px;
  margin-top: 8px;
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run tests/frontend/ViewGrid.test.ts tests/frontend/useCompareStore.test.ts tests/frontend/csv.test.ts`
Expected: 全部 passed

Run: `npx vue-tsc --noEmit && npx eslint frontend/src --ext .ts,.vue`
Expected: 全绿

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/ViewGrid.vue frontend/src/styles.css tests/frontend/ViewGrid.test.ts
git commit -m "feat: ViewGrid 新增对比 tab——多策略横向对比与已保存策略对比 UI"
```

---

### Task 6: 全量回归 + 文档收口

**Files:**
- Modify: `AGENTS.md`（模块/测试计数）
- Modify: `ROADMAP.md`（勾选 + 交付摘要）
- Modify: `CHANGELOG.md`（v0.7.2 条目）

**Interfaces:** 无代码接口；纯文档与验证。

- [ ] **Step 1: 全量回归**

Run: `npm run verify`
Expected: vitest 全绿 + vue-tsc 全绿 + pytest 全绿（含覆盖率 ≥80% 门禁）。记录输出末尾的两行总数：后端 pytest `X passed`、前端 vitest `Y passed (Z files)`。

若有失败：修复后重跑，不得带红提交。

- [ ] **Step 2: 更新 AGENTS.md**

四处修改（计数用 Step 1 输出的实际值替换）：

1. stores 块：`stores/               12 个 Pinia 状态仓库` → `13 个`，并在 usePortfolioStore.ts 之后一行加 `      useCompareStore.ts    多策略回测对比（同标的横向对比 + 已保存策略快照/现跑）`。
2. modules 块：`assistCalc.ts（草案试算） / lucideIcons.ts（图标注册表）` 行追加 ` / csv.ts（对比 CSV 组装与公式注入防护）`。
3. tests/frontend 注释：`21 个 vitest 测试文件（共 236 项测试）` → `24 个 vitest 测试文件（共 <vitest 实际总数> 项测试）`。
4. 后端测试注释：`python -m pytest tests/ -v            # 后端测试（665 项，…）` → `（<pytest 实际总数> 项，…）`；并在测试文件清单 `test_source_guard.py` 行后加：
   `  test_strategy_compare.py  多策略对比：同 bars 重放/白名单上界/部分失败隔离/trades 不截断/快照与现跑零写库`

- [ ] **Step 3: 更新 ROADMAP.md**

把「研究体验」下的 `- [ ] P3 多策略回测对比 + CSV 导出` 改为：

```markdown
- [x] P3 多策略回测对比 + CSV 导出
  - 完成（2026-10-11）：`POST /api/strategy/compare`（同标的横向对比：一次取数、同 bars 重放 8 类策略、
    网格自动建议区间 + 引擎默认参数、单策略失败逐项披露、trades 全量不截断）+ `POST /api/strategy/compare-saved`
    （已保存策略对比：latestMetrics 快照为默认 + rerun 现跑，零写库不调度）+ ViewGrid「对比」tab
    （指标对比表最优高亮 + multiLineSvg 归一化叠图 + 已保存合并勾选）+ 客户端 CSV 三张导出
    （指标/曲线/成交，csvCell 公式注入防护）。已知限制：网格区间样本内自动建议偏乐观（脚注披露）；
    对比结果不落库刷新即失；rerun 不更新快照；snapshot 无成交明细可导。
    设计：`docs/superpowers/specs/2026-10-11-strategy-compare-csv-design.md`
```

- [ ] **Step 4: 更新 CHANGELOG.md**

在 `## [v0.7.1]` 之前插入：

```markdown
## [v0.7.2] - 2026-10-11

### 多策略回测对比 + CSV 导出（研究体验 P3）

- **`POST /api/strategy/compare`**：同标的横向对比。一次上游取数，同一份日线重放全部勾选策略（网格自动建议区间 8 格 classic + 7 个策略引擎 schema 默认参数）；单策略失败不拖垮整单（per-item `error`，HTTP 200）；trades 全量不截断（与单策略端点 `-100` 截断的有意差异）；顶层基准曲线仅一份；结构化日志 `strategy.compare`（耗时/状态/失败类型）。
- **`POST /api/strategy/compare-saved`**：已保存策略对比。snapshot 纯读库 `latestMetrics`（失效 id / 从未回测逐项如实披露）；rerun 按各自保存参数现跑（per-item `dataSource`/`dataAsOf` 降级披露）；**零写库**——不写 backtest 表、不更新 `latest_metrics`、不调度。
- **前端**：ViewGrid 新增第 9 个「对比」tab（策略类型勾选 + 指标对比表最优高亮 + `multiLineSvg` 归一化净值叠图 + 已保存策略合并勾选 ≤10）；新模块 `modules/csv.ts`（指标/曲线宽表/成交长表三张 CSV 组装，`csvCell` 对 `= + - @ \t \r` 开头字符串加 `'` 前缀防 Excel 公式注入，BOM + Blob 下载）；新 store `useCompareStore`。
- **测试**：新增 `tests/test_strategy_compare.py`（8 用例，含 rerun 零写库断言）+ 前端 3 个测试文件（csv 注入矩阵 / store / ViewGrid 冒烟）。
```

- [ ] **Step 5: 提交并核验 Git Flow 状态**

```bash
git add AGENTS.md ROADMAP.md CHANGELOG.md
git commit -m "docs: 收口多策略回测对比与 CSV 导出（AGENTS 模块计数/ROADMAP 勾选/CHANGELOG）"
git log --oneline -8
```

Expected: 8 个 feature 提交（spec 2 + 实现 4 + docs 1-2），工作树干净。

**后续（用户确认后执行，不在本计划内）：** `git flow feature finish strategy-compare-csv-export`（`--no-ff` 合入 develop）；发布时走 `git flow release start v0.7.2`。

---

## Self-Review 记录

1. **Spec 覆盖**：§3.1→Task 1；§3.2→Task 2；§3.3→Task 1 config/assumptions + Task 5 警示脚注；§3.4→Task 1/2 校验 + 测试；§3.5→两任务 except 链；§3.6→Task 1/2 schemas；§3.7→compare_logger 两处日志；§4.1→Task 5；§4.2→Task 4；§4.3→Task 3；§4.4→Task 5 v-html 仅 chart 输出；§5→Task 4 exportSavedCsv 按模式裁剪；§6→Task 3 METRIC_LABELS；§7→各任务测试 + Task 6 全量；§8/§9→Task 6 文档与验收。无缺口。
2. **占位符**：无 TBD/TODO；AGENTS 计数以「Step 1 实际输出替换」为准（数据依赖，非未实现内容）。
3. **类型一致性**：`csvCell/buildCsv/downloadCsv/buildCompare*MetricRow` 等命名在 Task 3/4/5 间逐字一致；store 导出 `toggleType/runCompare/toggleSaved/compareSaved/isBest/exportRunCsv/exportSavedCsv/runChartSvg/savedOptions/compareDraft/selectedTypes/savedSelection/runResult/savedResult` 与 Task 5 模板引用一致；后端 `CompareRunIn/Out`、`CompareSavedIn/Out` 与 app.py 导入一致。
