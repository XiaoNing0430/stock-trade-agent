# 首次使用闭环优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 让刷新后网格策略可直接得到建议，并让空盯盘状态准确反映尚未配置监控标的。

**架构：** 继续由 `frontend/app.js` 管理 Vue 状态，在应用初始化后复用既有 `previewGrid()`；用计算属性集中推导盯盘是否就绪。`frontend/index.html` 仅依据该状态改变文案、禁用不适用动作，并提供选股器跳转。

**技术栈：** Vue 3、原生 CSS、FastAPI 静态资源、pytest、Node.js。

## 全局约束

- 不修改行情接口、网格建议接口、数据库结构或盯盘触发规则。
- 自动网格建议仅在恢复网格页且不存在建议和回测结果时运行一次。
- 无监控标的时不显示自动扫描正在执行。
- 界面文案使用简体中文，窄屏不得出现页面横向溢出。

---

### 任务 1：恢复网格策略建议

**文件：**
- 修改：`frontend/app.js:276-280,997-1020`
- 测试：`node --check frontend/app.js`

**接口：**
- 使用：`normalizedGridCode`、`hasGridSuggestion`、`hasGridResult`、`previewGrid()`。
- 新增：`restoreGridSuggestion(): Promise<void>`，仅在恢复网格页时执行已有建议请求。

- [x] **步骤 1：记录当前脚本语法基线**

运行：`node --check frontend/app.js`

预期：退出码为 0。

- [x] **步骤 2：添加恢复辅助函数**

```js
async function restoreGridSuggestion() {
  if (view.value !== 'grid' || gridLoading.value || hasGridSuggestion.value || hasGridResult.value) return;
  if (!/^\d{6}$/.test(normalizedGridCode.value)) return;
  await previewGrid();
}
```

- [x] **步骤 3：在初始化刷新行情后调用恢复辅助函数**

在 `onMounted` 的 `await refreshAll()` 后调用 `await restoreGridSuggestion()`，使标的报价已加载后再请求建议。

- [x] **步骤 4：验证脚本语法**

运行：`node --check frontend/app.js`

预期：退出码为 0。

### 任务 2：准确的空盯盘状态与引导

**文件：**
- 修改：`frontend/app.js:300-330,1020-1105`
- 修改：`frontend/index.html:533-563`
- 测试：本地浏览器盯盘页检查

**接口：**
- 使用：`watchlistCodes`、`monitorEnabled`、`switchView()`。
- 新增：`hasWatchTargets`、`monitorStatusLabel`、`monitorNextScan` 计算属性。

- [x] **步骤 1：添加盯盘就绪状态**

```js
const hasWatchTargets = computed(() => watchlistCodes.value.length > 0);
const monitorStatusLabel = computed(() => !hasWatchTargets.value ? '等待添加标的' : monitorEnabled.value ? '盯盘已开启' : '盯盘已暂停');
const monitorNextScan = computed(() => !hasWatchTargets.value ? '尚未开始' : monitorEnabled.value ? '15 秒' : '已暂停');
```

- [x] **步骤 2：将盯盘页绑定到状态**

状态标签改用 `monitorStatusLabel`；“立即扫描”仅在存在标的时启用；下一次扫描统计卡使用 `monitorNextScan` 和“自动 / 待配置”补充说明。

- [x] **步骤 3：添加空状态主操作**

在无自选标的时加入：

```html
<button class="button button-primary" type="button" @click="switchView('screener')">
  <i data-lucide="scan-search" aria-hidden="true"></i>去选股器添加标的
</button>
```

- [x] **步骤 4：执行浏览器验证**

刷新后停在网格策略页，确认 `588000` 自动出现建议；盯盘列表为空时确认显示“等待添加标的”“尚未开始”和主操作按钮。

### 任务 3：回归、提交和推送

**文件：**
- 创建：`docs/superpowers/plans/2026-08-09-onboarding-flow.md`
- 修改：任务 1、任务 2 的前端文件
- 测试：`tests/`

- [x] **步骤 1：运行自动化检查**

```powershell
node --check frontend/app.js
python -m pytest -q -p no:cacheprovider
git diff --check
```

预期：所有测试通过，且无差异格式错误。

- [x] **步骤 2：验证 390px 窄屏**

确认盯盘空状态页面未产生全局横向溢出，且主操作按钮可见。

- [x] **步骤 3：提交并推送**

```bash
git add frontend/app.js frontend/index.html docs/superpowers/plans/2026-08-09-onboarding-flow.md
git commit -m "feat: improve onboarding workflow"
git push origin main
```
