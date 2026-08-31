# 冲突处理策略与 toast 计时修复实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 409 冲突按可配置策略（`server` 默认 / `local` / `ask`）自动处理，并修复 toast 连发时超长停留的计时 bug。

**Architecture:** 后端只动 workspace settings 的默认值与归一化（纯函数，直测）；前端在 `scheduleWorkspaceSync` 的 409 分支按 `settingsDraft.conflictPolicy` 分派，抽出 `adoptServerSnapshot` / `pushLocalWorkspace` 两个复用助手；toast 改为逐条独立定时器。规格：`docs/superpowers/specs/2026-08-29-conflict-policy-and-toast-timing-design.md`。

**Tech Stack:** 同仓库主栈（FastAPI + pytest 离线 monkeypatch；Vue 3 全局构建，`node --check` 验证）。

## Global Constraints

- commit subject：Conventional Commits 前缀 + 中文。
- Git Flow：所有提交在 `feature/conflict-policy-toast-fix` 分支。
- API 字段纯新增；`conflictPolicy` 合法值 `server|local|ask`，非法回退 `server`。
- 任何策略下都不自动重试冲突写入（`local` 档的 force 重发是单次、用户显式配置的行为）。

---

### Task 1: 分支准备

**Files:** 无

- [x] **Step 1: 开启 feature 分支**

```bash
git flow feature start conflict-policy-toast-fix
```

Expected: 基于 `develop`（d81ef4a）创建并切换。

---

### Task 2: 后端 conflictPolicy 归一化（TDD）

**Files:**
- Modify: `backend/storage.py`（`DEFAULT_WORKSPACE_SETTINGS`、`_normalize_workspace_settings`）
- Test: `tests/test_settings_api.py`（末尾追加）

**Interfaces:**
- Consumes: `_normalize_workspace_settings(payload: dict) -> dict`（纯函数）、`DEFAULT_WORKSPACE_SETTINGS: dict`
- Produces: `data["conflictPolicy"] ∈ {"server","local","ask"}`，缺省/非法回退 `"server"`；随 `GET/PUT /api/settings` 的 `data` 自动透出

- [x] **Step 1: 写失败测试**（`tests/test_settings_api.py` 末尾追加）

```python
def test_conflict_policy_normalization_defaults_and_whitelist():
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS, _normalize_workspace_settings

    assert DEFAULT_WORKSPACE_SETTINGS["conflictPolicy"] == "server"
    assert _normalize_workspace_settings({})["conflictPolicy"] == "server"
    assert _normalize_workspace_settings({"conflictPolicy": "local"})["conflictPolicy"] == "local"
    assert _normalize_workspace_settings({"conflictPolicy": "ask"})["conflictPolicy"] == "ask"
    assert _normalize_workspace_settings({"conflictPolicy": "bogus"})["conflictPolicy"] == "server"
```

- [x] **Step 2: 确认失败**

Run: `python -m pytest tests/test_settings_api.py -v`
Expected: FAIL——`KeyError: 'conflictPolicy'`。

- [x] **Step 3: 实现**

`backend/storage.py` 的 `DEFAULT_WORKSPACE_SETTINGS` 末尾（`"retryCount": 1,` 之后）加一行：

```python
    "conflictPolicy": "server",
```

`_normalize_workspace_settings` 中 `data["retryCount"] = max(0, min(int(data["retryCount"]), 5))` 之后加一行：

```python
    data["conflictPolicy"] = data["conflictPolicy"] if data["conflictPolicy"] in {"server", "local", "ask"} else "server"
```

- [x] **Step 4: 确认通过 + 全量回归**

Run: `python -m pytest tests/ -q`
Expected: 38 passed。

- [x] **Step 5: 提交**

```bash
git add backend/storage.py tests/test_settings_api.py
git commit -m "feat: workspace 设置新增冲突处理策略归一化"
```

---

### Task 3: 前端策略分派与设置项

**Files:**
- Modify: `frontend/app.js`（`settingsDraft` 初始值；409 分支；新增 `adoptServerSnapshot`/`pushLocalWorkspace`，重构 `adoptServerWorkspace`/`forceSaveWorkspace`；`return` 导出不变——无新绑定）
- Modify: `frontend/index.html`（设置页新增下拉行）

**Interfaces:**
- Consumes: Task 2 的 `settingsDraft.conflictPolicy`；既有 409 契约 `error.payload.detail.workspace`
- Produces: 冲突分派行为（server/local 自动、ask 横幅）；设置页可改策略并持久化

- [x] **Step 1: `settingsDraft` 初始值加字段**（`retryCount: 1` 之后）

```js
      retryCount: 1,
      conflictPolicy: 'server'
```

- [x] **Step 2: 重构助手并分派**（替换现有 `adoptServerWorkspace` 与 `forceSaveWorkspace` 两个函数为以下四个，位置不变）

```js
    function adoptServerSnapshot(snapshot, auto = false) {
      watchlistCodes.value = snapshot.watchlist || [];
      plans.value = snapshot.plans || [];
      alerts.value = snapshot.alerts || [];
      workspaceRevision.value = Number(snapshot.revision || 0);
      persist();
      showToast(auto ? '检测到其他页面更新，已自动采用服务器版本' : '已采用服务器最新数据');
    }

    async function adoptServerWorkspace() {
      const snapshot = conflictSnapshot.value;
      conflictVisible.value = false;
      if (!snapshot) return;
      adoptServerSnapshot(snapshot, false);
    }

    async function pushLocalWorkspace(successMessage) {
      try {
        const saved = await requestJson('/api/workspace?force=true', {
          method: 'PUT',
          body: JSON.stringify(workspacePayload())
        });
        workspaceRevision.value = Number(saved.revision || 0);
        persist();
        showToast(successMessage);
      } catch (error) {
        showToast(error.message || '覆盖失败', 'error');
      }
    }

    async function forceSaveWorkspace() {
      conflictVisible.value = false;
      await pushLocalWorkspace('已用本地数据覆盖服务器');
    }
```

- [x] **Step 3: 409 分支按策略分派**（`scheduleWorkspaceSync` 的 catch 中，替换现有 `if (error.status === 409 ...)` 整段）

```js
        } catch (error) {
          if (error.status === 409) {
            // 版本冲突不自动重试写入，按工作区策略处理。
            workspaceSyncQueued = false;
            const snapshot = error.payload?.detail?.workspace;
            const policy = settingsDraft.conflictPolicy;
            if (policy === 'ask' || !snapshot) {
              // 响应异常缺失快照时，server/local 策略静默降级为 ask 行为。
              showConflictBanner(snapshot);
            } else if (policy === 'local') {
              await pushLocalWorkspace('检测到冲突，已自动用本地版本覆盖服务器');
            } else {
              adoptServerSnapshot(snapshot, true);
            }
          }
          // 其余失败仍静默降级：浏览器存储兜底，等待持久化服务恢复。
        } finally {
```

- [x] **Step 4: 设置页新增行**（`frontend/index.html` 设置区，"行情刷新间隔"行之后插入）

```html
            <section class="surface settings-row"><div><strong>冲突处理策略</strong><span>多个页面同时修改工作区时的默认处理方式</span></div><select v-model="settingsDraft.conflictPolicy" aria-label="冲突处理策略"><option value="server">自动采用服务器版本（推荐）</option><option value="local">自动用本地覆盖</option><option value="ask">每次询问</option></select></section>
```

- [x] **Step 5: 验证 + 提交**

Run: `node --check frontend/app.js` → 语法通过。
浏览器：设置页三种选项可保存；双标签页冲突在 server/local/ask 下行为各异。

```bash
git add frontend/app.js frontend/index.html
git commit -m "feat: 冲突按工作区策略自动处理并增加设置项"
```

---

### Task 4: toast 逐条计时修复

**Files:**
- Modify: `frontend/app.js`（`lastToastTimer` 声明、`showToast`、`onBeforeUnmount`）

**Interfaces:**
- Consumes: 无
- Produces: 每条 toast 独立 3.2 秒移除；连发不再互相延长

- [x] **Step 1: 替换共享定时器**（删除 `const lastToastTimer = ref(null);`，原位置改为）

```js
    const toastTimers = new Set();
```

- [x] **Step 2: `showToast` 尾部两行**（`clearTimeout(lastToastTimer.value); lastToastTimer.value = setTimeout(() => toast.remove(), 3200);`）替换为

```js
      const timer = setTimeout(() => {
        toast.remove();
        toastTimers.delete(timer);
      }, 3200);
      toastTimers.add(timer);
```

- [x] **Step 3: `onBeforeUnmount` 增加**（`clearTimeout(workspaceSyncTimer.value);` 之后）

```js
      toastTimers.forEach((timer) => clearTimeout(timer));
```

- [x] **Step 4: 验证 + 提交**

Run: `node --check frontend/app.js` → 语法通过。
浏览器：连续触发两条 toast（如快速加入两个自选），各自约 3.2 秒消失。

```bash
git add frontend/app.js
git commit -m "fix: toast 提示改为逐条独立计时"
```

---

### Task 5: 文档同步与收尾

**Files:**
- Modify: `AGENTS.md`（revision-lock 条目补策略说明）

- [x] **Step 1: AGENTS.md 更新**（"Workspace sync is revision-locked" 条目中 `...and surfaces 409 via the conflict banner...` 一句替换为）

```markdown
The frontend keeps the latest known `revision` in `workspaceRevision` and resolves 409 by `settingsDraft.conflictPolicy`: `server` (default) auto-adopts the server snapshot, `local` auto-force-saves the local one, `ask` shows the conflict banner with "采用服务器版本" / "用本地覆盖" actions — never auto-retry a 409.
```

- [x] **Step 2: 全量回归**

Run: `python -m pytest tests/ -q`、`node --check frontend/app.js`
Expected: 38 passed / 语法通过。

- [x] **Step 3: 提交 + feature finish**

```bash
git add AGENTS.md
git commit -m "docs: 补记冲突处理策略约定"
git flow feature finish conflict-policy-toast-fix
```

Expected: `--no-ff` 合入 develop，分支删除。
