# 通知中心（系统事件收录）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 系统事件（冲突自愈 / 保存失败 / 行情降级）以 `kind='system'` 收录进现有提醒中心并随工作区同步持久化；"执行"角标只计盯盘触发；桌面通知按类型在设置页可配置。

**Architecture:** 零新后端路由。后端仅两处：设置默认值/归一化加两个布尔键、`_alert_dict` 输出 `createdAtMs`（由 `created_at` 派生）。前端 `addAlert` 增加系统事件冷却合并（同 title 10 分钟内 → 更新原条目 message 为 ×N 形式）与桌面通知分组判定；新增 4 个系统事件调用点；提醒中心加筛选 chips；设置"工作台"标签加两行开关。

**Tech Stack:** FastAPI + SQLAlchemy（additive）、Vue 3 全局构建。验证：pytest（TDD）+ `node --check` + 浏览器手动。

## Global Constraints

- 规格：`docs/superpowers/specs/2026-08-29-notification-center-design.md`。
- Git Flow 分支 `feature/notification-center`；Conventional Commits 中文主题。
- `alerts` 条目新增本地字段 `createdAtMs`（Date.now()），服务端导入白名单不含它（丢弃，由 `_alert_dict` 从 `created_at` 派生回填）——无数据库迁移。
- 现有 `kind`（alert/success/info）语义不变；桌面通知按组判定：`kind==='system'` → `notifyDesktopSystem`，其余 → `notifyDesktopAlert`。
- lucide `Wrench` 已确认存在。

---

### Task 1: 分支准备

- [ ] **Step 1: 开启 feature 分支**

```bash
git flow feature start notification-center
```

Expected: 基于 develop（`a764e20`）。

---

### Task 2: 后端设置键与 createdAtMs（TDD）

**Files:**
- Modify: `tests/test_settings_api.py`（先写断言）
- Modify: `tests/test_backend_api.py`（workspace GET 断言）
- Modify: `backend/storage.py:239-271,203-211`

- [ ] **Step 1: 先写失败测试**

`tests/test_settings_api.py` 追加（沿用文件内现有断言风格）：

```python
def test_notification_desktop_settings_defaults_and_normalization(client):
    payload = client.get("/api/settings").json()
    assert payload["data"]["notifyDesktopAlert"] is True
    assert payload["data"]["notifyDesktopSystem"] is False
    saved = client.put("/api/settings", json={"notifyDesktopSystem": "yes", "notifyDesktopAlert": 0})
    assert saved.status_code == 200
    data = client.get("/api/settings").json()["data"]
    assert data["notifyDesktopSystem"] is True
    assert data["notifyDesktopAlert"] is False
```

（若该文件 fixture 名称不同，以现有测试为准对齐 client fixture。）

`tests/test_backend_api.py` 的 workspace 测试中追加断言：GET `/api/workspace` 的 `alerts` 每项含数值型 `createdAtMs`。

- [ ] **Step 2: 跑测试确认红**

Run: `python -m pytest tests/test_settings_api.py tests/test_backend_api.py -q`
Expected: 新断言失败（KeyError / 断言失败）。

- [ ] **Step 3: 实现**

`backend/storage.py` `DEFAULT_WORKSPACE_SETTINGS`（251 行 `conflictPolicy` 后）追加：

```python
    "notifyDesktopAlert": True,
    "notifyDesktopSystem": False,
```

`_normalize_workspace_settings`（270 行 `monitorEnabled` 后）追加：

```python
    data["notifyDesktopAlert"] = bool(data["notifyDesktopAlert"])
    data["notifyDesktopSystem"] = bool(data["notifyDesktopSystem"])
```

`_alert_dict`（203-211）返回 dict 追加：

```python
        "createdAtMs": int(alert.created_at.timestamp() * 1000),
```

- [ ] **Step 4: 跑测试确认绿 + 提交**

Run: `python -m pytest tests/ -q` → 38+ 项全过。

```bash
git add backend/storage.py tests/
git commit -m "feat: 设置新增桌面通知开关键并输出提醒 createdAtMs"
```

---

### Task 3: 前端 addAlert 冷却合并 + 系统事件接入

**Files:**
- Modify: `frontend/app.js`（settingsDraft 初始 152 行、scheduleWorkspaceSync catch 369 行、adoptServerSnapshot 386 行、pushLocalWorkspace 402 行、unreadAlerts 245 行、refreshAll dataState 534-542 行、showToast 前 addAlert 697 行、saveSettings catch、backtestGrid catch、return 导出）

- [ ] **Step 1: settingsDraft 初始键**

152 行 reactive 对象追加 `notifyDesktopAlert: true, notifyDesktopSystem: false`。

- [ ] **Step 2: addAlert 冷却合并 + 桌面通知分组**

替换 `addAlert`（697-712）为：

```js
    function addAlert(kind, title, message) {
      const now = Date.now();
      if (kind === 'system') {
        const existing = alerts.value.find((item) => item.kind === 'system' && item.title === title);
        if (existing && now - (existing.createdAtMs || 0) < 10 * 60 * 1000) {
          const count = (existing.count || 1) + 1;
          existing.count = count;
          existing.message = count > 1 ? `${message}（10 分钟内第 ${count} 次）` : message;
          existing.createdAtMs = now;
          existing.time = '刚刚';
          persist();
          return;
        }
      }
      const item = {
        id: `alert-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        kind,
        title,
        message,
        time: '刚刚',
        read: false,
        createdAtMs: now
      };
      alerts.value.unshift(item);
      alerts.value = alerts.value.slice(0, 24);
      persist();
      const desktopAllowed = kind === 'system' ? settingsDraft.notifyDesktopSystem : settingsDraft.notifyDesktopAlert;
      if (desktopAllowed && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification(title, { body: message });
      }
    }
```

（`count` 为本地展示字段，服务端白名单外自动丢弃；重载后由服务端 `createdAtMs` 恢复冷却基点。）

- [ ] **Step 3: 四个系统事件调用点**

1. `adoptServerSnapshot`（386）在 `showToast(...)` 前追加：

```js
      addAlert('system', '工作区冲突已自动处理', auto ? '检测到其他页面更新，已自动采用服务器版本。' : '已手动采用服务器最新数据。');
```

2. `pushLocalWorkspace`（402）成功分支 `showToast(successMessage);` 前追加：

```js
        addAlert('system', '工作区已用本地版本覆盖', successMessage);
```

3. `scheduleWorkspaceSync` catch 的非 409 静默分支（369 行注释处）改为：

```js
          } else {
            addAlert('system', '工作区同步失败', error.message || '持久化服务暂不可用，浏览器存储兜底。');
          }
```

（原注释行删除；409 分支已在 adopt/pushLocal 内记录，不重复。）

4. `refreshAll`（534-542）：dataState 赋值后统一记录状态转换。在 `dataState.value = 'live';` 分支块之后（543 行 `market.errors` 判断之前）插入：

```js
        if (dataState.value !== lastRecordedDataState) {
          if (dataState.value === 'stale') {
            addAlert('system', '行情数据降级', '部分接口失败，当前页面保留最近一次成功数据，来源可能已切换。');
          } else if (dataState.value === 'error') {
            addAlert('system', '行情获取失败', errorMessage.value || '真实行情暂时不可用。');
          } else if (dataState.value === 'live' && lastRecordedDataState && lastRecordedDataState !== 'live') {
            addAlert('system', '行情已恢复', '实时行情接口恢复正常。');
          }
          lastRecordedDataState = dataState.value;
        }
```

并在 setup 顶部（`refreshInFlight` 声明附近）加 `let lastRecordedDataState = '';`。恢复事件只在实际降级过后记录一次；重复降级由 addAlert 冷却合并。

- [ ] **Step 4: 保存失败接入**

- `saveSettings` catch（`showToast(error.message || '设置保存失败', 'error');` 前后）追加 `addAlert('system', '设置保存失败', error.message || '未知错误');`
- `backtestGrid` catch（838 行附近）改为：

```js
      } catch (error) {
        showToast(error.message || '网格回测失败', 'error');
        if (save) addAlert('system', '网格策略保存失败', error.message || '未知错误');
      }
```

（`savePlan` 为纯前端保存，无服务端失败路径，不接入——同步失败已覆盖。）

- [ ] **Step 5: unreadAlerts 排除系统事件**

245 行改为：

```js
    const unreadAlerts = computed(() => alerts.value.filter((alert) => !alert.read && alert.kind !== 'system').length);
```

- [ ] **Step 6: 验证 + 提交**

Run: `node --check frontend/app.js` → 通过。

```bash
git add frontend/app.js
git commit -m "feat: 系统事件接入提醒中心并支持冷却合并与分组桌面通知"
```

---

### Task 4: 提醒中心筛选与图标、设置开关

**Files:**
- Modify: `frontend/app.js`（alertFilter + filteredAlerts + return）
- Modify: `frontend/index.html:552-558`（筛选条 + 列表改造）、`frontend/index.html:570-572`（设置两行）、`frontend/index.html:228`（指挥台图标）
- Modify: `frontend/styles.css`（追加筛选 chips 样式）

**Interfaces:**
- Produces: `alertFilter`（ref：'all'/'trade'/'system'）、`filteredAlerts`（computed）

- [ ] **Step 1: app.js 筛选状态**

`unreadAlerts` computed 后插入：

```js
    const alertFilter = ref('all');
    const filteredAlerts = computed(() => {
      if (alertFilter.value === 'trade') return alerts.value.filter((alert) => alert.kind !== 'system');
      if (alertFilter.value === 'system') return alerts.value.filter((alert) => alert.kind === 'system');
      return alerts.value;
    });
```

`return` 导出对象中 `alerts,` 附近追加 `alertFilter, filteredAlerts,`。

- [ ] **Step 2: 提醒中心 UI**

552 行 surface-heading 后插入筛选条：

```html
              <div class="alert-filters" role="tablist" aria-label="提醒分类">
                <button v-for="option in [{ id: 'all', label: '全部' }, { id: 'trade', label: '盯盘' }, { id: 'system', label: '系统' }]" :key="option.id" type="button" role="tab" :class="['alert-filter-chip', { 'is-active': alertFilter === option.id }]" :aria-selected="alertFilter === option.id" @click="alertFilter = option.id">{{ option.label }}</button>
              </div>
```

554-558 列表改造：`v-for="alert in filteredAlerts"`；空态条件改为 `!filteredAlerts.length`，文案改为"暂无提醒"/"切换分类查看其他提醒。"。

- [ ] **Step 3: 图标兼容 system**

555 行 alert-icon 类与图标 ternary 改为：

```html
<div :class="['alert-icon', alert.kind === 'success' ? 'success' : alert.kind === 'info' || alert.kind === 'system' ? 'info' : '']"><i :data-lucide="alert.kind === 'success' ? 'check-circle-2' : alert.kind === 'alert' ? 'triangle-alert' : alert.kind === 'system' ? 'wrench' : 'bell-ring'" aria-hidden="true"></i></div>
```

228 行（指挥台执行跟踪）图标 ternary 同步加 `alert.kind === 'system' ? 'wrench'` 分支（类名分支保持原样）。

- [ ] **Step 4: 设置页两行开关**

572 行冲突处理策略行后追加：

```html
            <section v-if="settingsTab === 'workspace'" class="surface settings-row"><div><strong>桌面通知：盯盘触发</strong><span>价格触发与计划动态弹系统通知</span></div><label class="toggle"><input v-model="settingsDraft.notifyDesktopAlert" type="checkbox"><span class="toggle-track"><span></span></span></label></section>
            <section v-if="settingsTab === 'workspace'" class="surface settings-row"><div><strong>桌面通知：系统事件</strong><span>冲突自愈、行情降级等收件箱事件弹系统通知</span></div><label class="toggle"><input v-model="settingsDraft.notifyDesktopSystem" type="checkbox"><span class="toggle-track"><span></span></span></label></section>
```

- [ ] **Step 5: 样式 + 验证 + 提交**

styles.css"===== P1 unified trading desk ====="块后追加：

```css
/* ===== P2 notification center ===== */
.alert-filters {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}

.alert-filter-chip {
  padding: 6px 14px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: transparent;
  color: var(--muted-strong);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.alert-filter-chip.is-active {
  border-color: #ef6d53;
  color: #eef2f8;
  background: rgba(239, 109, 83, 0.12);
}
```

Run: `node --check frontend/app.js` → 通过。

```bash
git add frontend/app.js frontend/index.html frontend/styles.css
git commit -m "feat: 提醒中心分类筛选与桌面通知设置开关"
```

---

### Task 5: 回归、手动验证与收尾

- [ ] **Step 1: 全量回归**

Run: `python -m pytest tests/ -q` 与 `node --check frontend/app.js`
Expected: 全部通过。

- [ ] **Step 2: 浏览器验证**

- 双开标签触发冲突 → 收件箱出现"工作区冲突已自动处理"、角标不亮、桌面通知不弹（system 默认关）
- 10 分钟内重复冲突 → 合并为 ×N 计数条目
- 设置开"桌面通知：系统事件"→ 再触发一次 → 弹桌面通知
- 提醒中心三个筛选 chips 正确过滤；清空已读作用于全部
- 设置两行开关保存/往返（刷新后保持）

- [ ] **Step 3: 完成 feature 分支**

```bash
git flow feature finish notification-center
```

Expected: `--no-ff` 合入 develop，分支删除。
