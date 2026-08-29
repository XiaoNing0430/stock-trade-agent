# 行情降级缓存兜底实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 上游行情接口失败时，`cached()` 回退返回服务器内存缓存的上次成功真实数据（`STALE_MAX_AGE=1800` 硬顶），`/api/*` 响应经 middleware 加 `X-Atlas-Stale` 响应头披露；前端据此置 `dataState=stale` 并入收件箱，恢复后回 `live`。

**Architecture:** 后端 data_source.py 改 `cached()` + 全局降级标记；app.py 加 middleware；前端 requestJson 读响应头 + refreshAll 状态机并入。零响应体结构变更，零新路由。

**Tech Stack:** FastAPI + SQLAlchemy（additive）、Vue 3 全局构建。验证：pytest（TDD）+ `node --check` + 浏览器手动。

## Global Constraints

- 规格：`docs/superpowers/specs/2026-08-29-stale-cache-fallback-design.md`。
- Git Flow 分支 `feature/stale-cache-fallback`；Conventional Commits 中文主题。
- 诚实性：降级只返回真实获取过的历史数据，必须经响应头披露，绝不伪造。
- 测试用 loader 抛异常需 monkeypatch 可控；`cached` 是同步函数，线程安全用既有 `cache_lock`。

---

### Task 1: 分支准备

- [ ] `git flow feature start stale-cache-fallback`
- Expected: 基于 develop（当前 `65ddd52`）。

---

### Task 2: 后端 cached() 降级 + 标记（TDD）

**Files:**
- Modify: `tests/test_backend_api.py`（先写失败测试）
- Modify: `backend/data_source.py`
- Modify: `backend/app.py`

- [ ] **Step 1: 先写失败测试**

`tests/test_backend_api.py` 追加：

```python
def test_cached_serves_stale_on_loader_failure(monkeypatch):
    from backend import data_source as ds
    from backend.data_source import cached

    # 先灌入一次成功缓存
    calls = []
    monkeypatch.setattr(ds, "_cache_ttl", 0)  # 强制缓存过期路径
    cached("k", lambda: (calls.append(1) or "ok"))
    assert ds.cache["k"][1] == "ok"

    def boom():
        raise ConnectionError("upstream down")

    monkeypatch.setattr(ds, "cache", dict(ds.cache))  # 保持缓存，避免重灌
    assert cached("k", boom) == "ok"  # 降级返回旧值
    marker = ds.recent_stale(window=60)
    assert marker is not None and marker["age"] >= 0


def test_cached_raises_when_stale_too_old_or_absent():
    from backend import data_source as ds
    from backend.data_source import cached

    # 无缓存 → 抛出
    ds.cache.clear()
    try:
        cached("absent", lambda: (_ for _ in ()).throw(ConnectionError("x")))
        assert False, "should raise"
    except ConnectionError:
        pass

    # 超龄缓存 → 抛出
    ds.cache["old"] = (0.0, "oldval")  # 1970 年，远超 1800s
    try:
        cached("old", lambda: (_ for _ in ()).throw(ConnectionError("x")))
        assert False, "should raise"
    except ConnectionError:
        pass
```

（若与既有测试命名冲突，以现有风格对齐。）

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/test_backend_api.py -q` → 新用例红（KeyError/`recent_stale` 不存在 / 断言失败）。

- [ ] **Step 3: 实现**

`backend/data_source.py` 顶部常量区追加：

```python
STALE_MAX_AGE = 1800  # 30 分钟硬顶：超龄缓存不再降级
```

模块级标记（`cache_lock` 旁）：

```python
stale_marker: dict[str, float] = {"at": 0.0, "age": 0.0}


def mark_stale(age: float) -> None:
    with cache_lock:
        stale_marker["at"] = time.time()
        stale_marker["age"] = age


def recent_stale(window: float = 2.0) -> dict[str, float] | None:
    """窗口内是否发生过降级服务；返回 {age: 秒} 或 None。"""
    with cache_lock:
        if time.time() - stale_marker["at"] <= window:
            return {"age": stale_marker["age"]}
    return None
```

`cached()` 改造：

```python
def cached(key: str, loader):
    now = time.time()
    with cache_lock:
        item = cache.get(key)
        if item and now - item[0] < _cache_ttl:
            return item[1]
    try:
        value = loader()
    except Exception:
        with cache_lock:
            item = cache.get(key)
        if item and now - item[0] <= STALE_MAX_AGE:
            mark_stale(now - item[0])
            return item[1]
        raise
    with cache_lock:
        cache[key] = (now, value)
    return value
```

- [ ] **Step 4: middleware**

`backend/app.py` `create_app()` 内、`app = FastAPI(...)` 后追加：

```python
    @app.middleware("http")
    async def stale_header_middleware(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            marker = data_source.recent_stale(window=2.0)
            if marker:
                response.headers["X-Atlas-Stale"] = f"{int(marker['age'])}"
        return response
```

（确认 `backend.app` 已 `from backend import data_source` 或等价引用；若未导入，顶部补 `import backend.data_source as data_source`。`Request` 从 `starlette.requests` 导入或 FastAPI 已导出。）

- [ ] **Step 5: middleware 测试**

`tests/test_backend_api.py` 追加（monkeypatch `recent_stale` 返回标记）：

```python
def test_stale_header_present_when_recent_stale(monkeypatch):
    import backend.app as app_module
    from fastapi.testclient import TestClient
    from backend import data_source as ds

    monkeypatch.setattr(ds, "recent_stale", lambda window=2.0: {"age": 300}, raising=False)
    with TestClient(app_module.create_app()) as client:
        resp = client.get("/api/health")
    assert resp.headers.get("x-atlas-stale") == "300"
```

- [ ] **Step 6: 跑测试确认绿 + 提交**

Run: `python -m pytest tests/ -q` → 全绿（40+3 新增）。

```bash
git add backend/data_source.py backend/app.py tests/test_backend_api.py
git commit -m "feat: 行情接口失败时降级返回缓存并输出陈旧响应头"
```

---

### Task 3: 前端接入响应头

**Files:**
- Modify: `frontend/app.js`

- [ ] **Step 1: 状态 + requestJson**

setup 顶部（`market` ref 附近）追加：

```js
    const serverStaleAge = ref(null);
```

`requestJson`（323-337）内 `const payload = await response.json()...` 之前读头：

```js
      const staleHeader = response.headers.get('x-atlas-stale');
      if (staleHeader !== null) {
        serverStaleAge.value = Number(staleHeader);
      }
      const payload = await response.json().catch(() => ({}));
```

（正常响应无头则不清除——由 refreshAll 每轮开头统一重置，见 Step 2。）

- [ ] **Step 2: refreshAll 状态机并入**

`refreshAll` 开头（`results` 计算前）重置：`serverStaleAge.value = null;`
dataState 判定（554-562）改为：

```js
        if (failures.length && !market.quotes.length && !screenRows.value.length && !serverStaleAge.value) {
          dataState.value = 'error';
          errorMessage.value = failures[0].reason?.message || '真实行情暂时不可用';
        } else if (failures.length && !serverStaleAge.value) {
          dataState.value = 'stale';
          errorMessage.value = '行情接口部分失败，当前页面保留最近一次成功数据。';
        } else if (serverStaleAge.value !== null) {
          dataState.value = 'stale';
          errorMessage.value = `行情源暂时不可用，展示服务器缓存的真实行情（约 ${serverStaleAge.value >= 60 ? Math.round(serverStaleAge.value / 60) + ' 分钟前' : '刚获取'}）。`;
        } else {
          dataState.value = 'live';
        }
```

（收件箱 `lastRecordedDataState` 状态机不变，自动记录降级/恢复事件。）

- [ ] **Step 3: return 导出 + 版本号**

return 对象 `dataState,` 附近追加 `serverStaleAge,`。
`index.html` app.js 版本 `?v=20260829-6` → `?v=20260830-1`。

- [ ] **Step 4: 验证 + 提交**

Run: `node --check frontend/app.js`；模板绑定闭合检查（复用会话内脚本）。

```bash
git add frontend/app.js frontend/index.html
git commit -m "feat: 前端消费陈旧响应头并披露缓存行情状态"
```

---

### Task 4: 回归、手动验证与收尾

- [ ] **Step 1: 全量回归**

Run: `python -m pytest tests/ -q` 与 `node --check frontend/app.js` → 全绿。

- [ ] **Step 2: 浏览器验证**

- DevTools Network → Offline → 触发一次刷新 → 页面顶栏「缓存行情」，提示「展示服务器缓存的真实行情（约 X 分钟前）」；收件箱出现「行情数据降级」（冷却合并）
- Network 面板响应头含 `X-Atlas-Stale`
- 恢复 Online → 刷新 → 「真实行情」+ 收件箱「行情已恢复」
- 未降级正常路径不受影响（响应头缺失）

- [ ] **Step 3: 完成分支**

```bash
git flow feature finish stale-cache-fallback
```
