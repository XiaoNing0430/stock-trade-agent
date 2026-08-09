# 用户使用流程体验优化实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 让用户可以从任意主要入口清楚地完成“识别标的、生成网格建议、回测并保存”的流程。

**架构：** 前端继续使用 Vue 3 单文件状态逻辑，不新增后端接口。`app.js` 增加纯状态辅助函数与导航动作，`index.html` 使用这些状态渲染分步操作，`styles.css` 仅补充复用型状态和响应式样式。

**技术栈：** Vue 3、原生 CSS、FastAPI 静态资源服务、pytest、Node.js 语法检查。

## 全局约束

- 不修改真实行情源、网格回测计算或数据库结构。
- 保持 `/api/grid/preview`、`/api/grid/backtest` 的请求和响应契约。
- 使用简体中文界面文案。
- 桌面和窄屏下不得产生页面横向溢出。

---

### 任务 1：网格策略状态与导航逻辑

**文件：**
- 修改：`frontend/app.js:209-228,727-847,988-1069`
- 测试：`frontend/app.js` 的 Node.js 语法检查

**接口：**
- 使用：现有 `gridDraft`、`gridSuggestion`、`gridResult`、`selectedCode`。
- 新增：`openGridStrategy(code?: string): Promise<void>`，转入网格页并按需生成建议。
- 新增：`gridAction` 计算属性，返回 `{ label, icon, action }` 以供页面选择主操作。

- [ ] **步骤 1：记录当前语法检查基线**

运行：`node --check frontend/app.js`

预期：当前脚本语法有效。

- [ ] **步骤 2：编写最小状态辅助函数**

在 `setup()` 内新增：

```js
const normalizedGridCode = computed(() => String(gridDraft.code || '').trim());
const hasGridSuggestion = computed(() => Boolean(gridSuggestion.value));
const hasGridResult = computed(() => Boolean(gridResult.value));
```

并让 `openGridStrategy` 将传入的合法六位代码同步到 `selectedCode` 和 `gridDraft.code`，清空旧结果后调用 `previewGrid()`。

- [ ] **步骤 3：在进入网格页时自动预览一次**

在 `switchView` 中处理 `nextView === 'grid'`：当代码为六位数字、当前未计算且未在加载时调用 `previewGrid()`；其他视图维持当前行为。

- [ ] **步骤 4：暴露页面需要的状态和动作**

在 `return` 对象中暴露 `normalizedGridCode`、`hasGridSuggestion`、`hasGridResult` 和 `openGridStrategy`。

- [ ] **步骤 5：验证脚本语法**

运行：`node --check frontend/app.js`

预期：退出码为 0。

### 任务 2：网格策略分步界面与快捷入口

**文件：**
- 修改：`frontend/index.html:115-127,410-460`
- 修改：`frontend/styles.css:2297-2377,2915-3188`
- 测试：本地浏览器交互检查

**接口：**
- 使用：任务 1 产出的 `openGridStrategy`、`hasGridSuggestion`、`hasGridResult`。
- 产出：总览和股票详情的网格策略入口；网格页的识别信息、三步进度和上下文主按钮。

- [ ] **步骤 1：补充总览和选中股票的入口**

新增两个按钮，分别调用：

```html
<button type="button" class="button button-secondary" @click="openGridStrategy()">制定网格策略</button>
<button type="button" class="button button-secondary" @click="openGridStrategy(selectedCode)">网格策略</button>
```

- [ ] **步骤 2：将网格页首要操作改为状态驱动**

未生成建议时显示“生成策略建议”；已有建议无结果时显示“开始回测”；已有结果时显示“保存策略”。保存按钮仅在有回测结果时启用。

- [ ] **步骤 3：补充标的识别和下一步提示**

在代码输入框下显示当前代码、名称、交易所和参考价格；在无结果面板中显示“生成策略建议”按钮，而不是只显示说明文字。

- [ ] **步骤 4：补齐紧凑样式**

添加不嵌套卡片的步骤提示与标的识别信息样式；在 `max-width: 680px` 下将操作按钮和识别信息改为纵向流式布局。

- [ ] **步骤 5：浏览器验证桌面流程**

在 `http://127.0.0.1:4173/` 输入 `588000` 并进入网格策略，确认显示“科创50ETF华夏”及建议；执行回测后确认主操作变为保存。

### 任务 3：行情状态与响应式回归验证

**文件：**
- 修改：`frontend/index.html:148-165`
- 修改：`frontend/app.js:251-264`
- 修改：`frontend/styles.css:2915-3188`（仅当窄屏验证需要）
- 测试：`tests/test_grid_strategy.py`、浏览器宽窄屏检查

**接口：**
- 使用：现有 `dataState`、`marketStatus`、`dataStatusText`。
- 产出：真实报价到达前不误报实时连接的状态展示。

- [ ] **步骤 1：收紧实时状态判断**

只有 `dataState === 'live'` 且 `market.quotes.length > 0` 时显示“已连接”和“实时数据已同步”；否则显示对应的连接中、缓存或断开文案。

- [ ] **步骤 2：改善指数空状态**

加载时保持“正在读取指数”；加载结束但无数据时显示“暂未获得指数报价”与“刷新行情”按钮。

- [ ] **步骤 3：执行自动化检查**

运行：

```powershell
node --check frontend/app.js
pytest tests/test_grid_strategy.py -q
```

预期：两条命令均以退出码 0 完成。

- [ ] **步骤 4：执行浏览器回归检查**

使用 1280px 和 390px 视口检查：图标为 SVG、无页面横向溢出、网格策略页面可滚动且操作按钮可见。

- [ ] **步骤 5：提交实现**

```bash
git add frontend/app.js frontend/index.html frontend/styles.css docs/superpowers/plans/2026-08-09-user-journey-ux.md
git commit -m "feat: improve strategy user journey"
```
