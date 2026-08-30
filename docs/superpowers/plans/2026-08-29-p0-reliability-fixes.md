# P0 可靠性修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复六角色头脑风暴确认的 5 个正确性/可靠性缺陷并清理废弃分支，不改变任何既有 API 字段名与产品行为。

**Architecture:** 全部改动落在 4 个热点文件（`backend/data_source.py`、`backend/grid_strategy.py`、`backend/app.py`+`backend/storage.py`、`frontend/app.js`+`index.html`）。后端测试延续本仓库"离线 + monkeypatch"模式——workspace 乐观锁的路由逻辑通过 monkeypatch `app_module` 中导入的存储函数测试，不触碰真实 PostgreSQL。前端无 JS 测试运行器，用 `node --check` + 手动浏览器验证。

**Tech Stack:** Python/FastAPI/SQLAlchemy 2.0（无 Alembic，走 `create_all` + `ALTER TABLE IF NOT EXISTS` 前向迁移）、pytest、Vue 3 全局构建（无打包器）、Node 内置 `node --check`。

## Global Constraints

- UI 文案一律中文；commit subject 用 Conventional Commits 前缀 + 中文（如 `fix: 修复选股器排序`）。
- 仓库强制 Git Flow：所有任务提交发生在 `feature/p0-reliability-fixes` 分支（off `develop`），禁止直接提交 `develop`/`main`。
- **绝不**用模拟值填补缺失数据；失败要显式暴露。
- 既有 API 字段名只增不改：新增 `revision`、`baseRevision`、`force`、`onePriceLimitUpDays`、`onePriceLimitDownDays`。
- 时间戳约定：机器时间用 `createdAtMs`（epoch 毫秒）。
- 测试必须离线：pytest 全部用 monkeypatch，不依赖 PostgreSQL/Redis/外网。
- harness 运行 git 命令偶发 `Access is denied`——遇此情况重试一次；仍失败则把命令与预期输出写进报告交用户执行。
- 规格：`docs/superpowers/specs/2026-08-29-p0-reliability-fixes-design.md`。

---

### Task 1: 分支准备与废弃分支清理

**Files:**
- 无文件改动（纯 git 操作）

**Interfaces:**
- Consumes: 无
- Produces: 干净的 `feature/p0-reliability-fixes` 分支（off `develop`）；已删除的 `.worktrees/unified-trading-desk` 与 `feature/unified-trading-desk`

- [x] **Step 1: 删除废弃 worktree 与分支（用户已在头脑风暴中明确批准放弃该分支）**

```bash
git worktree remove --force .worktrees/unified-trading-desk
git branch -D feature/unified-trading-desk
```

Expected: worktree 目录消失；`git branch -a` 中不再出现 `feature/unified-trading-desk`。若 git 命令报 `Access is denied`，重试一次；仍失败则报告用户手动执行。

- [x] **Step 2: 开启 Git Flow feature 分支**

```bash
git flow feature start p0-reliability-fixes
```

Expected: 输出显示基于 `develop` 创建并切换到 `feature/p0-reliability-fixes`。`git flow init` 需要干净工作树——当前工作树无未提交改动（设计文档已提交为 `ddd6ab1`），可直接执行。

---

### Task 2: 选股器涨跌幅排序修复

**Files:**
- Modify: `backend/data_source.py:300`（`load_screener` 内的 `rows.sort(...)` 一行）
- Test: `tests/test_backend_api.py`（文件末尾追加）

**Interfaces:**
- Consumes: `data_source.load_screener(market: str, page_size: int) -> dict`、`data_source.load_quotes(codes: list[str]) -> list[dict]`（测试中 monkeypatch 后者）
- Produces: 排序语义——有涨跌幅者在前按 `change` 降序（0.0 正确参与比较），无涨跌幅者殿后

- [x] **Step 1: 写失败测试**

在 `tests/test_backend_api.py` 末尾追加：

```python
def test_screener_sorts_zero_change_above_negative(monkeypatch):
    rows = [
        {"code": "600001", "name": "甲", "market": "沪深主板", "change": 0.0},
        {"code": "600002", "name": "乙", "market": "沪深主板", "change": 2.0},
        {"code": "600003", "name": "丙", "market": "沪深主板", "change": -1.0},
        {"code": "600004", "name": "丁", "market": "沪深主板", "change": None},
    ]
    monkeypatch.setattr(data_source, "load_quotes", lambda codes: rows)

    payload = data_source.load_screener("全部", page_size=20)

    assert [row["change"] for row in payload["rows"]] == [2.0, 0.0, -1.0, None]
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_backend_api.py::test_screener_sorts_zero_change_above_negative -v`
Expected: FAIL——实际顺序为 `[2.0, -1.0, 0.0, None]`（`0.0` 因 `or -999` 被当负值）。

- [x] **Step 3: 修复排序键**

在 `backend/data_source.py` 中找到（`load_screener` 内，约 300 行）：

```python
    rows.sort(key=lambda row: (row["change"] is not None, row["change"] or -999), reverse=True)
```

替换为：

```python
    rows.sort(key=lambda row: (row["change"] is not None, row["change"] if row["change"] is not None else -999), reverse=True)
```

- [x] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_backend_api.py::test_screener_sorts_zero_change_above_negative -v`
Expected: PASS

- [x] **Step 5: 提交**

```bash
git add backend/data_source.py tests/test_backend_api.py
git commit -m "fix: 修复选股器涨跌幅为零时排序错误"
```

---

### Task 3: 网格回测一字板三态处理

**Files:**
- Modify: `backend/grid_strategy.py`（`backtest_grid` 的日内循环头部、计数器初始化、`metrics` 字典、`assumptions` 文案）
- Test: `tests/test_grid_strategy.py`（文件末尾追加）

**Interfaces:**
- Consumes: `backtest_grid(bars, lower, upper, grid_count, capital, fee_bps, mode, security_type, exchange, settlement_days, slippage_bps, price_limit_pct) -> dict`（既有签名不变）
- Produces: `metrics` 新增 `onePriceLimitUpDays: int`、`onePriceLimitDownDays: int`；`assumptions` 字符串追加一字板披露句；停牌判定收窄为 `volume <= 0`（Task 4/8 无依赖，可并行）

- [x] **Step 1: 写三个失败测试**

在 `tests/test_grid_strategy.py` 末尾追加（若文件已有同名辅助函数则复用，勿重复定义）：

```python
def _make_bar(date, open_, high, low, close, volume):
    return {"date": date, "open": open_, "high": high, "low": low, "close": close, "volume": volume}


def test_one_price_limit_up_day_allows_sells_only():
    bars = [
        _make_bar("2026-01-01", 10.0, 10.0, 10.0, 10.0, 10000),
        _make_bar("2026-01-02", 11.0, 11.0, 11.0, 11.0, 4000),
    ]

    result = backtest_grid(bars, lower=9.0, upper=12.0, grid_count=3, capital=100000, mode="classic")
    metrics = result["metrics"]
    buys = [t for t in result["trades"] if t["side"] == "buy"]
    sells = [t for t in result["trades"] if t["side"] == "sell"]

    assert metrics["onePriceLimitUpDays"] == 1
    assert metrics["onePriceLimitDownDays"] == 0
    assert metrics["skippedSuspensionDays"] == 0
    assert len(sells) == 1
    assert sells[0]["price"] == 11.0
    assert not buys


def test_one_price_limit_down_day_allows_buys_only():
    bars = [
        _make_bar("2026-01-01", 10.0, 10.0, 10.0, 10.0, 10000),
        _make_bar("2026-01-02", 9.0, 9.0, 9.0, 9.0, 4000),
    ]

    result = backtest_grid(bars, lower=8.0, upper=12.0, grid_count=4, capital=100000, mode="classic")
    metrics = result["metrics"]
    buys = [t for t in result["trades"] if t["side"] == "buy"]
    sells = [t for t in result["trades"] if t["side"] == "sell"]

    assert metrics["onePriceLimitDownDays"] == 1
    assert metrics["onePriceLimitUpDays"] == 0
    assert metrics["skippedSuspensionDays"] == 0
    assert len(buys) == 1
    assert buys[0]["price"] == 9.0
    assert not sells


def test_zero_volume_day_is_still_suspension():
    bars = [
        _make_bar("2026-01-01", 10.0, 10.0, 10.0, 10.0, 10000),
        _make_bar("2026-01-02", 10.0, 10.0, 10.0, 10.0, 0),
    ]

    result = backtest_grid(bars, lower=9.0, upper=11.0, grid_count=2, capital=100000, mode="classic")
    metrics = result["metrics"]

    assert metrics["skippedSuspensionDays"] == 1
    assert metrics["onePriceLimitUpDays"] == 0
    assert metrics["onePriceLimitDownDays"] == 0
    assert result["trades"] == []
```

语义注记（测试构造依据）：一字涨停日 `low(11) >= prev(10)×1.1 - 0.005` 满足既有 `limit_up` 判定，买入被既有规则清空，修复点仅是这一天不再整日跳过，于是初始持仓在网格位 11 上成交卖出（执行价 `max(low=11, 11×(1-滑点)) = 11.0`）；一字跌停日对称。

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_grid_strategy.py -k one_price or -k zero_volume -v`
Expected: FAIL——`KeyError: 'onePriceLimitUpDays'`（新计数器尚不存在）。

- [x] **Step 3: 实现**

3a. 在 `backtest_grid` 中找到计数器初始化（约 111-113 行）：

```python
    skipped_limit_up_days = 0
    skipped_limit_down_days = 0
    skipped_suspension_days = 0
```

替换为：

```python
    skipped_limit_up_days = 0
    skipped_limit_down_days = 0
    skipped_suspension_days = 0
    one_price_limit_up_days = 0
    one_price_limit_down_days = 0
```

3b. 找到日内循环头部（约 115-129 行）：

```python
    for day_index, bar in enumerate(bars[1:], start=1):
        low = float(bar.get("low") or bar["close"])
        high = float(bar.get("high") or bar["close"])
        close = float(bar["close"])
        if high <= low or (bar.get("volume") is not None and float(bar["volume"]) <= 0):
            skipped_suspension_days += 1
            equity_curve.append(cash + shares * close)
            previous_close = close
            continue
        upper_limit = previous_close * (1 + price_limit_pct)
        lower_limit = previous_close * (1 - price_limit_pct)
        limit_up = high >= upper_limit - 0.005
        limit_down = low <= lower_limit + 0.005
        skipped_limit_up_days += int(limit_up)
        skipped_limit_down_days += int(limit_down)
```

替换为：

```python
    for day_index, bar in enumerate(bars[1:], start=1):
        low = float(bar.get("low") or bar["close"])
        high = float(bar.get("high") or bar["close"])
        close = float(bar["close"])
        volume = bar.get("volume")
        if volume is not None and float(volume) <= 0:
            skipped_suspension_days += 1
            equity_curve.append(cash + shares * close)
            previous_close = close
            continue
        upper_limit = previous_close * (1 + price_limit_pct)
        lower_limit = previous_close * (1 - price_limit_pct)
        limit_up = high >= upper_limit - 0.005
        limit_down = low <= lower_limit + 0.005
        if high == low:
            # 一字板：涨停只可卖、跌停只可买。既有 limit_up/limit_down 清空规则
            # 已保证这一语义，此处只负责准确计数。
            if limit_up:
                one_price_limit_up_days += 1
            elif limit_down:
                one_price_limit_down_days += 1
        skipped_limit_up_days += int(limit_up)
        skipped_limit_down_days += int(limit_down)
```

（循环其余部分——买卖触发、成交、权益曲线——保持不变。）

3c. 在 `metrics` 字典中，`"skippedSuspensionDays": skipped_suspension_days,` 之后追加两行：

```python
        "onePriceLimitUpDays": one_price_limit_up_days,
        "onePriceLimitDownDays": one_price_limit_down_days,
```

3d. 找到 `assumptions` 返回值（约 235-236 行）：

```python
        "assumptions": ("经典网格按日内先低后高触发；趋势网格按日内先高后低触发。"
                        f"按 100 股整数倍、T+{settlement_days} 可卖、{slippage_bps} BP 滑点和股票/ETF差异化费用计算。"),
```

替换为：

```python
        "assumptions": ("经典网格按日内先低后高触发；趋势网格按日内先高后低触发。"
                        f"按 100 股整数倍、T+{settlement_days} 可卖、{slippage_bps} BP 滑点和股票/ETF差异化费用计算。"
                        "一字涨停日仅可卖出、一字跌停日仅可买入，停牌日整日跳过。"),
```

- [x] **Step 4: 运行新测试确认通过**

Run: `python -m pytest tests/test_grid_strategy.py -k one_price or -k zero_volume -v`
Expected: 3 个测试全部 PASS

- [x] **Step 5: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS（既有 T+1/费用/滑点/涨跌停用例不受影响）

- [x] **Step 6: 提交**

```bash
git add backend/grid_strategy.py tests/test_grid_strategy.py
git commit -m "fix: 网格回测区分一字板与停牌并新增计数指标"
```

---

### Task 4: workspace 乐观锁后端

**Files:**
- Modify: `backend/storage.py`（新增 `WorkspaceState` 模型 + `get_workspace_revision`；`get_workspace`/`save_workspace` 接入 revision）
- Modify: `backend/app.py:80-85`（`PUT /api/workspace` 路由）
- Test: `tests/test_backend_api.py`（文件末尾追加）

**Interfaces:**
- Consumes: 既有 `save_workspace(payload, workspace_id) -> dict`、`get_workspace(workspace_id) -> dict` 签名不变
- Produces:
  - `backend.storage.get_workspace_revision(workspace_id: str = "default") -> int`
  - `GET /api/workspace` 响应新增 `revision: int`
  - `PUT /api/workspace?baseRevision=<int>&force=<bool>`：`baseRevision` 与当前不符且未 `force` → 409，响应体 `{"detail": {"error": str, "revision": int, "workspace": dict}}`；成功响应含自增后的 `revision`
  - Task 6（前端）依赖以上契约

- [x] **Step 1: 写失败测试**

在 `tests/test_backend_api.py` 末尾追加。注意：路由代码尚未引用新函数，前两条用 `raising=False` 允许 monkeypatch 尚不存在的属性。

```python
def test_workspace_get_includes_revision(monkeypatch):
    monkeypatch.setattr(
        app_module, "get_workspace",
        lambda workspace_id="default": {"watchlist": ["600519"], "plans": [], "alerts": [], "revision": 3},
        raising=False,
    )

    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/workspace")

    assert response.status_code == 200
    assert response.json()["revision"] == 3


def test_workspace_put_rejects_stale_revision_with_409(monkeypatch):
    monkeypatch.setattr(app_module, "get_workspace_revision", lambda workspace_id="default": 7, raising=False)
    monkeypatch.setattr(
        app_module, "get_workspace",
        lambda workspace_id="default": {"watchlist": [], "plans": [], "alerts": [], "revision": 7},
        raising=False,
    )
    saved = {}

    def fake_save(payload, workspace_id="default"):
        saved["payload"] = payload
        return {"watchlist": payload.get("watchlist", []), "plans": [], "alerts": [], "revision": 8}

    monkeypatch.setattr(app_module, "save_workspace", fake_save, raising=False)

    with TestClient(app_module.create_app()) as client:
        response = client.put(
            "/api/workspace?baseRevision=6",
            json={"watchlist": ["600519"], "plans": [], "alerts": []},
        )

    assert response.status_code == 409
    body = response.json()
    assert body["detail"]["revision"] == 7
    assert body["detail"]["workspace"]["revision"] == 7
    assert "payload" not in saved


def test_workspace_put_with_matching_revision_saves(monkeypatch):
    monkeypatch.setattr(app_module, "get_workspace_revision", lambda workspace_id="default": 7, raising=False)
    monkeypatch.setattr(
        app_module, "get_workspace",
        lambda workspace_id="default": {"watchlist": [], "plans": [], "alerts": [], "revision": 7},
        raising=False,
    )

    def fake_save(payload, workspace_id="default"):
        return {"watchlist": payload.get("watchlist", []), "plans": [], "alerts": [], "revision": 8}

    monkeypatch.setattr(app_module, "save_workspace", fake_save, raising=False)

    with TestClient(app_module.create_app()) as client:
        response = client.put(
            "/api/workspace?baseRevision=7",
            json={"watchlist": ["600519"], "plans": [], "alerts": []},
        )

    assert response.status_code == 200
    assert response.json()["revision"] == 8


def test_workspace_put_with_force_overrides_stale_revision(monkeypatch):
    monkeypatch.setattr(app_module, "get_workspace_revision", lambda workspace_id="default": 7, raising=False)
    monkeypatch.setattr(
        app_module, "get_workspace",
        lambda workspace_id="default": {"watchlist": [], "plans": [], "alerts": [], "revision": 7},
        raising=False,
    )

    def fake_save(payload, workspace_id="default"):
        return {"watchlist": payload.get("watchlist", []), "plans": [], "alerts": [], "revision": 8}

    monkeypatch.setattr(app_module, "save_workspace", fake_save, raising=False)

    with TestClient(app_module.create_app()) as client:
        response = client.put(
            "/api/workspace?baseRevision=6&force=true",
            json={"watchlist": ["600519"], "plans": [], "alerts": []},
        )

    assert response.status_code == 200
    assert response.json()["revision"] == 8
```

- [x] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_backend_api.py -k workspace_put or -k workspace_get -v`
Expected: 至少 `test_workspace_get_includes_revision` FAIL（响应无 `revision` 键）；PUT 系列因路由未处理 `baseRevision` 而失败或 503。

- [x] **Step 3: 实现 storage.py**

3a. 在 `WorkspaceSettings` 模型类之后追加新模型：

```python
class WorkspaceState(Base):
    __tablename__ = "workspace_state"

    workspace_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
```

（新表由 `initialize_storage()` 既有的 `Base.metadata.create_all(engine)` 自动创建，无需 ALTER。）

3b. 在 `get_workspace` 定义之前追加：

```python
def get_workspace_revision(workspace_id: str = "default") -> int:
    with SessionLocal() as session:
        row = session.get(WorkspaceState, workspace_id)
        return int(row.revision) if row else 0
```

3c. `get_workspace` 的返回语句由：

```python
        return {"watchlist": watchlist, "plans": [_plan_dict(plan) for plan in plans], "alerts": [_alert_dict(alert) for alert in alerts]}
```

改为：

```python
        return {
            "watchlist": watchlist,
            "plans": [_plan_dict(plan) for plan in plans],
            "alerts": [_alert_dict(alert) for alert in alerts],
            "revision": get_workspace_revision(workspace_id),
        }
```

3d. 在 `save_workspace` 与 `get_workspace` 之间追加内部辅助：

```python
def _bump_workspace_revision(session, workspace_id: str) -> None:
    row = session.get(WorkspaceState, workspace_id)
    if row is None:
        session.add(WorkspaceState(workspace_id=workspace_id, revision=1))
    else:
        row.revision = int(row.revision) + 1
```

3e. `save_workspace` 中 `with SessionLocal.begin() as session:` 块的末尾（alerts 写入循环之后、块结束之前）追加一行：

```python
        _bump_workspace_revision(session, workspace_id)
```

（函数末尾 `return get_workspace(workspace_id)` 不变，其返回值现在自然携带自增后的 `revision`。）

- [x] **Step 4: 修改 app.py 路由**

4a. 顶部 `from backend.storage import (...)` 中追加导入 `get_workspace_revision`（字母序放在 `get_workspace_settings` 与 `get_grid_strategy` 之间即可）。

4b. `PUT /api/workspace` 路由（约 80-85 行）由：

```python
    @app.put("/api/workspace")
    def update_workspace(payload: dict = Body(...), workspace_id: str = Query(default="default", alias="workspace")):
        try:
            return save_workspace(payload, workspace_id)
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"error": f"持久化存储不可用: {exc}"}) from exc
```

改为：

```python
    @app.put("/api/workspace")
    def update_workspace(
        payload: dict = Body(...),
        workspace_id: str = Query(default="default", alias="workspace"),
        base_revision: int | None = Query(default=None, alias="baseRevision"),
        force: bool = Query(default=False),
    ):
        try:
            current = get_workspace_revision(workspace_id)
            if base_revision is not None and base_revision != current and not force:
                raise HTTPException(
                    status_code=409,
                    detail={"error": "其他页面已更新工作区数据", "revision": current, "workspace": get_workspace(workspace_id)},
                )
            return save_workspace(payload, workspace_id)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=503, detail={"error": f"持久化存储不可用: {exc}"}) from exc
```

- [x] **Step 5: 运行新测试确认通过**

Run: `python -m pytest tests/test_backend_api.py -k workspace_put or -k workspace_get -v`
Expected: 4 个测试全部 PASS

- [x] **Step 6: 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 全部 PASS

- [x] **Step 7: 提交**

```bash
git add backend/storage.py backend/app.py tests/test_backend_api.py
git commit -m "feat: workspace 同步增加版本乐观锁与 409 冲突契约"
```

---

### Task 5: 恢复前端轮询并发守卫

**Files:**
- Modify: `frontend/app.js`（`refreshAll` 函数，约 387-418 行）

**Interfaces:**
- Consumes: 无
- Produces: `refreshAll(options)` 在已有一次运行进行中时跳过 `silent` 调用（定时轮询路径）；用户主动调用（`options.silent` 非真）不受阻塞。本仓库无 JS 测试运行器，验证方式为 `node --check` + 手动验证

- [x] **Step 1: 修改 `refreshAll`**

在 `setup()` 内（`async function refreshAll` 之前）加一行模块级状态（与 `let workspaceSyncInFlight = false;` 等既有写法一致）：

```js
    let refreshInFlight = false;
```

将整个 `refreshAll` 函数替换为（函数体逻辑不变，仅加守卫并把收尾移入 `finally`）：

```js
    async function refreshAll(options = {}) {
      const silent = Boolean(options.silent);
      if (refreshInFlight) {
        // 已有刷新进行中：定时轮询直接跳过，避免慢网络下请求堆积。
        if (silent) return;
      }
      if (!silent) loading.value = true;
      refreshInFlight = true;
      try {
        errorMessage.value = '';
        const tasks = [fetchMarket(), fetchScreener()];
        const now = Date.now();
        if (!indexHistory.value.length || now - indexHistoryFetchedAt.value > 60000) {
          tasks.push(fetchHistory('000001', 'index'));
        }
        if (!selectedHistory.value.length || selectedHistoryCode.value !== selectedCode.value || now - selectedHistoryFetchedAt.value > 60000) {
          tasks.push(fetchHistory(selectedCode.value, 'selected'));
        }
        const results = await Promise.allSettled(tasks);
        const failures = results.filter((result) => result.status === 'rejected');
        if (failures.length && !market.quotes.length && !screenRows.value.length) {
          dataState.value = 'error';
          errorMessage.value = failures[0].reason?.message || '真实行情暂时不可用';
        } else if (failures.length) {
          dataState.value = 'stale';
          errorMessage.value = '行情接口部分失败，当前页面保留最近一次成功数据。';
        } else {
          dataState.value = 'live';
        }
        if (market.errors.length && !errorMessage.value) {
          errorMessage.value = '部分股票报价暂时不可用，已保留其他实时结果。';
        }
        expirePlans();
        if (failures.length === 0) persist();
      } finally {
        refreshInFlight = false;
        loading.value = false;
        await nextTick();
        renderIcons();
      }
    }
```

（注：按规格约定，守卫只跳过 `silent` 调用；用户主动刷新始终执行，两次用户刷新极端情况下可能短暂并发，属可接受行为。）

- [x] **Step 2: 语法检查**

Run: `node --check frontend/app.js`
Expected: 无输出（语法通过）

- [x] **Step 3: 手动验证**

浏览器打开 <http://127.0.0.1:4173>，设置刷新间隔为 5 秒并保存；DevTools Network 面板确认 `/api/market`、`/api/screener` 请求不重叠（上一个完成后才发起下一个）。

- [x] **Step 4: 提交**

```bash
git add frontend/app.js
git commit -m "fix: 恢复 refreshAll 轮询并发守卫"
```

---

### Task 6: 前端 workspace 乐观锁接入与冲突横幅

**Files:**
- Modify: `frontend/app.js`（`requestJson`、状态声明区、`persist`、`loadWorkspace`、`scheduleWorkspaceSync`、新增冲突处理函数、`return` 导出区）
- Modify: `frontend/index.html`（第 14 行 `<div id="app" ...>` 之后插入横幅）
- Modify: `frontend/styles.css`（文件末尾追加横幅样式）

**Interfaces:**
- Consumes: Task 4 的 API 契约——GET/PUT 响应含 `revision`；409 响应体 `payload.detail = {error, revision, workspace}`；`force=true` 查询参数
- Produces: `workspaceRevision`（当前已知版本号，持久化到 localStorage）、`conflictVisible`、`adoptServerWorkspace()`、`forceSaveWorkspace()`（index.html 横幅绑定这三个名字）

- [x] **Step 1: `requestJson` 保留状态码与响应体**

将（约 248-259 行）：

```js
    async function requestJson(url, options = {}) {
      const response = await fetch(url, {
        cache: 'no-store',
        ...options,
        headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) }
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail?.error || payload.error || `接口返回 ${response.status}`);
      }
      return payload;
    }
```

改为：

```js
    async function requestJson(url, options = {}) {
      const response = await fetch(url, {
        cache: 'no-store',
        ...options,
        headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) }
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(payload.detail?.error || payload.error || `接口返回 ${response.status}`);
        error.status = response.status;
        error.payload = payload;
        throw error;
      }
      return payload;
    }
```

- [x] **Step 2: 新增状态**

在 `const workspaceSynced = ref(false);`（约 50 行）之后追加：

```js
    const workspaceRevision = ref(Number(saved.workspaceRevision) || 0);
    const conflictVisible = ref(false);
    const conflictSnapshot = ref(null);
```

- [x] **Step 3: `persist` 记录版本号**

在 `persist()` 的 `localStorage.setItem(STORAGE_KEY, JSON.stringify({ ... }))` 对象中、`monitorEnabled: monitorEnabled.value,` 之后加一行：

```js
          workspaceRevision: workspaceRevision.value,
```

- [x] **Step 4: `loadWorkspace` 记录服务器版本**

将 `loadWorkspace` 中（约 300-313 行）：

```js
        const remote = await requestJson('/api/workspace');
        const hasRemoteData = (remote.watchlist || []).length || (remote.plans || []).length || (remote.alerts || []).length;
```

改为：

```js
        const remote = await requestJson('/api/workspace');
        workspaceRevision.value = Number(remote.revision || 0);
        const hasRemoteData = (remote.watchlist || []).length || (remote.plans || []).length || (remote.alerts || []).length;
```

- [x] **Step 5: `scheduleWorkspaceSync` 携带版本并处理 409**

将其中 `await requestJson('/api/workspace', {...})` 一段（约 283-296 行）：

```js
          await requestJson('/api/workspace', {
            method: 'PUT',
            body: JSON.stringify(workspacePayload())
          });
        } catch (error) {
          // Browser storage remains a fallback while the persistence service reconnects.
        } finally {
```

改为：

```js
          await requestJson(`/api/workspace?baseRevision=${encodeURIComponent(workspaceRevision.value)}`, {
            method: 'PUT',
            body: JSON.stringify(workspacePayload())
          });
        } catch (error) {
          if (error.status === 409 && error.payload?.detail?.workspace) {
            // 版本冲突不自动重试，交给用户在横幅中决策，避免覆盖任何一端数据。
            workspaceSyncQueued = false;
            showConflictBanner(error.payload.detail.workspace);
          }
          // 其余失败仍静默降级：浏览器存储兜底，等待持久化服务恢复。
        } finally {
```

- [x] **Step 6: 新增冲突处理函数**

在 `scheduleWorkspaceSync` 函数之后追加：

```js
    function showConflictBanner(snapshot) {
      conflictSnapshot.value = snapshot;
      conflictVisible.value = true;
      showToast('其他页面已更新工作区数据，请选择保留哪一版', 'error');
    }

    async function adoptServerWorkspace() {
      const snapshot = conflictSnapshot.value;
      conflictVisible.value = false;
      if (!snapshot) return;
      watchlistCodes.value = snapshot.watchlist || [];
      plans.value = snapshot.plans || [];
      alerts.value = snapshot.alerts || [];
      workspaceRevision.value = Number(snapshot.revision || 0);
      persist();
      showToast('已采用服务器最新数据');
    }

    async function forceSaveWorkspace() {
      conflictVisible.value = false;
      try {
        const saved = await requestJson('/api/workspace?force=true', {
          method: 'PUT',
          body: JSON.stringify(workspacePayload())
        });
        workspaceRevision.value = Number(saved.revision || 0);
        persist();
        showToast('已用本地数据覆盖服务器');
      } catch (error) {
        showToast(error.message || '覆盖失败', 'error');
      }
    }
```

- [x] **Step 7: 导出新绑定**

在 `setup()` 的 `return { ... }` 导出对象中、`monitorEnabled,`（约 997 行）之后追加三行（index.html 横幅通过 `v-if` 与 `@click` 绑定这三个名字，缺一即运行时报错）：

```js
      conflictVisible,
      adoptServerWorkspace,
      forceSaveWorkspace,
```

- [x] **Step 8: index.html 插入横幅**

在第 14 行 `<div id="app" v-cloak class="app-shell">` 之后（`<aside class="sidebar">` 之前）插入：

```html
    <div v-if="conflictVisible" class="conflict-banner" role="alert">
      <i data-lucide="triangle-alert" aria-hidden="true"></i>
      <span>检测到其他页面更新了工作区数据</span>
      <button class="button button-secondary" type="button" @click="adoptServerWorkspace">采用服务器版本</button>
      <button class="button button-primary" type="button" @click="forceSaveWorkspace">用本地覆盖</button>
      <button class="icon-button" type="button" aria-label="忽略冲突提示" @click="conflictVisible = false"><i data-lucide="x" aria-hidden="true"></i></button>
    </div>
```

- [x] **Step 9: styles.css 追加横幅样式**

文件末尾追加（使用显式色值，不引入新的设计令牌）：

```css
/* Workspace conflict banner (multi-tab revision conflict) */
.conflict-banner {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 80;
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 16px;
  border-radius: 12px;
  background: #16223a;
  border: 1px solid #ef6d53;
  color: #eef2f8;
  box-shadow: 0 12px 32px rgba(8, 12, 22, 0.35);
}

.conflict-banner svg { color: #ef6d53; }
```

- [x] **Step 10: 语法检查与手动验证**

Run: `node --check frontend/app.js`
Expected: 无输出（语法通过）

浏览器双标签页验证（需 `python server.py` 与 PostgreSQL 可用）：
1. 两个窗口各打开 <http://127.0.0.1:4173>；
2. 窗口 A 加入一只自选股，等待 1 秒（350ms debounce + 请求完成）；
3. 窗口 B 加入另一只自选股；
4. B 应出现红色横幅"检测到其他页面更新了工作区数据"；
5. 点击"采用服务器版本"→ B 的自选与 A 一致，无后续冲突；
6. 重复 2-4 后改点"用本地覆盖"→ B 的自选生效于服务器，A 刷新后与 B 一致；
7. 点击"忽略"→ 横幅关闭且不发起任何写入。

- [x] **Step 11: 提交**

```bash
git add frontend/app.js frontend/index.html frontend/styles.css
git commit -m "feat: 工作区同步接入乐观锁与冲突提示横幅"
```

---

### Task 7: 交易计划持久化文案修正

**Files:**
- Modify: `frontend/index.html:517`（计划表单 footer 的 `form-footnote`）

**Interfaces:**
- Consumes: 无
- Produces: 与实际行为一致的文案（计划已双写本地与 PostgreSQL）

- [x] **Step 1: 修改文案**

将：

```html
<span class="form-footnote"><i data-lucide="lock-keyhole" aria-hidden="true"></i>计划只保存在本地浏览器</span>
```

改为：

```html
<span class="form-footnote"><i data-lucide="cloud-check" aria-hidden="true"></i>计划保存在本地浏览器与服务器，换设备打开自动同步</span>
```

- [x] **Step 2: 验证**

Run: 搜索确认旧文案不存在、新文案存在：`Select-String -Path frontend\index.html -Pattern "计划保存在本地浏览器与服务器"`
Expected: 命中 1 处；手动浏览器检查 plans 页脚显示正常、图标渲染（`cloud-check` 是 lucide 有效图标名；若渲染为空白则改用 `cloud`）。

- [x] **Step 3: 提交**

```bash
git add frontend/index.html
git commit -m "fix: 修正交易计划保存位置文案"
```

---

### Task 8: AGENTS.md 补记与收尾

**Files:**
- Modify: `AGENTS.md`（Key Conventions 一节追加两条约定）
- 无代码改动

**Interfaces:**
- Consumes: Task 3-6 的最终行为
- Produces: 文档与实现一致；feature 分支合入 develop

- [x] **Step 1: AGENTS.md 追加约定**

在 Key Conventions / Rules 列表中、`- **Frontend polling** ...` 一条之后追加：

```markdown
- **Workspace sync is revision-locked:** `GET /api/workspace` returns `revision`; `PUT /api/workspace` accepts `baseRevision` (conflict → 409 with the server snapshot in `detail.workspace`) and `force=true` to override. The frontend keeps the latest known `revision` in `workspaceRevision` and surfaces 409 via the conflict banner with "采用服务器版本" / "用本地覆盖" actions — never auto-retry a 409.
- **Grid backtest day classification:** suspension = `volume <= 0` only. A one-price day (`high == low`, volume > 0) at limit-up is tradeable for sells only; at limit-down, buys only. Counters: `onePriceLimitUpDays` / `onePriceLimitDownDays` (new metrics fields, additive).
```

- [x] **Step 2: 全量回归**

Run: `python -m pytest tests/ -v` 与 `node --check frontend/app.js`
Expected: 全部 PASS / 语法通过

- [x] **Step 3: 提交文档**

```bash
git add AGENTS.md
git commit -m "docs: 补记 workspace 乐观锁与一字板语义约定"
```

- [x] **Step 4: 完成 feature 分支**

```bash
git flow feature finish p0-reliability-fixes
```

Expected: `--no-ff` 合入 `develop`，分支删除。若 git 报 `Access is denied`，重试一次；仍失败则报告用户手动执行。

---

## Self-Review 记录

- **Spec coverage**：规格 7 项目标 → Task 1（废弃分支清理）、Task 2（排序）、Task 3（一字板 + assumptions + 新指标）、Task 4+6（乐观锁后端/前端）、Task 7（文案）、Task 5+8（AGENTS.md 同步：refreshInFlight 恢复后文档描述自动为真，新增两条约定）。无遗漏。
- **Placeholder scan**：所有代码步骤含完整可粘贴代码；无 TBD/"适当处理"类占位。
- **Type consistency**：`get_workspace_revision` 在 Task 3b/4b 与测试 monkeypatch 名一致；`baseRevision`/`force` 查询参数与前端 URL 拼接一致；`onePriceLimitUpDays`/`onePriceLimitDownDays` 在测试、metrics、AGENTS.md 三处拼写一致；`conflictVisible`/`adoptServerWorkspace`/`forceSaveWorkspace` 在 app.js return 与 index.html 绑定一致。
