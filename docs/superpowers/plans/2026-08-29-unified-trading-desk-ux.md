# 统一交易台 UX 落地实施计划（P1）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在当前 develop 基线上落地统一交易台设计文档剩余的五块：今日交易台指挥台、回测 provenance 披露、选股器单滚动、手机底部导航与执行复合视图、设置页三标签。

**Architecture:** 全部改动在三个热点文件（`frontend/index.html`、`frontend/app.js`、`frontend/styles.css`）加 `modules/constants.js`。指挥台数据全部来自前端既有响应式状态（新增纯 computed，不新增 API）；provenance 复用后端已返回字段；底部导航与执行复合视图走新增 `exec` 视图 id + 条件渲染；设置标签为纯前端切换。旧样式类（`focus-list` 等）保留不清理（属 P3 文件拆分范围）。

**Tech Stack:** Vue 3 全局构建（无打包器）、单文件模板、CSS。验证：`node --check` + 浏览器手动（桌面 1280×720 / 1440×900，手机 390×844）。

## Global Constraints

- 规格：`docs/superpowers/specs/2026-08-09-unified-trading-desk-design.md`（含 2026-08-29 基线增量节）。
- commit subject：Conventional Commits 前缀 + 中文；Git Flow 分支 `feature/unified-trading-desk-ux`。
- API 字段只读不改；不新增 API；不以模拟值填补缺失数据（空态 + 主操作）。
- 不删除旧样式类（死样式留给 P3 清理）；新样式一律追加在 styles.css 末尾"P1 unified trading desk"注释块下。
- lucide 图标名必须先在 `frontend/vendor/lucide.min.js` 中确认存在（PascalCase 检索）再用。

---

### Task 1: 分支准备

**Files:** 无

- [x] **Step 1: 开启 feature 分支**

```bash
git flow feature start unified-trading-desk-ux
```

Expected: 基于 develop（`a77c45d`）创建并切换。

---

### Task 2: 今日交易台指挥台

**Files:**
- Modify: `frontend/index.html:122-334`（overview section 整体替换为指挥台结构，保留其中盘面温度面板复用块）
- Modify: `frontend/app.js`（新增 3 个 computed + return 导出）
- Modify: `frontend/styles.css`（末尾追加指挥台样式）

**Interfaces:**
- Consumes: 既有导出 `screenRows`/`filteredRows`/`gridStrategies`/`activePlans`/`unreadAlerts`/`breadth`/`selectedIndex`/`marketStatus`/`fetchedLabel`/`todayLabel`/`presetName`/`quoteFor`/`applyPreset`/`openGridStrategy`/`switchView`/`formatPct` 等格式化函数；`gridStrategies` 元素含 `status`/`lastBacktestAt`(ISO 串)/`latestMetrics.excessReturnPct`
- Produces: `presetHits`/`strategyStats`/`riskStats`（computed，Task 3+ 不依赖；供模板绑定）

- [x] **Step 1: 替换 overview 区块**

将 `frontend/index.html` 中 `<section v-if="view === 'overview'" class="view-panel is-active">`（122 行）至对应闭合 `</section>`（334 行）整体替换为：

```html
        <section v-if="view === 'overview'" class="view-panel is-active">
          <div class="view-heading">
            <div>
              <span class="section-kicker">TRADING DESK</span>
              <h2>今日交易台</h2>
              <p class="heading-note">市场怎样、有什么机会、策略是否可靠、当前有哪些风险。</p>
            </div>
            <div class="view-heading-actions">
              <span class="data-updated"><span class="live-dot"></span>{{ fetchedLabel }}</span>
              <span class="strategy-label">{{ todayLabel }}</span>
            </div>
          </div>

          <div v-if="errorMessage" class="connection-banner">
            <i data-lucide="triangle-alert" aria-hidden="true"></i>
            <span>{{ errorMessage }}</span>
            <button class="text-button" type="button" @click="refreshAll()">重试</button>
          </div>

          <div class="desk-kpis">
            <section class="desk-kpi surface">
              <span class="desk-kpi-label">市场状态</span>
              <strong :class="trendClass(selectedIndex?.change)">{{ selectedIndex ? formatPct(selectedIndex.change) : '--' }}</strong>
              <span class="desk-kpi-note">上证指数 {{ selectedIndex ? formatNumber(selectedIndex.price) : '--' }} · {{ marketStatus }}</span>
            </section>
            <section class="desk-kpi surface">
              <span class="desk-kpi-label">候选数量</span>
              <strong>{{ screenRows.length }}</strong>
              <span class="desk-kpi-note">当前条件命中 {{ filteredRows.length }} 只 · {{ presetName }}</span>
            </section>
            <section class="desk-kpi surface">
              <span class="desk-kpi-label">运行中策略</span>
              <strong>{{ strategyStats.running }}</strong>
              <span class="desk-kpi-note">待重新回测 {{ strategyStats.pending }} 个 · 样本外超额 {{ strategyStats.latestExcess != null ? formatPct(strategyStats.latestExcess) : '--' }}</span>
            </section>
            <section class="desk-kpi surface">
              <span class="desk-kpi-label">待处理提醒</span>
              <strong>{{ unreadAlerts }}</strong>
              <span class="desk-kpi-note">活跃计划 {{ riskStats.active }} 份 · 止损触及 {{ riskStats.stopHit }}</span>
            </section>
          </div>

          <div class="desk-workspaces">
            <section class="desk-panel surface">
              <div class="surface-heading">
                <div>
                  <span class="section-kicker">OPPORTUNITIES</span>
                  <h3>发现机会</h3>
                </div>
                <span class="strategy-label">{{ presetName }}</span>
              </div>
              <div class="preset-hits">
                <button v-for="preset in presetHits" :key="preset.name" class="preset-hit" type="button" @click="applyPreset(preset); switchView('screener')">
                  <span :class="['preset-icon', preset.iconClass]"><i :data-lucide="preset.icon" aria-hidden="true"></i></span>
                  <span class="preset-hit-name">{{ preset.name }}</span>
                  <strong class="preset-hit-count">{{ preset.count }}</strong>
                </button>
              </div>
              <div class="mini-stock-list">
                <div v-for="stock in filteredRows.slice(0, 4)" :key="stock.code" class="mini-stock-item" @click="selectStock(stock.code)">
                  <span class="stock-dot stock-dot-blue">{{ stock.name.slice(0, 1) }}</span>
                  <div class="mini-stock-copy"><strong>{{ stock.name }}</strong><span>{{ stock.code }} · 量比 {{ formatNullable(stock.volumeRatio, 2) }}</span></div>
                  <span class="mini-stock-change" :class="trendClass(stock.change)">{{ formatPctNullable(stock.change) }}</span>
                </div>
                <div v-if="!filteredRows.length" class="empty-state compact-empty"><span>当前条件下暂无结果。</span></div>
              </div>
              <button class="button button-primary button-full" type="button" @click="switchView('screener')">
                <i data-lucide="scan-search" aria-hidden="true"></i>
                进入选股器
              </button>
            </section>

            <section class="desk-panel surface">
              <div class="surface-heading">
                <div>
                  <span class="section-kicker">STRATEGY VALIDATION</span>
                  <h3>验证策略</h3>
                </div>
              </div>
              <div class="desk-stat-rows">
                <div class="desk-stat-row"><span>运行中策略</span><strong>{{ strategyStats.running }}</strong></div>
                <div class="desk-stat-row"><span>待重新回测</span><strong>{{ strategyStats.pending }}</strong></div>
                <div class="desk-stat-row"><span>最近样本外超额</span><strong :class="trendClass(strategyStats.latestExcess)">{{ strategyStats.latestExcess != null ? formatPct(strategyStats.latestExcess) : '--' }}</strong></div>
              </div>
              <div v-if="!gridStrategies.length" class="empty-state compact-empty"><span>还没有保存的网格策略。</span></div>
              <button class="button button-secondary button-full" type="button" @click="openGridStrategy()">
                <i data-lucide="grid-3x3" aria-hidden="true"></i>
                进入网格策略
              </button>
            </section>

            <section class="desk-panel surface">
              <div class="surface-heading">
                <div>
                  <span class="section-kicker">EXECUTION RISK</span>
                  <h3>执行跟踪</h3>
                </div>
              </div>
              <div class="desk-stat-rows">
                <div class="desk-stat-row"><span>活跃计划</span><strong>{{ riskStats.active }}</strong></div>
                <div class="desk-stat-row desk-stat-row-risk"><span>触及止损</span><strong>{{ riskStats.stopHit }}</strong></div>
                <div class="desk-stat-row"><span>未读提醒</span><strong>{{ unreadAlerts }}</strong></div>
              </div>
              <div class="activity-list">
                <div v-for="alert in alerts.slice(0, 2)" :key="alert.id" class="activity-item">
                  <div :class="['activity-icon', alert.kind === 'alert' ? 'alert' : alert.kind === 'success' ? 'success' : '']">
                    <i :data-lucide="alert.kind === 'success' ? 'check-circle-2' : alert.kind === 'alert' ? 'triangle-alert' : 'bell-ring'" aria-hidden="true"></i>
                  </div>
                  <div class="activity-copy"><strong>{{ alert.title }}</strong><span>{{ alert.message }}</span></div>
                </div>
                <div v-if="!alerts.length" class="empty-state compact-empty"><span>还没有提醒动态。</span></div>
              </div>
              <button class="button button-primary button-full" type="button" @click="switchView('monitor')">
                <i data-lucide="radar" aria-hidden="true"></i>
                进入盯盘提醒
              </button>
            </section>
          </div>

          <section class="market-board surface">
            <div class="surface-heading">
              <div>
                <span class="section-kicker">MARKET PULSE</span>
                <h3>盘面温度</h3>
              </div>
              <button class="icon-button" type="button" aria-label="打开盯盘中心" data-tooltip="盯盘中心" @click="switchView('monitor')">
                <i data-lucide="arrow-up-right" aria-hidden="true"></i>
              </button>
            </div>

            <div v-if="indices.length" class="index-grid">
              <div v-for="index in indices" :key="index.code" class="index-item">
                <div class="index-item-head">
                  <span>{{ index.name }}</span>
                  <i data-lucide="activity" aria-hidden="true"></i>
                </div>
                <strong class="index-item-value">{{ formatNumber(index.price) }}</strong>
                <div class="index-item-foot">
                  <span>{{ index.market }}</span>
                  <span :class="trendClass(index.change)">{{ formatPct(index.change) }}</span>
                </div>
              </div>
            </div>
            <div v-else-if="loading" class="empty-state compact-empty">
              <i data-lucide="loader-circle" aria-hidden="true"></i>
              <strong>正在读取指数</strong>
              <span>行情代理返回后会显示最新价。</span>
            </div>
            <div v-else class="empty-state compact-empty">
              <i data-lucide="chart-no-axes-combined" aria-hidden="true"></i>
              <strong>暂未获得指数报价</strong>
              <button class="text-button" type="button" @click="refreshAll()">刷新行情</button>
            </div>

            <div class="market-chart-wrap">
              <div class="chart-heading">
                <div>
                  <span class="chart-label">上证指数 · 近 40 个交易日</span>
                  <strong>{{ selectedIndex ? formatNumber(selectedIndex.price) : '--' }}</strong>
                </div>
                <span :class="trendClass(selectedIndex?.change)">{{ selectedIndex ? formatPct(selectedIndex.change) : '--' }}</span>
              </div>
              <div class="market-chart" v-html="chartSvg(indexHistory.map(item => item.close), '#ef6d53', '上证指数近 40 个交易日走势')"></div>
            </div>

            <div class="market-breadth">
              <div class="breadth-label">
                <span>已加载候选池涨跌</span>
                <strong>{{ breadth.up }} / {{ breadth.down }}</strong>
              </div>
              <div class="breadth-bar" aria-label="已加载候选池上涨家数与下跌家数">
                <span class="breadth-up" :style="{ width: `${breadth.upRatio}%` }"></span>
                <span class="breadth-flat" :style="{ width: `${breadth.flatRatio}%` }"></span>
                <span class="breadth-down" :style="{ width: `${breadth.downRatio}%` }"></span>
              </div>
              <div class="breadth-legend">
                <span><i class="legend-dot up"></i>上涨 {{ breadth.up }}</span>
                <span><i class="legend-dot flat"></i>平盘 {{ breadth.flat }}</span>
                <span><i class="legend-dot down"></i>下跌 {{ breadth.down }}</span>
              </div>
            </div>
          </section>
        </section>
```

（原 `chartSvg` 通过 `v-html` 使用，XSS 纪律不变；`alert.time` 列在执行跟踪中省略以压缩密度，完整列表在盯盘中心。）

- [x] **Step 2: app.js 新增 computed**

在 `const conflictSnapshot = ref(null);` 之后插入：

```js
    const presetHits = computed(() => presets.map((preset) => ({
      name: preset.name,
      icon: preset.icon,
      iconClass: preset.iconClass,
      filters: preset.filters,
      count: screenRows.value.filter((row) => (
        row.pe !== null && row.pe <= preset.filters.peMax
        && row.pb !== null && row.pb <= preset.filters.pbMax
        && row.volumeRatio !== null && row.volumeRatio >= preset.filters.volumeMin
        && row.change !== null && row.change >= preset.filters.changeMin
      )).length
    })));

    const strategyStats = computed(() => {
      const running = gridStrategies.value.filter((strategy) => strategy.status === '启用');
      const now = Date.now();
      const pending = running.filter((strategy) => !strategy.lastBacktestAt || now - new Date(strategy.lastBacktestAt).getTime() > 24 * 3600 * 1000);
      const withExcess = gridStrategies.value.filter((strategy) => strategy.latestMetrics && strategy.latestMetrics.excessReturnPct != null);
      return {
        running: running.length,
        pending: pending.length,
        latestExcess: withExcess.length ? withExcess[0].latestMetrics.excessReturnPct : null
      };
    });

    const riskStats = computed(() => {
      const stopHit = activePlans.value.filter((plan) => {
        if (plan.triggered && plan.triggered.stop) return true;
        const quote = quoteFor(plan.code);
        return quote && quote.price != null && quote.price <= plan.stop;
      }).length;
      return { active: activePlans.value.length, stopHit, unread: unreadAlerts.value };
    });
```

在 `return {` 导出对象中 `monitorEnabled,` 之后追加：

```js
      presetHits,
      strategyStats,
      riskStats,
```

- [x] **Step 3: styles.css 追加指挥台样式**（文件末尾追加）

```css
/* ===== P1 unified trading desk ===== */
.desk-kpis {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.desk-kpi {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 16px 18px;
}

.desk-kpi-label {
  font-size: 12px;
  letter-spacing: 0.08em;
  color: var(--muted-strong);
}

.desk-kpi strong {
  font-size: 26px;
  line-height: 1.2;
}

.desk-kpi-note {
  font-size: 12px;
  color: var(--muted-strong);
}

.desk-workspaces {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}

.desk-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px;
}

.preset-hits {
  display: grid;
  gap: 8px;
}

.preset-hit {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.preset-hit:hover {
  border-color: #ef6d53;
}

.preset-hit-name {
  font-weight: 600;
}

.preset-hit-count {
  margin-left: auto;
  font-size: 16px;
}

.desk-stat-rows {
  display: grid;
  gap: 8px;
}

.desk-stat-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  border-radius: 10px;
  background: rgba(148, 163, 184, 0.08);
  font-size: 13px;
}

.desk-stat-row-risk strong {
  color: #ef6d53;
}

@media (max-width: 1260px) {
  .desk-kpis {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .desk-workspaces {
    grid-template-columns: 1fr;
  }
}
```

- [x] **Step 4: 验证 + 提交**

Run: `node --check frontend/app.js` → 语法通过。
浏览器 1280×720：指挥台四卡 + 三工作区渲染，预设命中数与选股器实际结果一致（手动交叉验证一次），空态与主操作可见；1440×900 无横向溢出。

```bash
git add frontend/index.html frontend/app.js frontend/styles.css
git commit -m "feat: 总览升级为今日交易台指挥台"
```

---

### Task 3: 回测 provenance 披露

**Files:**
- Modify: `frontend/index.html:478`（`grid-result-body` 开头插入披露行）
- Modify: `frontend/app.js`（`gridProvenance` computed + 导出）
- Modify: `frontend/styles.css`（追加 `.grid-provenance`）

**Interfaces:**
- Consumes: 回测响应 `gridResult.history[].date`、`gridResult.config.dataAsOf`、`gridResult.metrics.skippedLimitUpDays/skippedLimitDownDays/onePriceLimitUpDays/onePriceLimitDownDays/skippedSuspensionDays`、既有导出 `providerLabel`
- Produces: `gridProvenance`（computed 字符串）

- [x] **Step 1: 插入披露行**

在 `<div v-if="gridResult" class="grid-result-body">`（约 478 行）之后、第一个 `.grid-metrics` 之前插入：

```html
                <p v-if="gridProvenance" class="grid-provenance"><i data-lucide="database" aria-hidden="true"></i>{{ gridProvenance }}</p>
```

- [x] **Step 2: app.js computed**

在 `riskStats` computed 之后插入：

```js
    const gridProvenance = computed(() => {
      const result = gridResult.value;
      if (!result || !Array.isArray(result.history) || !result.history.length) return '';
      const first = result.history[0]?.date || '--';
      const last = result.history[result.history.length - 1]?.date || '--';
      const metrics = result.metrics || {};
      const parts = [
        `数据区间 ${first} ~ ${last}`,
        `${result.history.length} 个交易日`,
        '前复权日线',
        `来源 ${providerLabel.value}`,
        `数据截止 ${result.config?.dataAsOf || last}`,
        `涨跌停跳过 ${metrics.skippedLimitUpDays ?? 0}/${metrics.skippedLimitDownDays ?? 0}`,
        `一字板 ${metrics.onePriceLimitUpDays ?? 0}/${metrics.onePriceLimitDownDays ?? 0}`,
        `停牌 ${metrics.skippedSuspensionDays ?? 0}`
      ];
      return parts.join(' · ');
    });
```

`return {` 导出对象中 `riskStats,` 之后追加 `gridProvenance,`。

- [x] **Step 3: styles.css 追加**

```css
.grid-provenance {
  margin: 0;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(148, 163, 184, 0.08);
  color: var(--muted-strong);
  font-size: 12px;
  line-height: 1.7;
  display: flex;
  align-items: flex-start;
  gap: 8px;
}

.grid-provenance svg {
  flex: 0 0 auto;
  margin-top: 2px;
}
```

- [x] **Step 4: 验证 + 提交**

Run: `node --check frontend/app.js` → 语法通过。
浏览器：运行一次回测，披露行内容与后端响应字段一致（Network 面板交叉核对 `history` 首末日期、`config.dataAsOf`、五个计数字段）；空结果时披露行不显示。

```bash
git add frontend/index.html frontend/app.js frontend/styles.css
git commit -m "feat: 回测报告增加数据来源与模型边界披露行"
```

---

### Task 4: 选股器单滚动模型

**Files:**
- Modify: `frontend/styles.css:629-667`（`.screener-view` 滚动规则块替换）
- Modify: `frontend/styles.css:2985-3001`（1180px 媒体查询内 screener 行调整）

**Interfaces:**
- Consumes: 既有 `.screener-layout`（1527 行起的基础栅格，保持不动）、`.table-responsive` 横向滚动包裹
- Produces: 选股器只有 view-panel 一层纵向滚动

- [x] **Step 1: 替换桌面滚动规则**

将 629-667 行的整块：

```css
.screener-view {
  display: grid !important;
  grid-template-rows: auto minmax(0, 1fr) 210px;
  overflow: hidden !important;
}

.screener-view .view-heading {
  min-height: 0;
}

.screener-view .screener-layout {
  grid-row: 2;
  height: auto;
  min-height: 0;
  margin-bottom: 14px;
}

.screener-view .filter-panel,
.screener-view .results-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: hidden;
}

.screener-view .filter-panel {
  overflow-y: auto;
}

.screener-view .results-table-wrap {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

.screener-view .selected-stock-panel {
  grid-row: 3;
  min-height: 0;
}
```

替换为：

```css
.screener-view {
  display: block !important;
  overflow: auto !important;
}

.screener-view .view-heading {
  min-height: 0;
}

.screener-view .screener-layout {
  grid-row: auto;
  height: auto;
  min-height: 0;
  margin-bottom: 14px;
  align-items: start;
}

.screener-view .filter-panel,
.screener-view .results-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  overflow: visible;
}

.screener-view .filter-panel {
  overflow: visible;
}

.screener-view .results-table-wrap {
  flex: 0 0 auto;
  min-height: 0;
  overflow-x: auto;
  overflow-y: visible;
}

.screener-view .selected-stock-panel {
  grid-row: auto;
  min-height: 0;
}
```

- [x] **Step 2: 调整 1180px 媒体查询**

`@media (max-width: 1180px)` 内 `.screener-view .screener-layout { grid-template-rows: minmax(220px, 1fr) minmax(260px, 1fr); }` 替换为：

```css
  .screener-view .screener-layout {
    grid-template-rows: none;
  }
```

（同块内 `.screener-layout { grid-template-columns: minmax(0, 1fr); }` 与 order 规则保持不动。）

- [x] **Step 3: 验证 + 提交**

浏览器 1280×720 与 1440×900：选股器页面只有 view-panel 一层纵向滚动（筛选面板与结果不再各自滚动）；窄屏下结果表仍可横向滚动；680px 以下行为与改前一致。

```bash
git add frontend/styles.css
git commit -m "fix: 选股器改为页面单滚动模型"
```

---

### Task 5: 手机底部导航与执行复合视图

**Files:**
- Modify: `frontend/index.html`（`</main>` 后插入底部导航；计划与盯盘 section 条件改造；新增执行标签条）
- Modify: `frontend/app.js`（`mobileExecTab` + 2 个 computed + 导出）
- Modify: `frontend/styles.css`（`.bottom-nav` / `.mobile-exec-tabs` + 680px 断点调整）

**Interfaces:**
- Consumes: 既有 `view`/`switchView`/`unreadAlerts`；plans section 当前条件 `v-else-if="view === 'plans'"`、monitor section 当前条件 `v-else-if="view === 'monitor'"`（实施时以实际文件为准）
- Produces: `mobileExecTab`/`execShowsPlans`/`execShowsAlerts`；新视图 id `exec`（键盘快捷键与桌面导航不涉及）

- [x] **Step 1: index.html 插入底部导航**

在 `</main>`（约 607 行）之后、`#app` 闭合 `</div>` 之前插入：

```html
    <nav class="bottom-nav" aria-label="手机端主导航">
      <button type="button" :class="{ 'is-active': view === 'overview' }" @click="switchView('overview')"><i data-lucide="layout-dashboard" aria-hidden="true"></i><span>总览</span></button>
      <button type="button" :class="{ 'is-active': view === 'screener' }" @click="switchView('screener')"><i data-lucide="scan-search" aria-hidden="true"></i><span>选股</span></button>
      <button type="button" :class="{ 'is-active': view === 'grid' }" @click="switchView('grid')"><i data-lucide="grid-3x3" aria-hidden="true"></i><span>网格</span></button>
      <button type="button" :class="{ 'is-active': view === 'exec' }" @click="switchView('exec')"><i data-lucide="clipboard-pen-line" aria-hidden="true"></i><span>执行</span><em v-if="unreadAlerts" class="nav-count">{{ unreadAlerts }}</em></button>
      <button type="button" :class="{ 'is-active': view === 'settings' }" @click="switchView('settings')"><i data-lucide="settings-2" aria-hidden="true"></i><span>更多</span></button>
    </nav>
```

- [x] **Step 2: 执行标签条 + 条件改造**

在 plans section（`v-else-if="view === 'plans'"`）之前插入：

```html
        <section v-else-if="view === 'exec'" class="mobile-exec-tabs" role="tablist" aria-label="执行分组">
          <button type="button" role="tab" :class="['mobile-exec-tab', { 'is-active': mobileExecTab === 'plans' }]" :aria-selected="mobileExecTab === 'plans'" @click="mobileExecTab = 'plans'">交易计划</button>
          <button type="button" role="tab" :class="['mobile-exec-tab', { 'is-active': mobileExecTab === 'alerts' }]" :aria-selected="mobileExecTab === 'alerts'" @click="mobileExecTab = 'alerts'">盯盘提醒</button>
        </section>
```

plans section 条件改为 `v-else-if="view === 'plans' || execShowsPlans"`；monitor section 条件改为 `v-else-if="view === 'monitor' || execShowsAlerts"`。

- [x] **Step 3: app.js 状态**

在 `riskStats` computed 之后插入：

```js
    const mobileExecTab = ref('plans');
    const execShowsPlans = computed(() => view.value === 'exec' && mobileExecTab.value === 'plans');
    const execShowsAlerts = computed(() => view.value === 'exec' && mobileExecTab.value === 'alerts');
```

`return {` 导出对象中 `gridProvenance,` 之后追加：

```js
      mobileExecTab,
      execShowsPlans,
      execShowsAlerts,
```

- [x] **Step 4: styles.css 追加**

```css
.bottom-nav {
  display: none;
}

.mobile-exec-tabs {
  display: none;
}

@media (max-width: 680px) {
  .primary-nav,
  .secondary-nav {
    display: none;
  }

  .content-area {
    padding-bottom: 96px;
  }

  .bottom-nav {
    position: fixed;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 70;
    display: flex;
    align-items: stretch;
    background: #101a2b;
    border-top: 1px solid rgba(148, 163, 184, 0.18);
    padding-bottom: env(safe-area-inset-bottom);
  }

  .bottom-nav button {
    flex: 1 1 0;
    min-width: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 2px;
    padding: 8px 4px 10px;
    background: transparent;
    border: none;
    color: var(--muted-strong);
    font-size: 11px;
    cursor: pointer;
    position: relative;
  }

  .bottom-nav button.is-active {
    color: #ef6d53;
  }

  .bottom-nav .nav-count {
    position: absolute;
    top: 4px;
    right: 18%;
    font-style: normal;
    font-size: 10px;
    font-weight: 700;
    color: #fff;
    background: #ef6d53;
    border-radius: 999px;
    padding: 1px 5px;
  }

  .mobile-exec-tabs {
    display: flex;
    gap: 8px;
    margin-bottom: 14px;
  }

  .mobile-exec-tab {
    flex: 1 1 0;
    padding: 10px 12px;
    border-radius: 10px;
    border: 1px solid rgba(148, 163, 184, 0.25);
    background: transparent;
    color: var(--muted-strong);
    font-size: 13px;
    font-weight: 600;
    cursor: pointer;
  }

  .mobile-exec-tab.is-active {
    border-color: #ef6d53;
    color: #eef2f8;
    background: rgba(239, 109, 83, 0.12);
  }
}
```

（追加在"===== P1 unified trading desk ====="块内；680px 块中的 `.primary-nav` 隐藏会覆盖既有 680px 块中的图标导航样式——按 CSS 顺序后定义者生效，需追加在文件末尾。）

- [x] **Step 5: 验证 + 提交**

Run: `node --check frontend/app.js` → 语法通过。
浏览器 390×844：底部五项文字导航显示且切换正确；"执行"内两个标签各自显示计划表单+列表 / 提醒列表；顶部不再出现图标导航行；桌面 1280×720 无底部导航、计划/盯盘入口不受影响。

```bash
git add frontend/index.html frontend/app.js frontend/styles.css
git commit -m "feat: 手机端底部导航与执行复合视图"
```

---

### Task 6: 设置页三标签与保存按钮状态

**Files:**
- Modify: `frontend/modules/constants.js`（新增 `SETTINGS_TABS`）
- Modify: `frontend/app.js`（导入 `SETTINGS_TABS`、`settingsTab` ref、`settingsDirty` computed、`appliedSettings` 快照 + 导出）
- Modify: `frontend/index.html`（设置区标签条 + 行按标签分组 + 保存按钮条件高亮）
- Modify: `frontend/styles.css`（`.settings-tabs`）

**Interfaces:**
- Consumes: 既有 `settingsDraft`/`loadSettings`/`saveSettings`/`dataSources`
- Produces: `settingsTab`/`settingsTabs`/`settingsDirty`

- [x] **Step 1: constants.js 追加**

```js
export const SETTINGS_TABS = [
  { id: 'workspace', label: '工作台' },
  { id: 'data', label: '数据获取' },
  { id: 'connection', label: '连接状态' }
];
```

- [x] **Step 2: app.js 导入与状态**

第 1 行导入列表中加入 `SETTINGS_TABS`：

```js
import { STORAGE_KEY, DEFAULT_WATCHLIST, DEFAULT_FILTERS, DEFAULT_ALERTS, PRESETS, NAV_ITEMS, VIEW_META, SETTINGS_TABS } from './modules/constants.js';
```

`const settingsLoading = ref(false);` 之后插入：

```js
    const settingsTab = ref('workspace');
    const appliedSettings = ref(null);
    const settingsDirty = computed(() => Boolean(appliedSettings.value) && JSON.stringify(settingsDraft) !== JSON.stringify(appliedSettings.value));
```

`loadSettings` 中成功拿到 `payload.data` 并 `Object.assign(settingsDraft, ...)` 之后追加：

```js
          appliedSettings.value = JSON.parse(JSON.stringify(settingsDraft));
```

（`saveSettings` 成功保存后同样追加该行，使保存按钮恢复平静态；两个函数的现有逻辑不变。）

`return {` 导出对象中 `settingsLoading,` 附近追加：

```js
      settingsTab,
      settingsTabs: SETTINGS_TABS,
      settingsDirty,
```

- [x] **Step 3: index.html 设置区改造**

在 `<div class="settings-grid">` 之前插入：

```html
          <div class="settings-tabs" role="tablist" aria-label="设置分组">
            <button v-for="tab in settingsTabs" :key="tab.id" type="button" role="tab" :class="['settings-tab', { 'is-active': settingsTab === tab.id }]" :aria-selected="settingsTab === tab.id" @click="settingsTab = tab.id">{{ tab.label }}</button>
          </div>
```

各 `settings-row` 按归属加 `v-if`：`工作区名称`、`默认账户资金`、`冲突处理策略` → `v-if="settingsTab === 'workspace'"`；`行情刷新间隔`、`自动故障切换`、三个来源 select → `v-if="settingsTab === 'data'"`；`v-for="source in dataSources"` 行 → `v-if="settingsTab === 'connection'"`。

顶部保存按钮改为条件高亮：

```html
<button class="button" :class="settingsDirty ? 'button-primary' : 'button-secondary'" type="button" :disabled="settingsLoading" @click="saveSettings"><i data-lucide="save" aria-hidden="true"></i>保存设置</button>
```

- [x] **Step 4: styles.css 追加**

```css
.settings-tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 14px;
}

.settings-tab {
  padding: 9px 16px;
  border-radius: 10px;
  border: 1px solid rgba(148, 163, 184, 0.25);
  background: transparent;
  color: var(--muted-strong);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
}

.settings-tab.is-active {
  border-color: #ef6d53;
  color: #eef2f8;
  background: rgba(239, 109, 83, 0.12);
}
```

- [x] **Step 5: 验证 + 提交**

Run: `node --check frontend/app.js` → 语法通过。
浏览器：三标签切换正常、各行归属正确；改动设置后保存按钮变主色，保存成功后恢复；冲突处理策略行在"工作台"标签内可保存（与 Task 5/后端策略联动）。

```bash
git add frontend/modules/constants.js frontend/app.js frontend/index.html frontend/styles.css
git commit -m "feat: 设置页改为三标签并按未保存状态高亮保存按钮"
```

---

### Task 7: 回归、手动验证与收尾

**Files:**
- 无代码改动

- [x] **Step 1: 全量回归**

Run: `python -m pytest tests/ -q` 与 `node --check frontend/app.js`
Expected: 38 passed / 语法通过（本计划不改后端，回归确认无意外破坏）。

- [x] **Step 2: 浏览器整体验证（按规格验证节）**

- 桌面 1280×720 / 1440×900：五页逐页检查无内容重叠、无意外横向溢出、选股器单滚动、指挥台与披露行正常。
- 手机 390×844：底部导航、执行复合视图、宽表横向滚动、提醒列表。
- 回测披露行与 Network 响应字段交叉核对。

- [x] **Step 3: 完成 feature 分支**

```bash
git flow feature finish unified-trading-desk-ux
```

Expected: `--no-ff` 合入 develop，分支删除。
