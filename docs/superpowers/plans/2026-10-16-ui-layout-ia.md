# UI 第③a批（布局 IA）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让同一事实只写一遍——导航按工作流分组且桌面手机同构、行情状态收归顶栏单控件、总览首屏去掉重复指标、8 个视图标题唯一化、5 处「有代码点不动」的入口补上下钻。

**Architecture:** 前端单侧改造，零后端改动。导航从 `NAV_ITEMS` 的平铺数组升级为「置顶项 + 5 组分区」的结构化常量（`NAV_GROUPS` + 每项的 `group`/`shortLabel`）；`App.vue` 壳层按分区渲染，桌面侧栏显示组标题、手机底部栏 4 格直达 + 「更多」底部 sheet 承载同一套分组；行情新鲜度合并进顶栏唯一控件（状态 + 时间 + 刷新）；总览 4 张 KPI 卡压成一行状态带，面板删除逐字重复的指标行；视图标题交给 `VIEW_META` 单一驱动，8 个视图删除装饰性 h2/说明与 34 处英文 kicker；下钻统一走已存在的 `selectStock(code, fromView)`。

**Tech Stack:** Vue 3 + TypeScript 5.9（strict）+ Vite 8 + Pinia 4 + vitest 4 + @vue/test-utils + lucide。样式集中在单文件 `frontend/src/styles.css`。

## Global Constraints

- **后端零改动**：不得修改 `backend/`、不得改 API/schema/迁移。本批 pytest 应保持 679 项全绿。
- **UI 文案一律中文**：不新增任何大写英文装饰标签（正则 `>[A-Z][A-Z /]{3,}<` 必须无匹配）。
- **绝不使用模拟值填充缺失数据**：缺失显示 `--` 或空态；行情三态（`live`/`stale`/`error`）必须如实披露，警示强度不得弱于现状。
- **保留现有 API 字段名与 store 导出名**（除本计划明确删除的 5 个：`mobileExecTab`/`execShowsPlans`/`execShowsAlerts`/`todayLabel`/`marketStatus`——最后一个见文末「与 spec 的偏差记录」）。
- **`NAV_ITEMS` 数量（7）与顺序不变**——`app.ts:97` 的数字键快捷键 `{1:overview,2:screener,3:grid,4:plans,5:monitor,6:portfolio}` 依赖该顺序，本批不得改动顺序或数量。
- **`VIEW_META` 不改**（`tests/frontend/constants.test.ts:40-46` 断言其覆盖所有导航项且长度为 2）。
- **既有测试硬约束（不得破坏）**：`tests/frontend/useAlertsStore.test.ts` 挂载 `App.vue`，依赖 ① 铃铛按钮 `aria-label="通知中心"`；② `data-testid="alert-code-chip"` 与其 `openFor({ code, source })` 行为。凡改通知面板只能**新增兄弟元素**。
- **图标纪律**：新引用的 kebab 图标必须在 `frontend/src/modules/lucideIcons.ts` 注册；**不得删除 `MoreHorizontal` 注册**（第 4 个任务要用它做「更多」格）。
- **时间戳**：机器时间戳统一 `createdAtMs`（epoch 毫秒）。
- **门禁**：每个任务结束时 `npm run verify` 全绿（vitest + `vue-tsc --noEmit` + pytest）。
- **提交**：中文主题行 + Conventional Commits 前缀；一个任务一个提交。
- **分支**：`feature/ui-layout-ia`（已存在，勿新建）。

---

## File Structure

| 文件 | 职责 | 任务 |
|---|---|---|
| `frontend/src/modules/constants.ts` | 导航分区与手机短标签常量、应用版本号 | 1 |
| `frontend/src/stores/useQuotesStore.ts` | 行情状态标签、`view` 白名单归一、拆除 `exec` 三件套与 `todayLabel`、清理 `marketStatus` | 2, 5, 6, 7 |
| `frontend/src/App.vue` | 壳层：侧栏分区、去假 UI、状态控件、底部栏 + 更多抽屉 | 2, 3, 4, 5 |
| `frontend/src/styles.css` | 新增状态控件/抽屉/状态带样式；删除废弃规则 | 2, 3, 4, 5, 6, 7 |
| `frontend/src/views/ViewOverview.vue` | 状态带 + 面板去重 | 6, 7 |
| `frontend/src/views/ViewGrid.vue` `ViewMonitor.vue` `ViewScreener.vue` `ViewPlans.vue` `ViewPortfolio.vue` `ViewSettings.vue` `ViewStockDetail.vue` | 标题收敛 + 下钻入口 | 7, 8 |
| `tests/frontend/constants.test.ts` | 常量新字段断言 | 1 |
| `tests/frontend/useQuotesStore.test.ts`（新建） | 状态标签、`view` 归一、已移除导出断言 | 2, 5, 7 |
| `tests/frontend/AppShell.test.ts`（新建） | 侧栏分区、手机 5 格、更多抽屉、徽标、删除项断言 | 3, 4, 5 |
| `tests/frontend/ViewOverview.test.ts`（新建） | 状态带与面板去重 | 6 |
| `tests/frontend/ViewPlans.test.ts` `ViewPortfolio.test.ts` `ViewStockDetail.test.ts` `ViewSettings.test.ts`（增补） | 下钻与返回文案 | 8 |
| `AGENTS.md` `CHANGELOG.md` `ROADMAP.md` | 文档收口 | 9 |

**共享测试挂载样板**（第 3/4/5 任务的 `AppShell.test.ts`、第 6 任务的 `ViewOverview.test.ts` 均复用；照抄 `tests/frontend/useAlertsStore.test.ts:5-19` 与 `ViewScreener.test.ts:11-16` 的模式）：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import App from '@/App.vue';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { useScreenerStore } from '@/stores/useScreenerStore';
import { useStrategyStore } from '@/stores/useStrategyStore';
import type { Alert } from '@/types/models';

vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));
vi.mock('@/app', () => ({ appOptions: { setup: vi.fn() } }));
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return { ...actual, requestJson: vi.fn() };
});

// AppShell.test.ts 额外需要视图 stub（否则子视图会拉真实 store 副作用）：
const stubView = { template: '<div />' };
const viewStubs = {
  components: {
    'view-overview': stubView, 'view-screener': stubView, 'view-stock-detail': stubView,
    'view-grid': stubView, 'view-plans': stubView, 'view-monitor': stubView,
    'view-portfolio': stubView, 'view-settings': stubView,
  },
};

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
});
```

（`ViewOverview.test.ts` 用同一套 mock 与 `beforeEach`，但把 `import App` 换成 `import ViewOverview from '@/views/ViewOverview.vue'`，且**不**需要 `viewStubs`。）

---

### Task 1: 常量层（导航分区 + 手机短标签 + 应用版本）

**Files:**
- Modify: `frontend/src/modules/constants.ts:48-56`（`NAV_ITEMS` 区块及其上方）
- Test: `tests/frontend/constants.test.ts`

**Interfaces:**
- Consumes: 无
- Produces:
  - `NAV_GROUPS: readonly { id: 'research'|'validation'|'execution'|'risk'|'system'; label: string }[]`（数组顺序即侧栏渲染顺序）
  - `NAV_ITEMS: readonly { id: string; label: string; icon: string; shortLabel: string; group: NavGroupId | null }[]`
  - `APP_VERSION: string`

- [ ] **Step 1: 写失败测试**

该文件**既有风格是 `node:assert/strict` + `test(...)`**（不是 `describe/it/expect`），追加内容必须与之一致：把 `NAV_GROUPS, APP_VERSION` 加入第 3-11 行的既有 import，把 `import { readFileSync } from 'node:fs';` 加在第 2 行之后，并在文件末尾追加：

```ts
test('NAV_GROUPS 分区顺序与成员覆盖', () => {
  assert.deepEqual(
    NAV_GROUPS.map((group) => group.id),
    ['research', 'validation', 'execution', 'risk', 'system']
  );
  assert.deepEqual(
    NAV_GROUPS.map((group) => group.label),
    ['研究', '验证', '执行', '风控', '系统']
  );
  for (const group of NAV_GROUPS) {
    assert.ok(
      NAV_ITEMS.filter((item) => item.group === group.id).length > 0,
      `${group.id} 至少 1 个成员`
    );
  }
});

test('NAV_ITEMS 具备 shortLabel 与 group，且顺序不变', () => {
  for (const item of NAV_ITEMS) {
    assert.equal(typeof item.shortLabel, 'string');
    assert.ok(item.shortLabel.length > 0);
  }
  assert.deepEqual(
    NAV_ITEMS.map((item) => item.id),
    ['overview', 'screener', 'grid', 'plans', 'monitor', 'portfolio', 'settings'],
    '顺序被 app.ts:97 快捷键契约锁定'
  );
  assert.deepEqual(
    NAV_ITEMS.filter((item) => item.group === null).map((item) => item.id),
    ['overview']
  );
});

test('APP_VERSION 与 package.json 同步', () => {
  const pkg = JSON.parse(readFileSync(new URL('../../package.json', import.meta.url), 'utf8')) as {
    version: string;
  };
  assert.equal(APP_VERSION, pkg.version);
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/constants.test.ts`
Expected: FAIL —— `NAV_GROUPS` / `APP_VERSION` 未导出（`item.shortLabel` 为 undefined）。

- [ ] **Step 3: 实现常量**

用下列内容替换 `frontend/src/modules/constants.ts:48-56` 的 `NAV_ITEMS` 定义块：

```ts
/** 应用版本：与 package.json 保持同步（constants.test.ts 守卫）。侧栏底部展示。 */
export const APP_VERSION = '0.7.1';

/** 主导航分区（顺序即侧栏渲染顺序）。总览不属任何分区，置顶展示。 */
export const NAV_GROUPS = [
  { id: 'research', label: '研究' },
  { id: 'validation', label: '验证' },
  { id: 'execution', label: '执行' },
  { id: 'risk', label: '风控' },
  { id: 'system', label: '系统' },
] as const;

export type NavGroupId = (typeof NAV_GROUPS)[number]['id'];

/**
 * 主导航项。顺序与数量是外部契约：app.ts 的数字键快捷键按此顺序映射，不得改动。
 * shortLabel 仅用于手机底部栏（宽度受限）；label 用于桌面侧栏与更多抽屉。
 */
export const NAV_ITEMS = [
  { id: 'overview', label: '总览', icon: 'layout-dashboard', shortLabel: '总览', group: null },
  { id: 'screener', label: '选股器', icon: 'scan-search', shortLabel: '选股', group: 'research' },
  { id: 'grid', label: '策略', icon: 'grid-3x3', shortLabel: '策略', group: 'validation' },
  { id: 'plans', label: '交易计划', icon: 'clipboard-pen-line', shortLabel: '计划', group: 'execution' },
  { id: 'monitor', label: '盯盘中心', icon: 'radar', shortLabel: '盯盘', group: 'execution' },
  { id: 'portfolio', label: '组合风险', icon: 'gauge', shortLabel: '风控', group: 'risk' },
  { id: 'settings', label: '个人中心', icon: 'user-round', shortLabel: '我的', group: 'system' },
] as const satisfies readonly {
  id: string;
  label: string;
  icon: string;
  shortLabel: string;
  group: NavGroupId | null;
}[];
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run tests/frontend/constants.test.ts tests/frontend/lucideIcons.test.ts`
Expected: PASS（含原有断言与图标注册断言）。

- [ ] **Step 5: 全量门禁**

Run: `npm run verify`
Expected: 全绿（`satisfies` 需 `vue-tsc` 通过；后端 679 项不受影响）。

- [ ] **Step 6: 提交**

```bash
git add frontend/src/modules/constants.ts tests/frontend/constants.test.ts
git commit -m "feat: 导航常量新增分区与手机短标签，并引入应用版本号"
```

---

### Task 2: 行情状态控件（顶栏唯一事实源）

**Files:**
- Modify: `frontend/src/stores/useQuotesStore.ts:38-56`（新增两个 computed）、`:220-264`（导出区）
- Modify: `frontend/src/App.vue:98-105`（`topbar-title-row` 去掉徽标）、`:232-235`（换成状态控件）、`:272`（页脚去重复 provider）、`:325-339`（解构）
- Modify: `frontend/src/styles.css:556-580`（`.demo-badge*` 区域，替换为状态控件态样式）
- Test: `tests/frontend/useQuotesStore.test.ts`（新建）

**Interfaces:**
- Consumes: `NAV_ITEMS` 等常量（Task 1 不参与本任务逻辑）
- Produces:
  - `marketStatusLabel: ComputedRef<'真实行情' | '缓存行情' | '行情连接中'>`
  - `marketStatusTimeLabel: ComputedRef<string>`（今天 → `HH:MM`；跨日 → `MM/DD HH:MM`）
  - 新的 DOM 契约：`button[data-testid="market-status-control"]`，其 `data-state` 为 `dataState` 原值（`connecting`/`live`/`stale`/`error`）

- [ ] **Step 1: 写失败测试**

新建 `tests/frontend/useQuotesStore.test.ts`：

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return { ...actual, requestJson: vi.fn() };
});

import { useQuotesStore } from '@/stores/useQuotesStore';

describe('行情状态标签', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it('三态标签与跨日时间', () => {
    const quotes = useQuotesStore();
    quotes.dataState = 'live';
    expect(quotes.marketStatusLabel).toBe('真实行情');
    quotes.dataState = 'stale';
    expect(quotes.marketStatusLabel).toBe('缓存行情');
    quotes.dataState = 'connecting';
    expect(quotes.marketStatusLabel).toBe('行情连接中');

    // 今天 → 仅时刻
    quotes.market.fetchedAt = Date.now();
    const today = quotes.marketStatusTimeLabel;
    expect(today).toMatch(/^\d{2}:\d{2}$/);

    // 跨日 → 带日期（解析不可用的时间戳退回 '--'）
    quotes.market.fetchedAt = new Date('2026-01-05T09:30:00').getTime();
    expect(quotes.marketStatusTimeLabel).not.toMatch(/^\d{2}:\d{2}$/);
    quotes.market.fetchedAt = 0;
    expect(quotes.marketStatusTimeLabel).toBe('--');
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/useQuotesStore.test.ts`
Expected: FAIL —— `marketStatusLabel` / `marketStatusTimeLabel` 未定义。

- [ ] **Step 3: 实现 store computed**

在 `frontend/src/stores/useQuotesStore.ts` 的 `fetchedLabel` computed（`:53`）**之后**插入（必须在其后：本块引用了 `lastUpdatedLabel`）：

```ts
  /** 顶栏状态控件文案：与既有三态语义一一对应（勿改措辞，测试与人工核对依赖）。 */
  const marketStatusLabel = computed(() =>
    dataState.value === 'live' ? '真实行情' : dataState.value === 'stale' ? '缓存行情' : '行情连接中'
  );

  /** 顶栏状态控件时间：跨日时必须带日期，否则缓存数据无从分辨。当天分支复用 lastUpdatedLabel（避免该导出失去渲染点）。 */
  const marketStatusTimeLabel = computed(() => {
    if (!market.fetchedAt) return '--';
    const fetched = new Date(market.fetchedAt);
    const now = new Date();
    const sameDay =
      fetched.getFullYear() === now.getFullYear() &&
      fetched.getMonth() === now.getMonth() &&
      fetched.getDate() === now.getDate();
    return sameDay
      ? lastUpdatedLabel.value
      : `${formatDateShort(market.fetchedAt)} ${formatTimeShort(market.fetchedAt)}`;
  });
```

并在返回对象中 `lastUpdatedLabel,` 之后追加：

```ts
    marketStatusLabel,
    marketStatusTimeLabel,
```

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run tests/frontend/useQuotesStore.test.ts`
Expected: PASS

- [ ] **Step 5: 改造顶栏与页脚模板**

`frontend/src/App.vue` 三处编辑：

① `:98-104` 的标题行去掉徽标（`h1` 保留，`demo-badge` 整块删除）：

```vue
          <div class="topbar-title-row">
            <h1>{{ currentViewMeta.title }}</h1>
          </div>
```

② `:232-235` 的 `.topbar-date` 替换为状态控件：

```vue
          <button
            class="topbar-date market-status-control"
            type="button"
            :data-state="dataState"
            data-testid="market-status-control"
            data-tooltip="刷新行情"
            :title="`${providerLabel} · ${dataStatusText}`"
            :aria-label="`${marketStatusLabel}，${marketStatusTimeLabel}，点击刷新行情`"
            @click="refreshAll()"
          >
            <span class="status-dot" :class="dataState"></span>
            <span class="market-status-label">{{ marketStatusLabel }}</span>
            <span class="market-status-time">{{ marketStatusTimeLabel }}</span>
            <i data-lucide="refresh-cw" aria-hidden="true" :class="{ spinning: loading }"></i>
          </button>
```

③ `:272` 页脚去掉重复的 provider，保留免责声明：

```vue
          <span>研究工具不构成投资建议</span>
```

解构区 `:326-339` 增补 `marketStatusLabel, marketStatusTimeLabel,`（`providerLabel`/`dataStatusText` 仍被控件使用，保留）；**并删除 `lastUpdatedLabel,`**——它的唯一渲染点就是被替换掉的旧 `.topbar-date`（`:234`），留着会触发 eslint 未使用变量，而 store 导出本身仍被 `marketStatusTimeLabel` 内部消费（Task 1 的 Step 已核对）。

> 提示文案分工：`data-tooltip="刷新行情"` 沿用既有 CSS tooltip 惯例；`providerLabel`/`dataStatusText` 按 spec §6 进原生 `title`（浏览器悬停可见），`aria-label` 承担「状态 + 时间 + 点击刷新行情」的读屏语义。`loading` 时的 `spinning` 类与 `.spinning` 样式（`styles.css:901`）保持现状。

- [ ] **Step 6: 补 CSS 并删除废弃徽标样式**

`frontend/src/styles.css`：删除 `.demo-badge`（`:556`）、`.demo-badge-stale`（`:570`）与 `.demo-badge .live-dot`（`:576`）三条规则——即 `:556-580` 整段（已核对该段连续、无与其他选择器共用；删前再以 `Get-ChildItem frontend\src -Recurse -Include *.vue | Select-String -Pattern 'demo-badge'` 确认 0 命中），随后在 `.topbar-date` 变体规则（`:682` 起）之后追加（**文字色须用浅色面 token**：`--status-gold`/`--status-coral` 是浅色调，给状态点填充尚可（`.status-dot.stale/.error` 现用），但作为白底顶栏的**文字**色对比度不足，会弱化现状警示强度）：

```css
.market-status-control {
  gap: var(--space-2);
  width: auto;
  height: auto;
  min-height: 28px;
  padding: 0 var(--space-2);
  border-radius: 999px;
}

.market-status-label,
.market-status-time {
  font-size: var(--fs-xs);
  white-space: nowrap;
}

.market-status-time {
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}

/* 三态签名与已删除的 .demo-badge / .demo-badge-stale 一一对应，error 更强不更弱 */
.market-status-control[data-state='live'] .market-status-label {
  color: var(--green);
}

.market-status-control[data-state='stale'] {
  border-color: var(--gold-line-soft);
  background: var(--gold-soft);
  color: var(--gold);
}

.market-status-control[data-state='error'] {
  border-color: var(--coral-line);
  background: var(--coral-soft);
  color: var(--coral);
}
```

（`.status-dot` 及其 `.live/.stale/.error` 变体样式保留：本任务删掉的是侧栏区块的用法，样式在 Task 3 之后仍被本控件消费。）

- [ ] **Step 7: 运行前端全量测试**

Run: `npx vitest run`
Expected: PASS（`useAlertsStore.test.ts` 仍须通过——铃铛 `aria-label="通知中心"` 与 `alert-code-chip` 未被触碰）。

- [ ] **Step 8: 提交**

```bash
git add frontend/src/App.vue frontend/src/stores/useQuotesStore.ts frontend/src/styles.css tests/frontend/useQuotesStore.test.ts
git commit -m "feat: 行情状态收归顶栏单控件，页脚去掉重复的行情源"
```

---

### Task 3: 桌面侧栏分区 + 删除假 UI + 底部版本号

**Files:**
- Modify: `frontend/src/App.vue:12-92`（`aside.sidebar` 整块）
- Modify: `frontend/src/styles.css:364-370`（`.sidebar-section-label` 微调）、`:423-471`（删除 `.sidebar-note*` 与 `.user-profile`）
- Test: `tests/frontend/AppShell.test.ts`（新建）

**Interfaces:**
- Consumes: Task 1 的 `NAV_GROUPS`、`NAV_ITEMS.group/shortLabel`、`APP_VERSION`
- Produces: 侧栏分区 DOM 契约——每个分区标题为 `.sidebar-section-label` 且文本 ∈ `['研究','验证','执行','风控','系统']`；`.nav-item` 数量为 7

- [ ] **Step 1: 写失败测试**

新建 `tests/frontend/AppShell.test.ts`（含前述共享样板 + `viewStubs`）：

```ts
import App from '@/App.vue';

describe('桌面侧栏分区（spec §4）', () => {
  it('按 5 个分区渲染组标题，且总览在分区之外置顶', () => {
    const wrapper = mount(App, { global: viewStubs });
    const labels = wrapper.findAll('.sidebar .sidebar-section-label').map((node) => node.text());
    expect(labels).toEqual(['研究', '验证', '执行', '风控', '系统']);
    const navItems = wrapper.findAll('.sidebar .nav-item');
    expect(navItems.length).toBe(7);
    expect(navItems[0].text()).toContain('总览');
    wrapper.unmount();
  });

  it('假 UI 已删除', () => {
    const wrapper = mount(App, { global: viewStubs });
    expect(wrapper.find('.user-profile').exists()).toBe(false);
    expect(wrapper.find('.market-switcher').exists()).toBe(false);
    expect(wrapper.find('.sidebar-data-note').exists()).toBe(false);
    expect(wrapper.find('.sidebar-note').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('林默');
    wrapper.unmount();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/AppShell.test.ts`
Expected: FAIL —— 组标题尚不存在（`labels` 为空数组）；`.user-profile` 仍存在。

- [ ] **Step 3: 改造侧栏模板**

`frontend/src/App.vue` 的 `<aside class="sidebar">` 内：删除 `market-switcher` 区块（`:21-30`）、`sidebar-section-label`「数据连接」与 `sidebar-data-note` 区块（`:50-57`）、`sidebar-note` 区块（`:72-80`）、`user-profile` 区块（`:82-91`）；`primary-nav`（`:32-48`）替换为分区渲染，并在主题开关之后追加版本号：

```vue
      <nav class="primary-nav" aria-label="主导航">
        <template v-for="section in navSections" :key="section.key">
          <div v-if="section.group" class="sidebar-section-label">{{ section.group.label }}</div>
          <button
            v-for="item in section.items"
            :key="item.id"
            class="nav-item"
            :class="{ 'is-active': view === item.id }"
            type="button"
            :aria-label="item.label"
            @click="switchView(item.id)"
          >
            <i :data-lucide="item.icon" aria-hidden="true"></i>
            <span>{{ item.label }}</span>
            <em v-if="item.id === 'settings' && unreadTotalCount" class="nav-count">{{
              unreadTotalCount > 99 ? '99+' : unreadTotalCount
            }}</em>
          </button>
        </template>
      </nav>
```

主题开关之后新增：

```vue
      <span class="sidebar-version">v{{ APP_VERSION }}</span>
```

`<script setup>` 中把 `const navItems = NAV_ITEMS;`（`:344`）替换为：

```ts
/** 侧栏分区：置顶项（group === null）在前，随后按 NAV_GROUPS 顺序展开。 */
const navSections = computed(() => [
  { key: 'top', group: null as { id: string; label: string } | null, items: NAV_ITEMS.filter((item) => item.group === null) },
  ...NAV_GROUPS.map((group) => ({
    key: group.id,
    group: group as { id: string; label: string } | null,
    items: NAV_ITEMS.filter((item) => item.group === group.id),
  })),
]);
```

并更新 import：`import { NAV_GROUPS, NAV_ITEMS, APP_VERSION } from '@/modules/constants';`（`computed` 需从 `vue` 引入——检查 `:302` 的既有 import 并加入）。

**同任务内必须清理解构**：`market-switcher` 是 `App.vue` 里 `marketStatus` 的唯一渲染点（`:29`），删掉它之后 `marketStatus`（`:328` 解构）成为未使用变量，会被 pre-commit 的 eslint 拦下 → 从 `:326-339` 的解构中删除 `marketStatus,`。（`providerLabel`/`dataStatusText` 改由 Task 2 的顶栏状态控件消费，保留。）store 里 `marketStatus` computed 的删除在 Task 6（见文末「与 spec 的偏差记录」）。

- [ ] **Step 4: 清理 CSS**

`frontend/src/styles.css`：
- 删除市场卡样式整段 `:238-276`：`.market-switcher`、`.market-switcher-copy`、`.market-switcher-copy > div`、`.market-switcher-copy strong`、`.market-switcher-copy span:last-child`、`.market-state`——**先** `Get-ChildItem frontend\src -Recurse -Include *.vue | Select-String -Pattern 'market-switcher|market-state'` 确认 0 命中（唯二引用在 App.vue:21-30 与本 Step 已删的解构）。（`@media` 内的同名残留见 Task 5。）
- 删除 `.sidebar-data-note`、`.sidebar-data-note > div`、`.sidebar-data-note strong`、`.sidebar-data-note span:last-child`（`:372-393`）
- 删除 `.sidebar-note`、`.sidebar-note-icon`、`.sidebar-note-icon svg`、`.sidebar-note > div:last-child`、`.sidebar-note strong`、`.sidebar-note span`（`:423-463`）
- 删除 `.user-profile` 与 `.avatar` 相关声明（先用 `Get-ChildItem frontend\src -Recurse -Include *.vue | Select-String -Pattern 'user-profile|class="avatar"'` 确认模板中已无引用；`.stock-avatar` 是另一个类，勿误删）
- `.sidebar-section-label`（`:364-370`）微调：`text-transform: uppercase` 删除（中文无意义）、`letter-spacing: 0.11em` 改为 `0.04em`（CJK 字距）
- 新增：

```css
.sidebar-version {
  margin: 0 var(--space-3) var(--space-3);
  color: var(--sidebar-muted);
  font-size: var(--fs-xs);
  font-variant-numeric: tabular-nums;
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `npx vitest run tests/frontend/AppShell.test.ts tests/frontend/useAlertsStore.test.ts`
Expected: PASS

- [ ] **Step 6: 门禁**

Run: `npm run verify`
Expected: 全绿

- [ ] **Step 7: 提交**

```bash
git add frontend/src/App.vue frontend/src/styles.css tests/frontend/AppShell.test.ts
git commit -m "feat: 侧栏按工作流分区，删除假 UI 与重复的行情源区块"
```

---

### Task 4: 手机底部栏 M1（4 格直达 + 更多抽屉 + 徽标）

**Files:**
- Modify: `frontend/src/App.vue:279-296`（`bottom-nav` 区块）、`<script setup>`（`moreOpen` 等状态）
- Modify: `frontend/src/styles.css:3714-3720` 与 `:3731-3776`（`.bottom-nav` 区域附近追加 `.more-sheet*`）
- Test: `tests/frontend/AppShell.test.ts`

**Interfaces:**
- Consumes: Task 1 常量；Task 2/3 的 `unreadTotalCount`、`switchView`、`renderIcons`
- Produces: DOM 契约——`button[aria-label="更多"]`；抽屉容器 `.more-sheet`；抽屉项 `.more-sheet-item`（三个：策略/组合风险/个人中心）

- [ ] **Step 1: 写失败测试**

在 `tests/frontend/AppShell.test.ts` 追加：

```ts
describe('手机底部栏与更多抽屉（spec §5）', () => {
  it('底部栏 5 格：总览/选股/计划/盯盘/更多', async () => {
    const wrapper = mount(App, { global: viewStubs });
    // 只读标签 span：DEFAULT_ALERTS 自带 1 条未读，em.nav-count 会污染 button.text()
    const slots = wrapper.findAll('.bottom-nav > button span').map((node) => node.text());
    expect(slots).toEqual(['总览', '选股', '计划', '盯盘', '更多']);
    wrapper.unmount();
  });

  it('更多抽屉按同一套分区渲染，且只含未在格子里出现的项', async () => {
    const wrapper = mount(App, { global: viewStubs });
    expect(wrapper.find('.more-sheet').exists()).toBe(false);
    await wrapper.find('.bottom-nav button[aria-label="更多"]').trigger('click');
    const sheet = wrapper.find('.more-sheet');
    expect(sheet.exists()).toBe(true);
    expect(sheet.findAll('.more-sheet-group').map((node) => node.text())).toEqual(['验证', '风控', '系统']);
    expect(sheet.findAll('.more-sheet-item span').map((node) => node.text())).toEqual(['策略', '组合风险', '个人中心']);
    wrapper.unmount();
  });

  it('点击抽屉项切视图并关闭抽屉', async () => {
    const wrapper = mount(App, { global: viewStubs });
    await wrapper.find('.bottom-nav button[aria-label="更多"]').trigger('click');
    await wrapper.findAll('.more-sheet-item')[0].trigger('click'); // 第一项 = 策略
    const quotes = useQuotesStore();
    expect(quotes.view).toBe('grid');
    expect(wrapper.find('.more-sheet').exists()).toBe(false);
    wrapper.unmount();
  });

  it('未读徽标出现在「更多」格、抽屉个人中心行与桌面侧栏个人中心项（作用域查询）', async () => {
    const workspace = useWorkspaceStore();
    workspace.alerts = [
      { id: 'a1', kind: 'alert', title: 'x', message: 'y', read: false, createdAtMs: 1 },
      { id: 'a2', kind: 'alert', title: 'z', message: 'w', read: true, createdAtMs: 2 },
    ] as Alert[];
    const wrapper = mount(App, { global: viewStubs });
    const more = wrapper.find('.bottom-nav button[aria-label="更多"]');
    expect(more.find('.nav-count').text()).toBe('1');
    const sidebarSettings = wrapper
      .findAll('.sidebar .nav-item')
      .find((node) => node.text().includes('个人中心'));
    expect(sidebarSettings!.find('.nav-count').text()).toBe('1');
    await more.trigger('click');
    const settingsRow = wrapper.findAll('.more-sheet-item')[2];
    expect(settingsRow.find('.nav-count').text()).toBe('1');
    wrapper.unmount();
  });
});
```

（`useQuotesStore` / `useWorkspaceStore` / `Alert` 类型补进文件顶部 import；`nav-count` 的值断言用 1 条未读 + 1 条已读固定住。）

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/AppShell.test.ts`
Expected: FAIL —— 底部栏仍是 `总览/选股/网格/执行/我的`，`.more-sheet` 不存在。

- [ ] **Step 3: 实现底部栏与抽屉**

`frontend/src/App.vue` 中 `bottom-nav`（`:279-296`）整体替换：

```vue
    <nav class="bottom-nav" aria-label="手机端主导航">
      <button
        v-for="slot in mobileBarItems"
        :key="slot.id"
        type="button"
        :class="{ 'is-active': view === slot.id }"
        @click="switchView(slot.id)"
      >
        <i :data-lucide="slot.icon" aria-hidden="true"></i><span>{{ slot.shortLabel }}</span>
      </button>
      <button
        type="button"
        :class="{ 'is-active': moreSheetOpen || isMoreView }"
        aria-label="更多"
        @click="openMoreSheet"
      >
        <i data-lucide="more-horizontal" aria-hidden="true"></i><span>更多</span
        ><em v-if="unreadTotalCount" class="nav-count">{{ unreadTotalCount > 99 ? '99+' : unreadTotalCount }}</em>
      </button>
    </nav>

    <div v-if="moreSheetOpen" class="more-sheet-backdrop" @click.self="moreSheetOpen = false">
      <section class="more-sheet" role="dialog" aria-modal="true" aria-label="更多导航">
        <template v-for="section in moreSections" :key="section.key">
          <div class="more-sheet-group">{{ section.group?.label }}</div>
          <button
            v-for="item in section.items"
            :key="item.id"
            class="more-sheet-item"
            type="button"
            @click="goFromMoreSheet(item.id)"
          >
            <i :data-lucide="item.icon" aria-hidden="true"></i><span>{{ item.label }}</span
            ><em v-if="item.id === 'settings' && unreadTotalCount" class="nav-count">{{
              unreadTotalCount > 99 ? '99+' : unreadTotalCount
            }}</em>
          </button>
        </template>
      </section>
    </div>
```

`<script setup>` 追加：

```ts
/** 手机底部栏 4 个直达格（其余进「更多」抽屉）。短标签取自 NAV_ITEMS.shortLabel。 */
const MOBILE_BAR_IDS = ['overview', 'screener', 'plans', 'monitor'] as const;
const mobileBarItems = NAV_ITEMS.filter((item) => (MOBILE_BAR_IDS as readonly string[]).includes(item.id));

const moreSheetOpen = ref(false);

/** 抽屉分区：与桌面同一套分组，只保留未出现在底部栏的项。 */
const moreSections = computed(() =>
  NAV_GROUPS.map((group) => ({
    key: group.id,
    group,
    items: NAV_ITEMS.filter((item) => item.group === group.id && !(MOBILE_BAR_IDS as readonly string[]).includes(item.id)),
  })).filter((section) => section.items.length > 0)
);

const isMoreView = computed(() => moreSections.value.some((section) => section.items.some((item) => item.id === view.value)));

/** 抽屉内图标同样需要 createIcons 渲染（lucide 按需注册表）。 */
function openMoreSheet(): void {
  moreSheetOpen.value = true;
  nextTick(renderIcons);
}

function goFromMoreSheet(id: string): void {
  moreSheetOpen.value = false;
  switchView(id);
}
```

`watch(view, ...)` 追加关闭语义（放在既有 `watch(notifOpen, ...)` 附近）：`watch(view, () => { moreSheetOpen.value = false; });`。
`ref`/`computed`/`nextTick` 需在 `:302` 的 `vue` import 中齐备。

- [ ] **Step 4: 补抽屉 CSS**

`frontend/src/styles.css` 在 `.bottom-nav`（`:3714`）区块附近追加：

```css
.more-sheet-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: flex;
  align-items: flex-end;
  background: rgba(0, 0, 0, 0.42);
}

.more-sheet {
  width: 100%;
  max-height: 70dvh;
  overflow: auto;
  padding: var(--space-4) var(--space-4) calc(var(--space-6) + env(safe-area-inset-bottom));
  border-top: 1px solid var(--line);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  background: var(--surface);
}

.more-sheet-group {
  margin: var(--space-4) 0 var(--space-2);
  color: var(--muted);
  font-size: var(--fs-xs);
  letter-spacing: 0.04em;
}

.more-sheet-group:first-child {
  margin-top: 0;
}

.more-sheet-item {
  display: flex;
  align-items: center;
  gap: var(--space-3);
  width: 100%;
  min-height: 44px;
  padding: 0 var(--space-3);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--ink);
  font-size: var(--fs-sm);
  text-align: left;
  cursor: pointer;
}

.more-sheet-item:hover {
  background: var(--surface-soft);
}

.more-sheet-item .nav-count {
  margin-left: auto;
}
```

（底部栏只有 ≤680px 显示；`.bottom-nav` 与 `.more-sheet-*` 的显隐规则保持现有 `@media (max-width: 680px)` 结构不变。）

- [ ] **Step 5: 运行测试确认通过**

Run: `npx vitest run tests/frontend/AppShell.test.ts`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add frontend/src/App.vue frontend/src/styles.css tests/frontend/AppShell.test.ts
git commit -m "feat: 手机底部栏改为 4 格直连加更多抽屉，徽标接管未读"
```

---

### Task 5: `view` 白名单归一 + 拆除 `exec` 伪视图

**Files:**
- Modify: `frontend/src/stores/useQuotesStore.ts:17`、`:210-218`、`:241`、`:260-263`
- Modify: `frontend/src/App.vue:244-266`（`exec` 分支与两个 `|| execShows*` 条件）、`:326-339`（解构）
- Modify: `frontend/src/styles.css`（`.mobile-exec-tabs` / `.mobile-exec-tab*` 规则）
- Test: `tests/frontend/useQuotesStore.test.ts`

**Interfaces:**
- Consumes: Task 1 `NAV_ITEMS`、Task 4 底部栏（此时 `exec` 已无 UI 入口）
- Produces: `view` 只可能取 `NAV_ITEMS.id` 或 `'stock-detail'`；`mobileExecTab`/`execShowsPlans`/`execShowsAlerts` 从 store 消失

> **顺序约束（勿在本任务删 `todayLabel`）**：`todayLabel` 的唯一渲染点是 `ViewOverview.vue:11`，它要到 Task 7 才随总览页头一起删除。若在本任务删掉 store 导出，`vue-tsc` 会在 Task 5 的 Step 各门禁里失败。故 `todayLabel` 的删除归属 Task 7。

- [ ] **Step 1: 写失败测试**

在 `tests/frontend/useQuotesStore.test.ts` 追加：

```ts
describe('view 白名单归一（spec §10）', () => {
  it('localStorage 中的已移除视图 exec 归一到 overview', () => {
    localStorage.setItem('atlas-stock-desk-v2', JSON.stringify({ view: 'exec' }));
    setActivePinia(createPinia());
    const quotes = useQuotesStore();
    expect(quotes.view).toBe('overview');
  });

  it('未知视图与 switchView("exec") 同样归一到 overview', () => {
    setActivePinia(createPinia());
    const quotes = useQuotesStore();
    quotes.switchView('exec');
    expect(quotes.view).toBe('overview');
    quotes.switchView('nowhere');
    expect(quotes.view).toBe('overview');
    quotes.switchView('portfolio');
    expect(quotes.view).toBe('portfolio');
  });

  it('exec 三件套已从 store 移除', () => {
    setActivePinia(createPinia());
    const quotes = useQuotesStore() as unknown as Record<string, unknown>;
    for (const key of ['mobileExecTab', 'execShowsPlans', 'execShowsAlerts']) {
      expect(key in quotes).toBe(false);
    }
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/useQuotesStore.test.ts`
Expected: FAIL —— `view` 仍为 `'exec'`；`execShowsPlans` 等仍存在。

- [ ] **Step 3: 实现归一并拆除**

`frontend/src/stores/useQuotesStore.ts`：

① 在 `import { DEFAULT_WATCHLIST, VIEW_META } ...` 中补 `NAV_ITEMS`；在 `:17` 之前新增：

```ts
/** 合法视图集合：主导航项 + 上下文详情页。localStorage 中的历史值必须过此白名单。 */
const VIEW_IDS: readonly string[] = [...NAV_ITEMS.map((item) => item.id), 'stock-detail'];
function normalizeView(name: unknown): string {
  return typeof name === 'string' && VIEW_IDS.includes(name) ? name : 'overview';
}
```

② `:17` 改为 `const view = ref(normalizeView(saved.view));`

③ 删除 `:210-212` 的 `mobileExecTab`/`execShowsPlans`/`execShowsAlerts` 三行（**`todayLabel` 不在此列，见上文顺序约束**），以及返回对象中的三件套（`:260-262`）。

④ `switchView` 改为：

```ts
  function switchView(name: string) {
    view.value = normalizeView(name);
    workspace.persist();
    nextTick(workspace.renderIcons);
  }
```

`frontend/src/App.vue`：删除 `:244-263` 的 `mobile-exec-tabs` 区块；`:265-266` 的两个条件改为 `v-else-if="view === 'plans'"` / `v-else-if="view === 'monitor'"`；解构 `:336-338` 删除三件套。

`frontend/src/styles.css`：
- 删除 `.mobile-exec-tabs`（`:3718-3720` 基础声明）、`.mobile-exec-tabs`（`:3777` 起 ≤680px 声明）、`.mobile-exec-tab`（`:3783`）、`.mobile-exec-tab.is-active`（`:3795`）
- 删除 `@media (max-width: 680px)`（`:3063` 块）内三处失效规则：`.market-switcher { display: none }`（`:3096-3098`）、`.primary-nav { display: flex; ... }`+`.nav-item {...}`+`.nav-item span { display: none }`（`:3100-3118`）、`.nav-item kbd, .sidebar-section-label, .sidebar-data-note, .sidebar-spacer, .sidebar-note, .user-profile { display: none }`（`:3120-3127`）。它们被同断点的后续规则（`:3722` 的 `.primary-nav { display: none }`）与自己已被删除的元素一并失效（spec §10）。**保留**同块内的 `.sidebar`（横条：品牌 + 主题开关）、`.brand`、`.brand-copy { display: none }`、`.main-area`、`.topbar`
- 修剪 `@media (max-width: 1060px)`（`:2948` 块）中**只服务于已删元素**的选择器：从 `display: none` 列表删 `.market-switcher-copy > div,`、`.market-state,`、`.sidebar-data-note,`、`.sidebar-note,`、`.user-copy`（保留 `.brand-copy`/`.nav-item span`/`.nav-item kbd`/`.sidebar-section-label`——其中 **`.sidebar-section-label` 必须留**：组标题只在 >1060px 的宽侧栏显示，681-1060px 的图标条里要隐藏），并删除 `.market-switcher { justify-content: center; ... }`（`:2976-2979`）。**保留**该块的 `.nav-item` / `.nav-item svg` / `.nav-count`（681-1060px 的图标条仍在用）
- ≤680px 侧栏退化为「品牌 + 主题开关 + 版本号」后在 Task 9 Step 2 的人工断点核对中确认（`.sidebar` 是 `display:flex; flex-direction:row`，版本号与主题开关同排）

- [ ] **Step 4: 运行测试确认通过**

Run: `npx vitest run tests/frontend/useQuotesStore.test.ts tests/frontend/AppShell.test.ts`
Expected: PASS

- [ ] **Step 5: 机械断言（本任务口径）**

Run:
```powershell
Get-ChildItem frontend\src -Recurse -Include *.vue,*.ts | Select-String -Pattern 'mobileExecTab|execShowsPlans|execShowsAlerts' | Measure-Object
Get-ChildItem frontend\src -Recurse -Include *.vue | Select-String -Pattern "view === 'exec'|view==='exec'" | Measure-Object
Select-String -Path frontend\src\styles.css -Pattern 'mobile-exec' | Measure-Object
```
Expected: 三处计数均为 0（`ViewPortfolio.vue` 的 `d.executed` 不匹配 `mobileExecTab` 这类驼峰模式；`exec` 单词本身不要裸查，会误伤 `executed`）。

- [ ] **Step 6: 门禁并提交**

```bash
npm run verify
git add frontend/src/App.vue frontend/src/stores/useQuotesStore.ts frontend/src/styles.css tests/frontend/useQuotesStore.test.ts
git commit -m "refactor: 拆除手机端 exec 伪视图并给 view 加白名单归一"
```

---

### Task 6: 总览首屏状态带（O1）

**Files:**
- Modify: `frontend/src/views/ViewOverview.vue:21-49`（KPI 卡 → 状态带）、`:102-128`（删除验证策略卡）、`:130-177`（执行跟踪去重复行）、script 解构
- Modify: `frontend/src/styles.css`（`.desk-kpis`/`.desk-kpi` → 状态带样式）
- Test: `tests/frontend/ViewOverview.test.ts`（新建）

**Interfaces:**
- Consumes: Task 2 的状态控件（数据日期已由顶栏承担，故本视图可删页头日期）；既有字段 `selectedIndex`（quotes）、`screenRows`（screener）、`strategyStats.running`（strategy）、`unreadAlerts` + `switchView`（workspace/quotes）
- Produces: DOM 契约——`.desk-status-strip` 容器；`.desk-status-item` 四个（文本含 `指数`/`候选`/`策略`/`提醒`）；已无 `.desk-kpi`、无「验证策略」面板

> **状态带只放数字，不放注解**：KPI③ 的「待重新回测/样本外超额」与 KPI④ 的「活跃计划/止损触及」正是本任务要删掉的重复行（§7），若把它们搬进状态带就等于没删。`filteredRows`/`presetName` 的归属是「发现机会」面板（`:58`、`:80`、`:94`，本任务保持原样）。

- [ ] **Step 1: 写失败测试**

新建 `tests/frontend/ViewOverview.test.ts`（共享样板 + 视图直挂）：

```ts
import ViewOverview from '@/views/ViewOverview.vue';
import { useScreenerStore } from '@/stores/useScreenerStore';
import { useGridStore } from '@/stores/useGridStore';
// 样板已提供：useQuotesStore/useWorkspaceStore/useScreenerStore? 见下（以样板为准，去重后只保留本文件真正用到的）

describe('总览状态带（spec §7）', () => {
  it('四个数字合成一行状态带，且三段跳转到对应视图', async () => {
    const quotes = useQuotesStore();
    const screener = useScreenerStore();
    const grid = useGridStore();
    const workspace = useWorkspaceStore();
    quotes.dataState = 'live';
    quotes.market.indices = [{ code: 'sh000001', name: '上证指数', price: 3200, change: -0.42, market: '沪市' }];
    screener.screenRows = [{ code: '600519', name: '贵州茅台', change: 1.2 } as any];
    // strategyStats 是 computed（useStrategyStore.ts:51：统计 gridStrategies 中 status === '启用' 的条数）→ 只能造底层数据
    grid.gridStrategies = [
      { id: 'g1', status: '启用' },
      { id: 'g2', status: '启用' },
      { id: 'g3', status: '已停用' },
    ] as any[];
    // unreadAlerts 来自 workspace（workspace.unreadAlerts = 未读且非 system 的条数）
    workspace.alerts = [
      { id: 'a1', kind: 'alert', title: 'x', message: 'y', read: false, createdAtMs: 1 },
    ] as Alert[];
    const wrapper = mount(ViewOverview);
    const items = wrapper.findAll('.desk-status-strip .desk-status-item');
    expect(items.map((node) => node.text().replace(/\s+/g, ''))).toEqual(['指数-0.42%', '候选1', '策略2', '提醒1']);
    await items[1].trigger('click');
    expect(quotes.view).toBe('screener');
    await items[2].trigger('click');
    expect(quotes.view).toBe('grid');
    await items[3].trigger('click');
    expect(quotes.view).toBe('settings');
    wrapper.unmount();
  });

  it('已删除重复的 KPI 卡与「验证策略」面板', () => {
    const wrapper = mount(ViewOverview);
    expect(wrapper.find('.desk-kpi').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('验证策略');
    expect(wrapper.text()).not.toContain('待重新回测');
    wrapper.unmount();
  });

  it('执行跟踪不再渲染与状态带重复的指标行', () => {
    const wrapper = mount(ViewOverview);
    expect(wrapper.findAll('.activity-item').length).toBeLessThanOrEqual(2);
    expect(wrapper.text()).not.toContain('触及止损');
    wrapper.unmount();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/ViewOverview.test.ts`
Expected: FAIL —— `.desk-status-strip` 不存在；`.desk-kpi` 存在；文本含「验证策略」。

- [ ] **Step 3: 实现状态带**

`frontend/src/views/ViewOverview.vue` 用状态带替换 `:21-49` 的 `desk-kpis` 区块：

```vue
    <div class="desk-status-strip surface">
      <span class="desk-status-item is-static">
        <span class="desk-status-label">指数</span>
        <strong :class="trendClass(selectedIndex?.change)">{{ selectedIndex ? formatPct(selectedIndex.change) : '--' }}</strong>
      </span>
      <button class="desk-status-item" type="button" @click="switchView('screener')">
        <span class="desk-status-label">候选</span><strong>{{ screenRows.length }}</strong>
      </button>
      <button class="desk-status-item" type="button" @click="switchView('grid')">
        <span class="desk-status-label">策略</span><strong>{{ strategyStats.running }}</strong>
      </button>
      <button class="desk-status-item" type="button" @click="switchView('settings')">
        <span class="desk-status-label">提醒</span><strong>{{ unreadAlerts }}</strong>
      </button>
    </div>
```

（指数段用 `<span>` 而非禁用按钮：它就是本页「盘面温度」的内容，不做跳转；其余三段分别跳选股器 / 策略 / 个人中心。`screenRows` 的 `--` 兜底无需：空数组渲染 `0`，与 KPI② 现状一致。）

- [ ] **Step 4: 删除重复面板与重复行**

`frontend/src/views/ViewOverview.vue`：
- 删除「验证策略」整张 `<section class="desk-panel surface">`（`:102-128`，含其 kicker/h3/`.desk-stat-rows` 三行与两个按钮）
- 「执行跟踪」面板（`:130-177`）：删除整个 `.desk-stat-rows` 容器（`:137-147`，三行为 活跃计划/触及止损/未读提醒，与状态带重复）；保留 `activity-list`、空态与「进入盯盘提醒」按钮
- 「发现机会」面板（`:52-100`）与「盘面温度」（`:180-259`）原样保留
- script 清理（这些解构项的**唯一**渲染点都在上面被删的区块里，已逐个 grep 核对）：`marketStatus`（仅 KPI① :28）、`riskStats`（仅 KPI④/执行跟踪 :47/:139/:142）、`gridStrategies` 与 `openGridStrategy`（仅验证策略卡 :123/:124）。因此删除 `import { useGridStore } from '@/stores/useGridStore';`（`:272`）、`const grid = useGridStore();`（`:278`）、`const { gridStrategies } = storeToRefs(grid);`（`:284`）、`const { openGridStrategy } = grid;`（`:288`），并把 `:283` 改为 `const { strategyStats } = storeToRefs(strategy);`
- 收尾一律用 `npx vue-tsc --noEmit` 与 `npx eslint frontend/src/views/ViewOverview.vue` 复核未使用变量

`frontend/src/stores/useQuotesStore.ts`：删除 `marketStatus` computed（`:40-45`）与返回对象中的 `marketStatus,`（`:237`）——它是 `dataState` 的**第三种复述**（`已连接/缓存/断开/连接中`，与 `dataStatusText`、顶栏状态控件同义），两个渲染点（App.vue:29、ViewOverview:28）本批均已删除。理由与回退方式见文末「与 spec 的偏差记录」。

- [ ] **Step 5: 状态带 CSS**

`frontend/src/styles.css`：删除 `.desk-kpis`、`.desk-kpi`、`.desk-kpi-label`、`.desk-kpi strong`、`.desk-kpi-note`（`:3603-3632`；先 `Get-ChildItem frontend\src -Recurse -Include *.vue | Select-String -Pattern 'desk-kpi'` 确认 0 命中），新增：

```css
.desk-status-strip {
  display: flex;
  flex-wrap: wrap;
  align-items: stretch;
  gap: var(--space-2);
  padding: var(--space-2);
}

.desk-status-item {
  display: flex;
  flex: 1 1 160px;
  align-items: baseline;
  gap: var(--space-2);
  min-width: 0;
  padding: var(--space-2) var(--space-3);
  border: none;
  border-radius: var(--radius-md);
  background: transparent;
  color: var(--ink);
  font-size: var(--fs-sm);
  text-align: left;
  cursor: pointer;
}

.desk-status-item:hover:not(.is-static) {
  background: var(--surface-soft);
}

.desk-status-item.is-static {
  cursor: default;
}

.desk-status-label {
  color: var(--muted);
  font-size: var(--fs-xs);
}
```

（不再需要 `.desk-status-note`：注解一律不进状态带。）

- [ ] **Step 6: 运行测试确认通过**

Run: `npx vitest run tests/frontend/ViewOverview.test.ts`
Expected: PASS

- [ ] **Step 7: 门禁并提交**

```bash
npm run verify
git add frontend/src/views/ViewOverview.vue frontend/src/stores/useQuotesStore.ts frontend/src/styles.css tests/frontend/ViewOverview.test.ts
git commit -m "feat: 总览首屏压成一行状态带，删除与面板逐字重复的指标卡"
```

---

### Task 7: 标题唯一化（H1）

**Files:**
- Modify: 8 个视图（`frontend/src/views/ViewOverview.vue` `ViewScreener.vue` `ViewGrid.vue` `ViewPlans.vue` `ViewMonitor.vue` `ViewPortfolio.vue` `ViewSettings.vue` `ViewStockDetail.vue`）
- Modify: `frontend/src/App.vue:97`（删除 eyebrow）
- Modify: `frontend/src/stores/useQuotesStore.ts:54` 与 `:241`（删除 `todayLabel` computed 与导出——唯一渲染点 `ViewOverview.vue:11` 在本任务消失，故必须与模板同任务删除）
- Modify: `frontend/src/styles.css`（删 `.section-kicker`+`.topbar-eyebrow` 共用规则、`.data-updated` 选择器；层级与 `.view-heading` 布局调整）
- Test: `tests/frontend/AppShell.test.ts`（追加断言）、`tests/frontend/useQuotesStore.test.ts`（追加 `todayLabel` 已移除断言）

**Interfaces:**
- Consumes: Task 2（顶栏承担数据日期）、Task 3（侧栏已去 kicker 无关）
- Produces: 视图内不再有这种 h2/说明；`.view-heading-actions` 一律保留

- [ ] **Step 1: 写失败测试**

在 `tests/frontend/AppShell.test.ts` 追加：

```ts
describe('标题唯一化（spec §8）', () => {
  it('顶栏无英文 eyebrow，视图区无 section-kicker 残留类', () => {
    const wrapper = mount(App, { global: viewStubs });
    expect(wrapper.find('.topbar-eyebrow').exists()).toBe(false);
    expect(wrapper.find('.section-kicker').exists()).toBe(false);
    wrapper.unmount();
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/AppShell.test.ts tests/frontend/useQuotesStore.test.ts`
Expected: FAIL —— `.topbar-eyebrow` 仍存在；`todayLabel` 仍在 store 上。

在 `tests/frontend/useQuotesStore.test.ts` 追加（沿用 Task 5 的 key-in-store 模式）：

```ts
describe('todayLabel 已随总览页头移除（spec §10）', () => {
  it('store 不再导出 todayLabel', () => {
    setActivePinia(createPinia());
    const quotes = useQuotesStore() as unknown as Record<string, unknown>;
    expect('todayLabel' in quotes).toBe(false);
  });
});
```

- [ ] **Step 3: 逐视图删除装饰标题与 kicker**

删除规则：删 `<span class="section-kicker">…</span>` 行、装饰性 `<h2>…</h2>` 行、`<p class="heading-note">…</p>` 行；**同级 `.view-heading-actions` 原样保留**（唯一例外是总览：它的 actions 只剩「数据日期 + 今天日期」，两项都删，空容器一并删除，日期事实已由 Task 2 的顶栏控件承担）。逐个视图的执行清单（行号为 2026-10-15 核对位置，以文本定位为准）：

- `ViewOverview.vue`：`:5` `TRADING DECK`、`:6` h2 `今日交易台`、`:7` note；`:9-12` 的 `.view-heading-actions` 整块删除（内含 `data-updated`（`fetchedLabel`）与 `strategy-label`（`todayLabel`）两个 span，两者都随日期迁移消失）；内部 kicker `OPPORTUNITIES`（`:55`）、`MARKET PULSE`（`:183`）删除（`STRATEGY VALIDATION`/`EXECUTION RISK` 两处已由 Task 6 删除）。**注意**：删掉 `:10` 后 `fetchedLabel` 在总览不再被引用 → 从 `:280` 的 `storeToRefs(quotes)` 解构中一并删除（`fetchedLabel` 的 store 导出保留，ViewMonitor:37 仍在用）
- `ViewScreener.vue`：`:5` `SCREENING LAB`、`:6` h2、`:7` note；`:46` `PIPELINE`、`:151` `RESULTS`、`:257` `STRATEGY`、`:339` `RESULTS`、`:433` `FULL MARKET`
- `ViewGrid.vue`：`:5` `STRATEGY LAB`、`:86` `CONFIGURATION`、`:198` `BACKTEST RESULT`、`:333` `CONFIGURATION`、`:421` `BACKTEST RESULT`、`:516` `COMPARISON`、`:582` `COMPARE RESULT`、`:678` `SAVED COMPARISON`、`:797` `SAVED STRATEGIES`、`:827` `OPTIMIZATION`、`:869` `SAVED STRATEGIES`。**该视图的 h2（`:6`，动态策略类型）与 `heading-note`（`:7-15`、`:293`、`:504`、`:592`、`:654`）保留**，仅把 h2 降级为内容区标题（`<h2>` → `<h2 class="surface-title">`，并在 CSS 中给 `.surface-title` 与既有 h2 相同的视觉档位）
- `ViewPlans.vue`：`:5` `TRADE PLAN`、`:6` h2、`:7` note；`:21` `NEW PLAN`、`:122` `ACTIVE PLANS`
- `ViewMonitor.vue`：`:5` `MONITORING CENTER`、`:6` h2、`:7` note；`:44` `LIVE WATCH`
- `ViewPortfolio.vue`：`:5` `PORTFOLIO RISK`、`:6` h2、`:7` note；`:129` `NAV CURVE`、`:158` `EXPOSURE`、`:187` `CONCENTRATION`
- `ViewSettings.vue`：`:5` `PERSONAL HUB`、`:6` h2、`:7` note；`:35` `NOTIFICATIONS`
- `ViewStockDetail.vue`：`:5` `STOCK DETAIL`。**h2（`:6`，股票名）与 `:7-13` 副信息保留**，降级为内容区标题

- [ ] **Step 4: 层级与样式调整**

- 各视图内容区卡片标题由 `<h3>` 升为 `<h2>`（`.surface-heading` 内），保证 `h1 → h2` 不跳级；
- `App.vue:97` 删除 `<span class="topbar-eyebrow">A-SHARE / REAL QUOTES</span>`（此时 `.topbar-title-row` 只剩 `h1`，样式无需改：它是 `display:flex`）；
- `frontend/src/stores/useQuotesStore.ts`：删除 `:54` 的 `todayLabel` computed 与 `:241` 的 `todayLabel,` 导出（`ViewOverview.vue:11` 的渲染点已在 Step 3 删除）；
- `styles.css`：
  - 删除 `:527-533` 整条规则（选择器只有 `.topbar-eyebrow,\n.section-kicker`，两者都不再被引用）
  - `.data-updated` 位于**共用**规则 `:853-862`（`.data-updated, .scan-time, .plan-count { ... }`）→ **只删 `.data-updated,` 这一行选择器**，保留规则体与 `.scan-time`/`.plan-count`（ViewScreener/ViewPlans 仍在用）
  - 新增：

```css
.view-heading {
  justify-content: flex-end;
}

.surface-title {
  margin: 0;
  color: var(--ink);
  font-size: var(--fs-md);
  font-weight: 600;
}
```

- `ViewGrid.vue` 的动态标题（`:6`）与 `ViewStockDetail.vue` 的股票名标题（`:6`）改为 `<h2 class="surface-title">`（不删，降级为内容区标题）；`ViewGrid` 的 `heading-note`（`:7-15`、`:293`、`:504`、`:592`、`:654`）与 `ViewStockDetail` 的 `:7-13` 副信息保留不动

- [ ] **Step 5: 运行测试确认通过**

Run: `npx vitest run`
Expected: PASS（含 `ViewGrid.test.ts`/`ViewPlans.test.ts` 等既有视图测试——它们的断言不依赖 kicker/标题文本，已核对）

- [ ] **Step 6: 机械断言**

Run:
```powershell
Get-ChildItem frontend\src -Recurse -Include *.vue | Select-String -Pattern 'section-kicker|topbar-eyebrow' | Measure-Object
Get-ChildItem frontend\src -Recurse -Include *.vue | Select-String -Pattern '>[A-Z][A-Z /]{3,}<' | Measure-Object
Get-ChildItem frontend\src -Recurse -Include *.vue,*.ts | Select-String -Pattern 'todayLabel' | Measure-Object
```
Expected: 三者计数均为 0。

- [ ] **Step 7: 门禁并提交**

```bash
npm run verify
git add frontend/src/App.vue frontend/src/views frontend/src/stores/useQuotesStore.ts frontend/src/styles.css tests/frontend/AppShell.test.ts tests/frontend/useQuotesStore.test.ts
git commit -m "refactor: 视图标题唯一化，删除装饰标题与 34 处英文标签"
```

---

### Task 8: 入口可达性（R1）

**Files:**
- Modify: `frontend/src/views/ViewPlans.vue`（计划列表 `:144` + 复盘表 `:300` 下钻）
- Modify: `frontend/src/views/ViewSettings.vue`（收件箱行 `:81-86` 下钻）
- Modify: `frontend/src/App.vue`（通知面板 `:186-197` 新增「查看详情」兄弟按钮）
- Modify: `frontend/src/views/ViewPortfolio.vue`（交易对表 `:255-256` 下钻，需引入 quotes store）
- Modify: `frontend/src/views/ViewStockDetail.vue`（返回按钮 `:19-21` 带来源名）
- Modify: `frontend/src/styles.css`（`.code-link`）
- Test: `tests/frontend/ViewPlans.test.ts`、`tests/frontend/ViewPortfolio.test.ts`、`tests/frontend/ViewStockDetail.test.ts`、`tests/frontend/ViewSettings.test.ts`（增补）

**Interfaces:**
- Consumes: `selectStock(code: string, fromView?: string)`、`detailReturnView`、`VIEW_META`
- Produces: 5 处新入口；`ViewStockDetail` 返回按钮文本为 `返回{来源名}`

- [ ] **Step 1: 写失败测试**

`tests/frontend/ViewPlans.test.ts` 追加（沿用该文件既有样板：`useWorkspaceStore` + `flushPromises`；**`activePlans` 是 workspace 的 computed**，所以测试要写 `workspace.plans` 而不是 `activePlans`）：

```ts
it('计划列表的代码可下钻个股详情并记录来源', async () => {
  const quotes = useQuotesStore(); // 该文件已 import 各 store，按需补 import
  const workspace = useWorkspaceStore();
  workspace.plans = [
    {
      id: 'p1',
      code: '600519',
      direction: 'buy',
      entry: 1680,
      stop: 1620,
      target: 1800,
      status: '执行中',
    } as Plan,
  ];
  const wrapper = mount(ViewPlans);
  await wrapper.find('[data-testid="plan-code-link"]').trigger('click');
  await flushPromises(); // selectStock 是 async（内部 ensureQuote + fetchHistory）
  expect(quotes.view).toBe('stock-detail');
  expect(quotes.detailReturnView).toBe('plans');
  wrapper.unmount();
});
```

`tests/frontend/ViewStockDetail.test.ts` 追加（沿用其 `mountDetail()` 助手）：

```ts
it('返回按钮显示来源视图名', async () => {
  const { quotes, wrapper } = await mountDetail();
  quotes.detailReturnView = 'portfolio';
  await nextTick(); // flushPromises/mount 后已渲染；改 ref 需等一次更新
  expect(wrapper.find('[data-testid="back-from-detail"]').text()).toBe('返回组合风险');
  wrapper.unmount();
});
```

`tests/frontend/ViewPortfolio.test.ts` 追加（沿用 `mountWith(payload)`；payload 的 `pairs` 若已有数据就直接用第一条，否则在 `makePayload` 里补一条 `{ buyPlanId: 'b1', buy: { code: '600519', entry: 10, stop: 9, target: 12, status: '执行中' } }`）：

```ts
it('交易对表的代码可下钻组合风险来源详情', async () => {
  const store = usePortfolioStore();
  const { wrapper } = await mountWith(makePayload(/* 含 pairs 的覆盖 */));
  await wrapper.find('[data-testid="pair-code-link"]').trigger('click');
  await flushPromises();
  const quotes = useQuotesStore(); // 需补 import
  expect(quotes.view).toBe('stock-detail');
  expect(quotes.detailReturnView).toBe('portfolio');
  wrapper.unmount();
});
```

`tests/frontend/ViewSettings.test.ts` 追加（收件箱行来自 alerts store 的 `filteredAlerts`，`workspace.alerts` 是数据源）：

```ts
it('通知收件箱的代码可下钻，且不改动标记已读行为', async () => {
  const workspace = useWorkspaceStore();
  workspace.alerts = [
    {
      id: 'a1',
      kind: 'alert',
      title: '触及止损',
      message: '贵州茅台 触及止损',
      code: '600519',
      read: false,
      time: '刚刚',
      createdAtMs: 1,
    } as Alert,
  ];
  const quotes = useQuotesStore();
  const wrapper = mount(ViewSettings);
  await wrapper.find('[data-testid="alert-detail-link"]').trigger('click');
  await flushPromises();
  expect(quotes.view).toBe('stock-detail');
  expect(quotes.detailReturnView).toBe('settings');
  // 既有行为不受影响
  expect(wrapper.text()).toContain('标记已读');
  wrapper.unmount();
});
```

> 若既有测试文件的 mount 样板与本计划示例不同，**以既有文件的样板为准**，只追加用例（并补上缺的 import 与 `nextTick`/`flushPromises`）。

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/ViewPlans.test.ts tests/frontend/ViewStockDetail.test.ts tests/frontend/ViewPortfolio.test.ts tests/frontend/ViewSettings.test.ts`
Expected: FAIL —— 三个 `data-testid` 均不存在。

- [ ] **Step 3: 实现 5 处入口**

统一模式（按钮而非 block 元素，键盘可聚焦）：

- `ViewPlans.vue`：计划列表的代码（`:144` 的 `<span>{{ plan.code }} · {{ direction }}</span>`）改为把代码包成按钮（头像圆标 `:139-141` 不动）：
  ```vue
                  <strong>{{ quoteFor(plan.code)?.name || plan.code }}</strong
                  ><span
                    ><button class="code-link" type="button" data-testid="plan-code-link" @click="selectStock(plan.code, 'plans')">
                      {{ plan.code }}</button
                    > · {{ plan.direction === 'buy' ? '买入计划' : '卖出计划' }}</span
                  >
  ```
  归档/复盘表 `:300` 的 `<td>{{ item.code }}</td>` 改为
  ```vue
                <td>
                  <button class="code-link" type="button" data-testid="plan-code-link" @click="selectStock(item.code, 'plans')">
                    {{ item.code }}
                  </button>
                </td>
  ```
  script：把 `:351` 的 `const { quoteFor } = quotes;` 改为 `const { quoteFor, selectStock } = quotes;`（`quotes` 实例已存在，无需新 import）。
- `ViewSettings.vue`（收件箱行 `:81-86`，即 `.alert-meta` 内、`标记已读` 之前）：新增
  ```vue
                  ><button v-if="alert.code" class="text-button" type="button" data-testid="alert-detail-link" @click="selectStock(alert.code, 'settings')">
                    查看详情
                  </button>
  ```
  script 新增 `import { useQuotesStore } from '@/stores/useQuotesStore';`、`const { selectStock } = useQuotesStore();`（该视图此前未引入 quotes store）。
- `App.vue`（通知面板 `:186-197`）：在既有 `alert-code-chip` 按钮**之后**新增兄弟按钮（不得改动既有按钮的 `data-testid="alert-code-chip"` 与 `openScanDraft(alert)` 行为——`useAlertsStore.test.ts` 依赖它们）：
  ```vue
                      <button
                        v-if="alert.code"
                        class="text-button"
                        type="button"
                        data-testid="alert-detail-chip"
                        @click="openAlertDetail(alert.code)"
                      >
                        查看详情
                      </button>
  ```
  script 新增（`quotes` 实例、`notifOpen`、`switchView`、`view` 均为既有解构/实例）：
  ```ts
  /** 通知面板下钻：保持「返回」回到用户当前所在视图（已在详情页时沿用它原本的来源）。 */
  function openAlertDetail(code: string): void {
    const from = view.value === 'stock-detail' ? (quotes.detailReturnView as string) : view.value;
    notifOpen.value = false;
    quotes.selectStock(code, from);
  }
  ```
  **注意**：不要先 `switchView('stock-detail')` 再传 `view.value`——`selectStock` 自己会切视图（`useQuotesStore.ts:147-155`），先切会让 `fromView` 变成 `'stock-detail'`。
- `ViewPortfolio.vue`（交易对表 `:255-256`）：首列改为「有代码才是链接」，不给缺失值造可点元素：
  ```vue
              <tr v-for="(pair, i) in pairs" :key="String(pair.buyPlanId ?? i)">
                <td>
                  <button
                    v-if="pair.buy?.code"
                    class="code-link"
                    type="button"
                    data-testid="pair-code-link"
                    @click="selectStock(pair.buy.code, 'portfolio')"
                  >
                    {{ pair.buy.code }}
                  </button>
                  <span v-else>--</span>
                </td>
  ```
  script 新增 `import { useQuotesStore } from '@/stores/useQuotesStore';` 与 `const { selectStock } = useQuotesStore();`（**不得**改动该视图 `:17-19` 的降级黄条/错误红条逻辑）。
- `ViewStockDetail.vue`（`view-heading-actions` `:19-21`）：返回按钮加 `data-testid` 并带来源名
  ```vue
        <button class="button button-secondary" type="button" data-testid="back-from-detail" @click="backFromDetail">
          <i data-lucide="arrow-left" aria-hidden="true"></i>返回{{ returnViewLabel }}
        </button>
  ```
  script：`storeToRefs(quotes)`（`:123`）补 `detailReturnView`；新增
  ```ts
  /** 「返回」带来源名（VIEW_META[from][0]）；来源缺失时退回泛化文案。 */
  const returnViewLabel = computed(() =>
    detailReturnView.value === 'stock-detail' ? '上一页' : (VIEW_META as Record<string, string[]>)[detailReturnView.value][0]
  );
  ```
  并从 `@/modules/constants` 引入 `VIEW_META`（`computed` 已在 `:106` 引入）。

- [ ] **Step 4: 补 `.code-link` 样式**

`frontend/src/styles.css` 新增：

```css
.code-link {
  padding: 0;
  border: none;
  background: transparent;
  color: inherit;
  font: inherit;
  text-decoration: underline;
  text-decoration-color: var(--line-strong);
  text-underline-offset: 2px;
  cursor: pointer;
}

.code-link:hover {
  color: var(--coral);
  text-decoration-color: currentColor;
}
```

- [ ] **Step 5: 运行测试确认通过**

Run: `npx vitest run tests/frontend/ViewPlans.test.ts tests/frontend/ViewSettings.test.ts tests/frontend/ViewPortfolio.test.ts tests/frontend/ViewStockDetail.test.ts tests/frontend/useAlertsStore.test.ts`
Expected: PASS（最后一个确认通知面板既有契约未破）

- [ ] **Step 6: 门禁并提交**

```bash
npm run verify
git add frontend/src/App.vue frontend/src/views frontend/src/styles.css tests/frontend
git commit -m "feat: 计划/提醒/交易对补下钻入口，详情返回带来源名"
```

---

### Task 9: 机械验收与文档收口

**Files:**
- Modify: `AGENTS.md`、`CHANGELOG.md`、`ROADMAP.md`

**Interfaces:**
- Consumes: 前 8 个任务的产物
- Produces: 可复核的验收记录

- [ ] **Step 1: 跑全量机械断言**

Run:
```powershell
"kicker/eyebrow 残留："; (Get-ChildItem frontend\src -Recurse -Include *.vue | Select-String -Pattern 'section-kicker|topbar-eyebrow' | Measure-Object).Count
"exec 三件套残留："; (Get-ChildItem frontend\src -Recurse -Include *.vue,*.ts | Select-String -Pattern 'mobileExecTab|execShowsPlans|execShowsAlerts' | Measure-Object).Count
"exec 伪视图分支残留："; (Get-ChildItem frontend\src -Recurse -Include *.vue | Select-String -Pattern "view === 'exec'" | Measure-Object).Count
"大写英文标签残留："; (Get-ChildItem frontend\src -Recurse -Include *.vue | Select-String -Pattern '>[A-Z][A-Z /]{3,}<' | Measure-Object).Count
"假 UI 类残留（模板）："; (Get-ChildItem frontend\src -Recurse -Include *.vue | Select-String -Pattern 'user-profile|market-switcher|sidebar-data-note|sidebar-note|demo-badge' | Measure-Object).Count
"假 UI 类残留（样式）："; (Select-String -Path frontend\src\styles.css -Pattern 'user-profile|market-switcher|market-state|sidebar-data-note|sidebar-note|demo-badge|mobile-exec|desk-kpi' | Measure-Object).Count
"marketStatus/todayLabel 残留："; (Get-ChildItem frontend\src -Recurse -Include *.vue,*.ts | Select-String -Pattern 'marketStatus|todayLabel' | Measure-Object).Count
```
Expected: 全部为 0。

- [ ] **Step 2: 五个断点人工核对**

Run: `npm run dev`，在浏览器逐宽度核对 1260 / 1180 / 1060 / 900 / 680px：
① 侧栏分区标题与 7 个导航项；② 顶栏状态控件的三态（含断网/跨日文案）；③ ≤680px 底部 4 格 + 更多抽屉（分组标题、徽标、点击切视图后关闭）；④ 页脚仅剩免责声明；⑤ 无横向溢出、无文字截断。
把每一档的结论（通过/发现的问题）写进最终报告；发现的问题当场修复并补提交。

- [ ] **Step 3: 更新文档**

- `AGENTS.md`：项目布局段中 `App.vue` / `constants.ts` / `styles.css` 描述更新为「分区导航 + 顶栏唯一状态控件 + 手机更多抽屉 + 无装饰 kicker」；前端视图清单补充「8 视图标题由 `VIEW_META` 单一驱动」。
- `CHANGELOG.md`：在 v0.7.2 段落内追加小节：
  ```
  ### UI 布局 IA（第③a批）
  - 主导航按工作流分区（研究/验证/执行/风控/系统），总览置顶；桌面侧栏显示分区标题。
  - 手机底部栏改为 4 格直达 + 「更多」抽屉，未读徽标挂「更多」。
  - 行情状态（状态 + 最后更新时间 + 刷新）合并为顶栏单一控件，跨日显示日期；页脚去掉重复的行情源。
  - 总览首屏 4 张 KPI 卡压成一行状态带，删除与面板逐字重复的指标。
  - 删除 8 个视图的装饰性标题与 34 处英文标签；视图标题由顶栏单一提供。
  - 5 处「有代码点不动」的入口补上下钻（提醒面板/通知收件箱/交易计划/已归档计划/组合风险交易对），详情「返回」显示来源视图。
  - 如实披露：手机格用短标签（选股/计划/盯盘）而抽屉用全名；「更多」抽屉暂无 Esc 关闭（留给第③b批）。
  - 代码清理（无 UI 影响）：删除 `marketStatus`（`dataState` 的第三次复述，两个渲染点本批均已移除）与 `todayLabel`；`view` 增加白名单归一（老存储里的 `exec` 归一到总览）。
  ```
- `ROADMAP.md`：勾选「整体界面优化」中本批覆盖的子项，注明 ③b（交互一致性）待做。

- [ ] **Step 4: 最终门禁**

Run: `npm run verify`
Expected: 全绿（vitest 全通过、`vue-tsc` 干净、pytest 679 项、覆盖率不低于 93%）

- [ ] **Step 5: 提交**

```bash
git add AGENTS.md CHANGELOG.md ROADMAP.md
git commit -m "docs: 收口第③a批文档并记录验收结论"
```

---

## Self-Review

**1. Spec 覆盖检查**

| Spec 节 | 覆盖任务 |
|---|---|
| §4 信息架构（分组/顺序/侧栏构成/删除项） | Task 1（常量）、Task 3（渲染与删除） |
| §5 手机端（5 格/抽屉/徽标/短标签/exec 拆除） | Task 4、Task 5 |
| §6 壳层（状态控件、日期边界、三态、页脚） | Task 2 |
| §7 总览首屏（状态带、删卡、去重复行） | Task 6 |
| §8 标题唯一化（规则、例外、actions 保留、层级） | Task 7 |
| §9 可达性（5 处下钻、来源返回、不进导航） | Task 8 |
| §10 状态与数据流（常量字段、归一、删除项） | Task 1、Task 5（exec/归一）、Task 6（marketStatus，见偏差记录）、Task 7（todayLabel） |
| §11 错误与降级（红线、抽屉行为留 ③b） | Task 2（三态）、Task 4（只做遮罩关闭）、Task 5（归一防白屏） |
| §12 测试计划（既有约束、新增测试、机械断言、门禁） | Task 2/3/4/5/6/7/8 各自的测试步骤 + Task 9 Step 1 |
| §13 文档收口 | Task 9 Step 3 |
| §14 已知限制 | Task 9 Step 3（CHANGELOG 如实披露）+ Task 9 Step 2（断点核对） |

无遗漏；无 spec 要求找不到归属任务。

**2. 占位符扫描**

无 TBD/TODO/「稍后补」。唯一的二选一（版本号注入方式）已定死为「常量 + 测试守卫」实现（Task 1 Step 3）。

**3. 类型/命名一致性**

- `NAV_ITEMS.group` 与 `NAV_GROUPS[i].id` 同名集合；`normalizeView`、`VIEW_IDS` 命名在 Task 5 内一致。
- `marketStatusLabel` / `marketStatusTimeLabel` 在 Task 2 定义，消费点只有 Task 2 的控件（`marketStatusTimeLabel` 内部复用既有 `lastUpdatedLabel`）。
- `moreSections` / `moreSheetOpen` / `isMoreView` / `openMoreSheet` / `goFromMoreSheet` 在 Task 4 内一致；`more-sheet` / `more-sheet-group` / `more-sheet-item` 类名在 Task 4 的模板、CSS、测试三处一致。
- `desk-status-strip` / `desk-status-item`（+`.is-static`）/ `desk-status-label` 在 Task 6 的模板、CSS、测试三处一致（**无** `desk-status-note`，注解一律不进状态带）。
- testid 集合：`market-status-control`（Task 2）、`plan-code-link`、`pair-code-link`、`alert-detail-link`、`alert-detail-chip`、`back-from-detail`（Task 8）——互不冲突，且不覆盖既有 `alert-code-chip`。

**4. 依赖顺序核对**（每个任务结束时都必须 `npm run verify` 全绿）

| 约束 | 原因 | 落点 |
|---|---|---|
| Task 2 早于 Task 3 | 顶栏状态控件必须先提供「最后更新时间」，Task 3/7 才敢删侧栏数据连接块与总览页头日期 | Task 2 → 3 → 7 |
| Task 3 早于 Task 6 | App.vue 里 `marketStatus` 的渲染点（`:29`）在 Task 3 消失，store 里的 computed 才能在 Task 6 删除 | Task 3 → 6 |
| `todayLabel` 只能在 Task 7 删 | 唯一渲染点 `ViewOverview.vue:11` 在 Task 7 才消失 | Task 7 |
| Task 4 早于 Task 5 | 底部栏先接管「计划/盯盘」直达，`exec` 才真正无 UI 入口 | Task 4 → 5 |
| Task 6 早于 Task 7 | 两者都改 `ViewOverview.vue`，先做指标结构、后做页头，避免同文件两次重排 | Task 6 → 7 |

**5. 三项开放问题的裁定**（spec §4、§14-4 留给我拍板，用户「确定」按 spec 默认执行）

1. **单成员分组保留组标题**（研究/验证/风控 各 1 项）：按 spec §4 默认保留（写进 CHANGELOG，便于日后回退成「仅执行组显示标题」）。
2. **版本号来源**：`APP_VERSION` 常量 + `constants.test.ts` 里与 `package.json` 的同步断言（构建期注入会引入 `vite define` + 全局类型声明，成本高于收益）；`package.json` 当前为 `0.7.1`。
3. **不出截图证据**：按 spec §14-4 默认——grep 断言 + 新增测试 + 五个断点人工核对；不新增 playwright 任务。

**6. 与 spec 的偏差记录**（唯一一处，无 UI 影响，可一行回退）

- **偏差**：删除 `stores/useQuotesStore.ts` 的 `marketStatus` computed（spec §10 只列了 `mobileExecTab`/`execShowsPlans`/`execShowsAlerts`/`todayLabel`）。
- **依据**：核对 `:40-45` 后确认它是 `dataState` 的第三次复述（`已连接/缓存/断开/连接中`，与 `dataStatusText`、本批新增的顶栏状态控件同义）。它不是独立事实：代码里根本没有「交易中/已收盘」这类行情时段字段（若确有，本批会保留其唯一渲染点）。它仅有的两个渲染点 `App.vue:29`（Task 3 删）与 `ViewOverview.vue:28`（Task 6 删）都在本批消失，留着就是死代码。
- **回退**：若复审要求保留，只需在 Task 6 跳过该步并保留 store 导出（不动，也不会有任何渲染点）。

