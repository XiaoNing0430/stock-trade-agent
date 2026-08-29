# 独立个股详情视图设计 — 2026-08-30

## 目标

将「选中股票详情」从选股器视图底部（`selected-stock-panel`）抽取为独立一级视图 `stock-detail`，全站统一入口：总览/选股/盯盘中点击任意股票行 → 进入详情页，返回按钮回到来源视图。同时修复 `selectStock` 强制跳回选股器的体验问题。

## 非目标

- 不新增底部导航 tab（5 个 tab 保持不变，详情页为次级页面）。
- 不改变数据流（报价/历史仍走现有 `ensureQuote` + `fetchHistory`）。
- 不改动选股器筛选/分页/排序逻辑。

## 架构

### 1. 视图状态（frontend/app.js）

- 新增 `const detailReturnView = ref('screener');` — 记录详情页的来源视图
- `VIEW_META`（modules/constants.js）追加 `stock-detail` 元数据：标题「个股详情」、描述「报价、走势与操作入口」

### 2. 导航与返回（frontend/app.js）

`selectStock(code, fromView)` 签名扩展（`fromView` 可选，默认当前 `view`）：

```js
async function selectStock(code, fromView) {
  if (!code) return;
  detailReturnView.value = fromView || view.value || 'screener';
  selectedCode.value = code;
  persist();
  view.value = 'stock-detail';
  await ensureQuote(code);
  try {
    await fetchHistory(code, 'selected');
  } catch (error) {
    errorMessage.value = '该股票的历史日线暂时不可用。';
  }
  await nextTick();
  renderIcons();
}

function backFromDetail() {
  view.value = detailReturnView.value;
  persist();
  nextTick(renderIcons);
}
```

- 所有 `@click="selectStock(stock.code)"` 调用点改为传入来源视图（可选；不传则自动用当前 `view`）
- 现有 `switchView('grid')` 里 `openGridStrategy` 会 `selectStock`，需保持返回语义正确（从详情页点「网格策略」进网格后，返回目标是网格而非详情——`openGridStrategy` 不改，它走 `switchView`）

### 3. 详情视图模板（frontend/index.html）

- 新增 `<section v-else-if="view === 'stock-detail'" class="view-panel is-active">`：
  - 顶部视图头：`view-heading` + 返回按钮 `<button @click="backFromDetail"><i data-lucide="arrow-left"></i>返回</button>`
  - 内容区 = 现有 `selected-stock-panel` 完整内容（summary + 走势图 + 来源角标），可原样搬移
- **移除** 选股器视图底部（477-500 行）的 `selected-stock-panel`——选股器/盯盘列表不再有下方详情，页面变短
- 总览「迷你股票项」、盯盘列表行、精选/全市场行：`@click="selectStock(stock.code)"` 保持不变（自动用当前 view 作为返回目标）

### 4. 返回目标细节

- 从「总览」点迷你股票 → 返回总览
- 从「选股（精选/全市场）」点行 → 返回选股器（保留模式/分页状态，因为只是切换 `view`，不重建列表）
- 从「盯盘」点行 → 返回盯盘
- 全局搜索 `searchSymbol()` 里 `selectStock(match.code)` → 返回目标为当前视图（搜索框所在视图）

### 5. 样式（frontend/styles.css）

- `.detail-return-btn`（返回按钮）样式；详情视图头与现有 `view-heading` 对齐
- 详情面板内容宽幅（可用 `max-width` 容器，但复用现有 `.selected-stock-panel` 布局类，仅去掉其在选股器底部时的 `margin` 语义——保留类名复用样式）

## 数据流

`selectStock` 是唯一入口，统一：记录返回 → 设 code → 切视图 → 拉报价/历史 → 渲染。详情页数据与旧面板完全一致（`selectedStock` computed、`selectedHistory`、`chartDataSource`），无新增请求。

## 错误处理

- `fetchHistory` 失败：沿用现有 `errorMessage` 提示，页面仍显示报价区与返回按钮
- 无报价（新代码）：显示 `selectedStock?.name || '选择一只股票'` 占位逻辑不变

## 测试

- 无后端改动；前端验证：`node --check frontend/app.js` + 模板闭包检查（`detailReturnView`/`backFromDetail`/新视图分支均导出）
- 手动验收：
  - [ ] 从总览点迷你股票 → 进入详情页，返回回总览
  - [ ] 从选股精选/全市场点行 → 进入详情页，返回回选股器且模式/分页保留
  - [ ] 从盯盘点行 → 进入详情页，返回回盯盘
  - [ ] 选股器视图不再有底部详情面板（页面变短）
  - [ ] 详情页「网格策略」「制定计划」「加入自选」按钮可用

## 非目标重申

不新增 nav tab、不改数据流、不动选股器核心逻辑；仅做视图抽取 + 返回导航。