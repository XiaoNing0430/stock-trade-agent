# MarketBar 本地日线历史读取路径实施计划

> **For agentic workers:** Use superpowers:executing-plans (inline) to implement this plan task-by-task.

**Goal:** 上游行情 API 失败时，走势图 (`/api/history`) 与网格回测/预览降级读取 PostgreSQL `market_bars` 表持久化的历史日线，响应加 `dataSource` 字段诚实地披露来源。

**Architecture:** storage.py 新增 `load_market_bars`；app.py 抽 `_load_history_with_fallback` 供三个端点复用；前端 fetchHistory 读取 `dataSource` 标记，gridProvenance 来源动态切换。

**Tech Stack:** FastAPI + SQLAlchemy, Vue 3 全局构建。验证：pytest（TDD）+ `node --check` + 浏览器手动。

---

### Task 1: 分支准备

- [x] `git flow feature start marketbar-local-read`

---

### Task 2: 后端（TDD）

**Files:** `backend/storage.py`, `backend/app.py`, `tests/test_backend_api.py`

- [x] **Step 1: 先写失败测试**

`tests/test_backend_api.py` 追加：

```python
def test_load_market_bars_returns_bars_ordered(monkeypatch):
    from backend.storage import load_market_bars, save_market_bars

    bars = [{"date": "2026-08-28", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "amount": 10000},
            {"date": "2026-08-29", "open": 10.5, "high": 12, "low": 10, "close": 11, "volume": 2000, "amount": 22000}]
    save_market_bars("600999", bars)
    loaded = load_market_bars("600999", limit=10)
    assert len(loaded) == 2
    assert loaded[0]["date"] == "2026-08-28"
    assert loaded[1]["date"] == "2026-08-29"
    assert "fetchedAt" in loaded[0]


def test_load_market_bars_returns_empty_when_none():
    from backend.storage import load_market_bars

    assert load_market_bars("nonexistent") == []


def test_fallback_serves_local_when_upstream_fails(monkeypatch):
    from backend import app as app_module
    from fastapi.testclient import TestClient
    from backend import data_source
    from backend.storage import save_market_bars

    # 灌入本地数据
    save_market_bars("600999", [{"date": "2026-08-28", "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 1000, "amount": 10000}])
    # 让 load_history 抛异常
    monkeypatch.setattr(data_source, "load_history", lambda code, limit=120, is_index=False: (_ for _ in ()).throw(ConnectionError("upstream down")))
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/history?code=600999")
    assert response.status_code == 200
    data = response.json()
    assert data["dataSource"] == "local"
    assert len(data["history"]) == 1
    assert data["history"][0]["date"] == "2026-08-28"


def test_fallback_raises_when_no_local_data(monkeypatch):
    from backend import app as app_module
    from fastapi.testclient import TestClient
    from backend import data_source
    from backend.storage import load_market_bars

    monkeypatch.setattr(data_source, "load_history", lambda code, limit=120, is_index=False: (_ for _ in ()).throw(ConnectionError("upstream down")))
    monkeypatch.setattr("backend.app.load_market_bars", lambda code, adjustment="qfq", limit=240: [])
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/history?code=absent")
    assert response.status_code == 502
```

- [x] **Step 2: 跑测试确认红**

`python -m pytest tests/test_backend_api.py -q`

- [x] **Step 3: 实现**

`backend/storage.py` 追加：

```python
def load_market_bars(code: str, adjustment: str = "qfq", limit: int = 240) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(MarketBar)
            .where(MarketBar.code == code, MarketBar.adjustment == adjustment)
            .order_by(MarketBar.trade_date.desc())
            .limit(limit)
        ).all()
        if not rows:
            return []
        return sorted([
            {
                "date": row.trade_date,
                "open": row.open,
                "high": row.high,
                "low": row.low,
                "close": row.close,
                "volume": row.volume,
                "amount": row.amount,
                "fetchedAt": row.fetched_at.isoformat() if row.fetched_at else None,
            }
            for row in rows
        ], key=lambda r: r["date"])
```

`backend/app.py` 追加 helper（`save_market_bars` import 行附近可确认已导入 `load_market_bars`）：

```python
def _load_history_with_fallback(code: str, limit: int, is_index: bool = False) -> tuple[list, str, str | None]:
    try:
        history = load_history(code, limit=limit, is_index=is_index)
        data_as_of = save_market_bars(code, history)
        return history, "live", data_as_of
    except Exception:
        bars = load_market_bars(code, limit=limit)
        if not bars:
            raise
        data_as_of = bars[-1]["date"]
        return bars, "local", data_as_of
```

`/api/history` 端点改为：

```python
    @app.get("/api/history")
    def history(code: str = Query(default="600519"), index: bool = Query(default=False)):
        try:
            history, data_source, data_as_of = _load_history_with_fallback(code, 120, is_index=index)
            return {
                "code": code,
                "provider": "Tencent public quote API",
                "fetchedAt": int(time.time() * 1000),
                "history": history,
                "dataSource": data_source,
                "dataAsOf": data_as_of,
            }
        except Exception as exc:
            raise HTTPException(status_code=502, detail={"error": str(exc), "provider": "Tencent public quote API"})
```

`/api/grid/preview` 对应的 `data_as_of = save_market_bars(...)` 处改为 `history, data_source, data_as_of = _load_history_with_fallback(code, limit)`，响应加 `"dataSource": data_source`。

`/api/grid/backtest` 同理。

- [x] **Step 4: 跑测试确认绿 + 提交**

`python -m pytest tests/ -q` → 全绿。

```bash
git add backend/storage.py backend/app.py tests/
git commit -m "feat: 上游失败时走势图与回测降级读本地缓存库"
```

---

### Task 3: 前端 dataSource 消费

**Files:** `frontend/app.js`, `frontend/index.html`

- [x] **Step 1: app.js 状态与 fetchHistory**

`dataState` 附近加 `const chartDataSource = ref('live');`；return 导出。

`fetchHistory` 改为：

```js
    async function fetchHistory(code, type = 'selected') {
      const isIndex = type === 'index';
      const payload = await requestJson(`/api/history?code=${encodeURIComponent(code)}${isIndex ? '&index=1' : ''}`);
      if (isIndex) {
        indexHistory.value = payload.history || [];
        indexHistoryFetchedAt.value = Date.now();
      } else {
        selectedHistory.value = payload.history || [];
        selectedHistoryCode.value = code;
        selectedHistoryFetchedAt.value = Date.now();
      }
      chartDataSource.value = payload.dataSource === 'local' ? 'local' : 'live';
    }
```

- [x] **Step 2: gridProvenance 来源动态**

`gridProvenance` computed 中 `来源 ${providerLabel.value}` 改为：

```js
        const src = result.dataSource === 'local' ? '本地缓存' : providerLabel.value;
        `来源 ${src}`,
```

- [x] **Step 3: index.html 走势图来源标签**

走势图 `view-panel` 内（`selectedCode` 附近）加来源标签（`v-if="selectedCode"` 区域内）：

```html
<span v-if="chartDataSource === 'local'" class="source-badge source-badge-local">本地缓存</span>
<span v-else class="source-badge">实时·腾讯</span>
```

样式复用 `.source-badge`（若 P1 已有类似 badge 样式）或新增：

```css
.source-badge { font-size: 11px; padding: 2px 8px; border-radius: 999px; background: var(--green-soft); color: var(--green); }
.source-badge-local { background: var(--gold-soft); color: var(--gold); }
```

- [x] **Step 4: 版本号 + 验证 + 提交**

`index.html` app.js `?v=20260829-6` → `?v=20260830-2`。`node --check`。

```bash
git add frontend/app.js frontend/index.html frontend/styles.css
git commit -m "feat: 前端消费本地缓存数据源标记并显示来源标签"
```

---

### Task 4: 回归、手动验证与收尾

- [x] **Step 1: 全量回归**

`python -m pytest tests/ -q` + `node --check frontend/app.js` → 全绿。

- [x] **Step 2: 浏览器验证**

- 断网 → 刷新走势图某只之前回测过的股票 → 走势图显示"本地缓存"角标；回测 provenance 行显示"来源 本地缓存"
- 联网 → 走势图显示"实时·腾讯"
- 新股票（无本地数据）断网 → 正常报错

- [x] **Step 3: 完成分支**

```bash
git flow feature finish marketbar-local-read
```