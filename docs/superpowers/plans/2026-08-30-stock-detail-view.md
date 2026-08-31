# 独立个股详情视图实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将「选中股票详情」从选股器底部抽取为独立 `stock-detail` 视图，全站统一入口 + 来源返回导航。

**Architecture:** 新增 `view === 'stock-detail'` 一级视图（非 nav tab）；`selectStock(code, fromView)` 记录来源并切视图；`backFromDetail()` 返回来源；详情面板从选股器底部搬入新视图；所有列表点击行自动用当前视图作为返回目标。

**Tech Stack:** Vue 3 全局构建（无 bundler），`frontend/app.js` / `index.html` / `styles.css` / `modules/constants.js`。验证：`node --check` + 模板闭包检查 + 浏览器手动。

## Global Constraints

- 前端改动后必须更新 `index.html` 中 `app.js` 与 `styles.css` 的 `?v=` 缓存参数（app.js → `v=20260830-4`，styles.css → `v=20260830-3`）。
- 任何模板中使用的 setup 状态必须出现在 setup `return` 导出中，否则白屏（`_ctx.X` undefined）。改动后跑闭包检查脚本。
- 不新增底部导航 tab（5 个 tab 不变）。
- UI 文案中文；保持 XSS 纪律（`showToast` 用 `textContent`，`chartSvg` 用 `escapeHtml`）。

---

### Task 1: 分支准备

**Files:** 无

- [x] **Step 1: 建分支**

```bash
git flow feature start stock-detail-view
```

---

### Task 2: 视图状态与导航逻辑（frontend/app.js + modules/constants.js）

**Files:**
- Modify: `frontend/app.js`（`detailReturnView` ref、`selectStock` 扩展、`backFromDetail`、return 导出）
- Modify: `frontend/modules/constants.js`（`VIEW_META` 追加 `stock-detail`）
- Test: 闭包检查脚本（临时，运行后删除）

**Interfaces:**
- Produces: `detailReturnView`（ref<string>）、`backFromDetail()`（函数，切回来源视图）、`selectStock(code, fromView?)`（函数，fromView 可选）
- Consumes: 现有 `view` ref、`persist()`、`ensureQuote()`、`fetchHistory()`、`nextTick`、`renderIcons()`

- [x] **Step 1: constants.js 追加 VIEW_META**

`frontend/modules/constants.js` 中 `VIEW_META` 对象（在 settings 条目附近）追加：

```js
  'stock-detail': ['个股详情', '报价、走势与操作入口'],
```

- [x] **Step 2: app.js 新增 detailReturnView ref**

在 `const selectedCode = ref(...)` 附近追加：

```js
    const detailReturnView = ref('screener');
```

- [x] **Step 3: 扩展 selectStock 并新增 backFromDetail**

将现有 `async function selectStock(code)`（当前为 `selectedCode.value = code; persist(); switchView('screener'); ...`）替换为：

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

- [x] **Step 4: return 导出**

在 setup `return { ... }` 中加入：

```js
      detailReturnView,
      backFromDetail,
```

- [x] **Step 5: 验证 + 提交**

```bash
node --check frontend/app.js
```

跑闭包检查（临时脚本，验证 `detailReturnView`/`backFromDetail` 已导出，运行后删除）。

```bash
git add frontend/app.js frontend/modules/constants.js
git commit -m "feat: 新增个股详情视图状态与来源返回导航"
```

---

### Task 3: 详情视图模板（frontend/index.html）

**Files:**
- Modify: `frontend/index.html`

**Interfaces:**
- Consumes: `view === 'stock-detail'`、`backFromDetail`、`detailReturnView`、`selectedStock`、`selectedHistory`、`chartDataSource`、`formatNullable`、`formatPctNullable`、`trendClass`、`formatAmount`、`formatMoney`、`toggleWatch`、`isWatched`、`openGridStrategy`、`createPlan`、`chartSvg`
- Produces: 详情视图 section；移除选股器底部 `selected-stock-panel`

- [x] **Step 1: 搬移详情面板为独立视图**

将选股器视图（`view === 'screener'` section）底部 477-500 行的 `<section class="selected-stock-panel surface">...</section>` **整体移除**，并在 `view === 'grid'` 的 `<section v-else-if="view === 'grid'" ...>` **之前**插入新视图：

```html
        <section v-else-if="view === 'stock-detail'" class="view-panel is-active">
          <div class="view-heading">
            <div>
              <span class="section-kicker">STOCK DETAIL</span>
              <h2>{{ selectedStock?.name || '个股详情' }}</h2>
              <p class="heading-note">{{ selectedStock ? `${selectedStock.code} · ${selectedStock.exchange} · ${selectedStock.board}` : '选择一只股票' }}</p>
            </div>
            <div class="view-heading-actions">
              <button class="button button-secondary" type="button" @click="backFromDetail"><i data-lucide="arrow-left" aria-hidden="true"></i>返回</button>
            </div>
          </div>
          <section class="selected-stock-panel surface">
            <div class="selected-stock-summary">
              <div class="selected-stock-identity">
                <div class="stock-avatar">{{ selectedStock?.name?.slice(0, 1) || '—' }}</div>
                <div>
                  <div class="stock-name-line"><h3>{{ selectedStock?.name || '选择一只股票' }}</h3><span class="ticker-code">{{ selectedStock ? `${selectedStock.code} · ${selectedStock.exchange} · ${selectedStock.board}` : '从列表中选择' }}</span></div>
                  <span class="stock-sector">{{ selectedStock ? `PE ${formatNullable(selectedStock.pe, 1)} · PB ${formatNullable(selectedStock.pb, 2)}` : '暂无报价' }}</span>
                </div>
              </div>
              <div class="selected-stock-quote"><strong>{{ formatNullable(selectedStock?.price) }}</strong><span :class="trendClass(selectedStock?.change)">{{ formatPctNullable(selectedStock?.change) }}</span></div>
              <div class="selected-stock-metrics">
                <div><span>开盘</span><strong>{{ formatNullable(selectedStock?.open) }}</strong></div>
                <div><span>最高 / 最低</span><strong>{{ formatNullable(selectedStock?.high) }} / {{ formatNullable(selectedStock?.low) }}</strong></div>
                <div><span>成交额</span><strong>{{ formatAmount(selectedStock?.amount) }}</strong></div>
              </div>
              <div class="selected-stock-actions">
                <button class="button button-secondary" type="button" @click="toggleWatch(selectedCode)"><i :data-lucide="isWatched(selectedCode) ? 'star-off' : 'star'" aria-hidden="true"></i>{{ isWatched(selectedCode) ? '移出自选' : '加入自选' }}</button>
                <button class="button button-secondary" type="button" @click="openGridStrategy(selectedCode)"><i data-lucide="grid-3x3" aria-hidden="true"></i>网格策略</button>
                <button class="button button-primary" type="button" @click="createPlan(selectedCode)"><i data-lucide="clipboard-pen-line" aria-hidden="true"></i>制定计划</button>
              </div>
            </div>
            <div class="stock-detail-chart" v-html="chartSvg(selectedHistory.map(item => item.close), '#3b6fb6', `${selectedStock?.name || '股票'}近期走势`)"></div>
            <div class="chart-source-row"><span :class="['source-badge', { 'source-badge-local': chartDataSource === 'local' }]">{{ chartDataSource === 'local' ? '本地缓存' : '实时·腾讯' }}</span></div>
          </section>
        </section>
```

- [x] **Step 2: 版本号**

`index.html` 中：
- `app.js?v=20260830-3` → `app.js?v=20260830-4`
- `styles.css?v=20260830-2` → `styles.css?v=20260830-3`

- [x] **Step 3: 闭包检查 + 提交**

```bash
node --check frontend/app.js
```

跑闭包检查脚本验证新视图引用全部导出。

```bash
git add frontend/index.html frontend/styles.css
git commit -m "feat: 抽取独立个股详情视图并移除选股器底部详情面板"
```

---

### Task 4: 样式（frontend/styles.css）

**Files:**
- Modify: `frontend/styles.css`

- [x] **Step 1: 详情视图头部/返回按钮样式**

文件末尾追加：

```css
.detail-return-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
```

说明：详情视图复用现有 `.view-heading` / `.selected-stock-panel` / `.selected-stock-summary` 等类样式，无需新增大量 CSS；返回按钮用现有 `.button.button-secondary` 基础样式 + `.detail-return-btn` 微调间距（可选，若不需要可省略此 CSS 块）。

- [x] **Step 2: 验证 + 提交**

```bash
node --check frontend/app.js
git add frontend/styles.css
git commit -m "style: 个股详情视图返回按钮样式"
```

---

### Task 5: 回归、验证与收尾

**Files:** 无新增

- [x] **Step 1: 前端回归**

```bash
node --check frontend/app.js
```

闭包检查脚本通过（134+ 根标识符全解析）。

- [x] **Step 2: 浏览器手动验证**

- [x] 从「总览」点迷你股票 → 进入详情页，返回按钮回总览
- [x] 从「选股·精选」点行 → 详情页；「选股·全市场」点行 → 详情页；返回均回选股器且模式/分页保留
- [x] 从「盯盘」点行 → 详情页，返回回盯盘
- [x] 选股器视图不再有底部详情面板（页面明显变短）
- [x] 详情页「加入自选」「网格策略」「制定计划」按钮可用
- [x] 走势图正常渲染，来源角标显示「实时·腾讯」/「本地缓存」

- [x] **Step 3: 完成分支**

```bash
git flow feature finish stock-detail-view
```

---

## 自检

- **规格覆盖**：独立视图（Task 2/3）、返回导航（Task 2）、移除底部面板（Task 3）、VIEW_META（Task 2）、样式（Task 4）、验证（Task 5）— 全覆盖。
- **占位符**：无 TODO/TBD，所有代码完整给出。
- **类型一致性**：`selectStock(code, fromView)`、`backFromDetail()`、`detailReturnView` 名称在 Task 2-3 一致；`selected-stock-panel` 类名从旧位置原样搬移，样式类复用一致。