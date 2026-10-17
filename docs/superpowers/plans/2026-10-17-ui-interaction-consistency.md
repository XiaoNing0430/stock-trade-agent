# UI 交互一致性（第③b批）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让浮层有统一的键盘行为（Esc/焦点陷阱/滚动锁/焦点归还）、让「加载中 / 没有数据 / 字段缺失 / 请求失败」四态各有明确画法、让 Toast 可信可控（去重/上限/可关闭/分时长）、让快捷键完整可发现且不误触，并补上 ③a 遗留的 4 项一致性缺口。

**Architecture:** 三处**新增纯逻辑模块**（`modules/overlayA11y.ts` 浮层栈与行为、`modules/toastQueue.ts` Toast 策略、`modules/shortcuts.ts` 键位表与抑制规则）承载可单测的规则；视图与组件只做**接线**（每处 1–3 行）。视觉侧只加一条滚动锁规则、一个 `.loading-state` 共享版式与三个 Toast 辅助类，**不新增视觉令牌**。

**Tech Stack:** Vue 3 + TypeScript 5.9（strict）+ Pinia + vitest 4 + @vue/test-utils（jsdom）；真实浏览器验收用仓库外 Playwright 脚本；后端零改动。

**规格：** `docs/superpowers/specs/2026-10-17-ui-interaction-consistency-design.md`（用户已复审通过）。

## Global Constraints

- **绝不使用模拟值填充缺失数据**：加载中显示「正在…」，加载完成但字段缺失仍是 `--`；降级/错误路径文案与强度本批**一字不改**。
- **免责声明**（页脚「研究工具不构成投资建议」）与 `VIEW_META` 标题体系本批不动。
- 用户可见文案**全中文**；不新增英文装饰标签、不新增视觉令牌。
- **`showToast(message, tone)` 签名与返回值不变**（~75 处调用点与既有 spy 断言 `toHaveBeenCalledWith(msg, 'error')` 必须继续通过）。
- **`NAV_ITEMS` 顺序与数量不变**；`VIEW_SHORTCUTS` 的 7 个键映射即 `NAV_ITEMS` 顺序。
- **后端零改动**（零 API / 零 schema / 零迁移）：`git diff --stat <基线>...HEAD -- backend/ tests/` 必须为空。
- 非目标守卫：不引入 `skeleton`，不引入 `inert`。
- 每步用 `npx vitest run <file>` 跑相关测试；每个任务末尾 `npx vitest run`（全量 309 项 + 本批新增）+ `npx vue-tsc --noEmit` 必须全绿再提交。
- 行号口径：2026-10-17 于 `develop`（`d756d2a`，含 ③a）核对；实现时以符号/文本定位为准。

---

## 文件结构

| 文件 | 责任 | 动作 |
|---|---|---|
| `frontend/src/modules/overlayA11y.ts` | 浮层栈 / Esc / 焦点陷阱 / 滚动锁计数 / 焦点归还 + 纯函数 | 新建（Task 1） |
| `frontend/src/modules/toastQueue.ts` | Toast 策略（去重 / 上限 / 时长 / 暂停 / 关闭）+ 命令式 DOM | 新建（Task 8） |
| `frontend/src/modules/shortcuts.ts` | 键位表 / 抑制规则 / `helpOpen` | 新建（Task 9） |
| `frontend/src/components/ShortcutHelpDialog.vue` | 快捷键帮助浮层 | 新建（Task 10） |
| `frontend/src/modules/format.ts` | `viewDetailLabel(code, name?)` 可访问名构造 | 追加（Task 12） |
| `frontend/src/styles.css` | 滚动锁规则、`.loading-state` 共享版式、Toast 辅助类、≤1060 主题开关文案 | 追加（Task 1/3/8/11） |
| `frontend/src/App.vue` | 2 个浮层接线、通知面板 ARIA、Toast 区域 ARIA、导航 `aria-keyshortcuts`、`?` 入口、抽屉键位 | 修改（Task 2/8/9/10/12） |
| `frontend/src/components/PlanDraftDialog.vue` | 浮层接线 | 修改（Task 2） |
| `frontend/src/components/CustomStrategyDialog.vue` | 浮层接线 | 修改（Task 2） |
| `frontend/src/stores/useWorkspaceStore.ts` | `showToast` 变薄委托 | 修改（Task 8） |
| `frontend/src/app.ts` | 键位监听重构为派发器 | 修改（Task 9） |
| `frontend/src/views/ViewScreener.vue` | 3 处加载态换类 + 精选空态按钮 | 修改（Task 3） |
| `frontend/src/views/ViewOverview.vue` | 1 处加载态换类 | 修改（Task 3） |
| `frontend/src/views/ViewGrid.vue` | 3 处加载分支 + 2 处空态按钮 | 修改（Task 4） |
| `frontend/src/views/ViewPlans.vue` | 复盘加载态 + 空态跳转按钮 + 2 处可访问名 | 修改（Task 5/12） |
| `frontend/src/views/ViewPortfolio.vue` | KPI「计算中」+ 空态跳转按钮 + 可访问名 | 修改（Task 6/12） |
| `frontend/src/views/ViewStockDetail.vue` | 报价/分钟线加载态 | 修改（Task 7） |
| `frontend/src/views/ViewSettings.vue` | 可访问名 | 修改（Task 12） |
| `tests/frontend/overlayA11y.test.ts` | 新建（Task 1） | — |
| `tests/frontend/toastQueue.test.ts` | 新建（Task 8） | — |
| `tests/frontend/shortcuts.test.ts` | 新建（Task 9） | — |
| `tests/frontend/ShortcutHelpDialog.test.ts` | 新建（Task 10） | — |
| `tests/frontend/{AppShell,format,ViewScreener,ViewOverview,ViewGrid,ViewPlans,ViewPortfolio,ViewStockDetail}.test.ts` | 扩展现有 | 修改（多任务） |

---

### Task 1: 浮层行为模块 `overlayA11y` + 滚动锁 CSS

**Files:**
- Create: `frontend/src/modules/overlayA11y.ts`
- Modify: `frontend/src/styles.css`（在 `.view-panel.is-active` 滚动条规则块之后，即 `styles.css:597` 附近追加）
- Test: `tests/frontend/overlayA11y.test.ts`

**Interfaces:**
- Consumes: 无（本批基础模块）
- Produces:
  - `useOverlayA11y(options: { id: string; isOpen: () => boolean; panelRef: Ref<HTMLElement | null>; onClose: () => void; closeOnEsc?: boolean }): void`
  - `isAnyOverlayOpen(): boolean` / `isOverlayOpen(id: string): boolean` / `topOverlayId(): string | null` / `resetOverlayStack(): void`
  - `focusableWithin(root: HTMLElement): HTMLElement[]` / `nextFocusTarget(elements: HTMLElement[], active: Element | null, shift: boolean): HTMLElement | null`

- [ ] **Step 1: 写失败测试**

```ts
// tests/frontend/overlayA11y.test.ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick, ref } from 'vue';
import { mount } from '@vue/test-utils';
import {
  focusableWithin,
  isAnyOverlayOpen,
  isOverlayOpen,
  nextFocusTarget,
  resetOverlayStack,
  topOverlayId,
  useOverlayA11y,
} from '@/modules/overlayA11y';

const Harness = defineComponent({
  props: {
    id: { type: String, required: true },
    open: { type: Boolean, required: true },
    onClose: { type: Function, required: true },
  },
  setup(props) {
    const panel = ref<HTMLElement | null>(null);
    useOverlayA11y({ id: props.id, isOpen: () => props.open, panelRef: panel, onClose: () => props.onClose() });
    return () =>
      props.open
        ? h('section', { ref: panel, 'data-testid': `panel-${props.id}` }, [
            h('button', { class: 'a' }, 'A'),
            h('button', { class: 'b', disabled: true }, 'B'),
            h('button', { class: 'c' }, 'C'),
          ])
        : null;
  },
});

function press(key: string, shiftKey = false) {
  window.dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey, bubbles: true, cancelable: true }));
}

beforeEach(() => {
  resetOverlayStack();
  document.body.className = '';
  document.body.innerHTML = '<button id="trigger">触发</button>';
});

describe('overlayA11y 纯函数', () => {
  it('focusableWithin 过滤 disabled 与 tabindex="-1"', () => {
    const root = document.createElement('div');
    root.innerHTML = '<button class="a">A</button><button disabled>B</button><span tabindex="-1">C</span>';
    document.body.appendChild(root);
    expect(focusableWithin(root).map((el) => el.className || el.tagName)).toEqual(['a']);
  });

  it('nextFocusTarget 空集返回 null，越界回绕', () => {
    const a = document.createElement('button');
    const b = document.createElement('button');
    expect(nextFocusTarget([], null, false)).toBeNull();
    expect(nextFocusTarget([a, b], a, true)).toBe(b);
    expect(nextFocusTarget([a, b], b, false)).toBe(a);
  });
});
```

- [ ] **Step 2: 运行测试确认失败**

Run: `npx vitest run tests/frontend/overlayA11y.test.ts`
Expected: FAIL — `Failed to resolve import "@/modules/overlayA11y"`

- [ ] **Step 3: 实现模块**

```ts
// frontend/src/modules/overlayA11y.ts
import { nextTick, onBeforeUnmount, watch, type Ref } from 'vue';

/**
 * 浮层无障碍行为：Esc 关闭（仅栈顶）、Tab 焦点陷阱、滚动锁（计数幂等）、焦点归还。
 * 模块级栈与锁计数是刻意的：多个浮层各自接一行即可共享同一套规则。
 */
const stack: string[] = [];
let lockCount = 0;

export function isAnyOverlayOpen(): boolean {
  return stack.length > 0;
}

export function isOverlayOpen(id: string): boolean {
  return stack.includes(id);
}

export function topOverlayId(): string | null {
  return stack.length ? stack[stack.length - 1] : null;
}

/** 测试/异常收尾用：清空栈、锁与 body 类（不负责恢复已改动的 DOM 属性）。 */
export function resetOverlayStack(): void {
  stack.length = 0;
  lockCount = 0;
  document.body.classList.remove('overlay-open');
}

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function isVisible(el: HTMLElement): boolean {
  if (el.hasAttribute('inert')) return false;
  const style = window.getComputedStyle(el);
  return style.display !== 'none' && style.visibility !== 'hidden';
}

export function focusableWithin(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) => el.tabIndex !== -1 && isVisible(el)
  );
}

export function nextFocusTarget(
  elements: HTMLElement[],
  active: Element | null,
  shift: boolean
): HTMLElement | null {
  if (!elements.length) return null;
  const index = elements.findIndex((el) => el === active);
  if (index === -1) return shift ? elements[elements.length - 1] : elements[0];
  const next = shift ? index - 1 : index + 1;
  return elements[(next + elements.length) % elements.length];
}

export interface OverlayA11yOptions {
  id: string;
  isOpen: () => boolean;
  panelRef: Ref<HTMLElement | null>;
  onClose: () => void;
  /** 默认 true；帮助浮层同样用 Esc 关闭。 */
  closeOnEsc?: boolean;
}

export function useOverlayA11y(options: OverlayA11yOptions): void {
  const { id, panelRef, onClose, closeOnEsc = true } = options;
  let restoreTarget: HTMLElement | null = null;
  let panelTabIndexAdded = false;

  function onKeydown(event: KeyboardEvent): void {
    if (topOverlayId() !== id) return; // 只有最上层浮层响应键盘
    if (event.key === 'Escape') {
      if (!closeOnEsc) return;
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;
    const panel = panelRef.value;
    if (!panel) return;
    const focusables = focusableWithin(panel);
    event.preventDefault();
    if (!focusables.length) return;
    const active = document.activeElement as HTMLElement | null;
    if (!active || !panel.contains(active)) {
      (event.shiftKey ? focusables[focusables.length - 1] : focusables[0]).focus();
      return;
    }
    nextFocusTarget(focusables, active, event.shiftKey)?.focus();
  }

  function open(): void {
    if (!stack.includes(id)) stack.push(id);
    lockCount += 1;
    if (lockCount === 1) document.body.classList.add('overlay-open');
    restoreTarget = (document.activeElement as HTMLElement | null) ?? null;
    void nextTick(() => {
      const panel = panelRef.value;
      if (!panel) return;
      const preferred = panel.querySelector<HTMLElement>('[data-autofocus]');
      if (preferred) {
        preferred.focus();
        return;
      }
      const first = focusableWithin(panel)[0];
      if (first) {
        first.focus();
        return;
      }
      if (!panel.hasAttribute('tabindex')) {
        panel.setAttribute('tabindex', '-1');
        panelTabIndexAdded = true;
      }
      panel.focus();
    });
  }

  function close(): void {
    const index = stack.indexOf(id);
    if (index !== -1) stack.splice(index, 1);
    lockCount = Math.max(0, lockCount - 1);
    if (lockCount === 0) document.body.classList.remove('overlay-open');
    if (panelTabIndexAdded && panelRef.value) {
      panelRef.value.removeAttribute('tabindex');
      panelTabIndexAdded = false;
    }
    const target = restoreTarget;
    restoreTarget = null;
    if (!target) return;
    void nextTick(() => {
      if (target.isConnected && !(target as HTMLButtonElement).disabled) target.focus();
    });
  }

  watch(() => options.isOpen(), (openNow) => (openNow ? open() : close()), { immediate: true, flush: 'sync' });
  window.addEventListener('keydown', onKeydown);
  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onKeydown);
    if (options.isOpen()) close();
  });
}
```

- [ ] **Step 4: 追加行为用例（同一测试文件）**

```ts
describe('useOverlayA11y 行为', () => {
  it('打开时焦点进面板第一个可聚焦元素；关闭后归还触发者', async () => {
    const onClose = vi.fn();
    const trigger = document.getElementById('trigger') as HTMLButtonElement;
    trigger.focus();
    const wrapper = mount(Harness, { props: { id: 'x', open: false, onClose }, attachTo: document.body });
    await wrapper.setProps({ open: true });
    await nextTick();
    expect(document.activeElement?.className).toBe('a');
    await wrapper.setProps({ open: false });
    await nextTick();
    expect(document.activeElement).toBe(trigger);
    wrapper.unmount();
  });

  it('Tab 在面板内回绕（末→首、首→末）', async () => {
    const wrapper = mount(Harness, { props: { id: 'x', open: true, onClose: vi.fn() }, attachTo: document.body });
    await nextTick();
    (document.querySelector('.c') as HTMLElement).focus();
    press('Tab');
    expect(document.activeElement?.className).toBe('a');
    press('Tab', true);
    expect(document.activeElement?.className).toBe('c');
    wrapper.unmount();
  });

  it('Esc 只由栈顶浮层响应并调用 onClose', async () => {
    const onCloseTop = vi.fn();
    const onCloseBottom = vi.fn();
    const bottom = mount(Harness, { props: { id: 'bottom', open: true, onClose: onCloseBottom }, attachTo: document.body });
    const top = mount(Harness, { props: { id: 'top', open: true, onClose: onCloseTop }, attachTo: document.body });
    expect(topOverlayId()).toBe('top');
    press('Escape');
    expect(onCloseTop).toHaveBeenCalledTimes(1);
    expect(onCloseBottom).not.toHaveBeenCalled();
    bottom.unmount();
    top.unmount();
  });

  it('滚动锁计数幂等：两个浮层全关才摘 body.overlay-open', async () => {
    const a = mount(Harness, { props: { id: 'a', open: true, onClose: vi.fn() }, attachTo: document.body });
    const b = mount(Harness, { props: { id: 'b', open: true, onClose: vi.fn() }, attachTo: document.body });
    expect(document.body.classList.contains('overlay-open')).toBe(true);
    expect(isAnyOverlayOpen()).toBe(true);
    await a.setProps({ open: false });
    expect(document.body.classList.contains('overlay-open')).toBe(true);
    await b.setProps({ open: false });
    expect(document.body.classList.contains('overlay-open')).toBe(false);
    expect(isOverlayOpen('a')).toBe(false);
    a.unmount();
    b.unmount();
  });
});
```

Run: `npx vitest run tests/frontend/overlayA11y.test.ts`
Expected: PASS（6 例）

- [ ] **Step 5: 加滚动锁 CSS**

追加到 `frontend/src/styles.css`（`.view-panel.is-active` 滚动条规则之后）：

```css
/* 浮层打开时冻结真实滚动容器（.view-panel.is-active），计数幂等由 overlayA11y 负责 */
body.overlay-open .view-panel.is-active {
  overflow: hidden;
}
```

- [ ] **Step 6: 全量门禁 + 提交**

Run: `npx vitest run` → 全绿；`npx vue-tsc --noEmit` → 0 error

```bash
git add frontend/src/modules/overlayA11y.ts frontend/src/styles.css tests/frontend/overlayA11y.test.ts
git commit -m "feat: 新增浮层无障碍行为模块（Esc/焦点陷阱/滚动锁/焦点归还）"
```

---

### Task 2: 4 个既有浮层接线 + 通知面板 ARIA/遮罩一致性

**Files:**
- Modify: `frontend/src/components/PlanDraftDialog.vue`（`:111-112` 根节点与 `<script setup>`）
- Modify: `frontend/src/components/CustomStrategyDialog.vue`（`:2-3` 根节点）
- Modify: `frontend/src/App.vue`（`:92-93` 通知面板；`:259-260` 更多抽屉；`<script setup>`）
- Test: `tests/frontend/AppShell.test.ts`（追加）、`tests/frontend/PlanDraftDialog.test.ts`（追加）

**Interfaces:**
- Consumes: Task 1 的 `useOverlayA11y`
- Produces: 4 个浮层均带 `role="dialog"` + `aria-modal="true"`，Esc 可关、Tab 不出面板、打开时 `document.body.classList.contains('overlay-open')`

- [ ] **Step 1: 写失败测试（AppShell.test.ts 追加）**

```ts
describe('浮层键盘行为（spec §6）', () => {
  it('通知面板带 aria-modal，Esc 关闭并归还焦点给铃铛', async () => {
    const wrapper = mount(App, { global: viewStubs, attachTo: document.body });
    const bell = wrapper.find('.notif-wrap button');
    await bell.trigger('click');
    const panel = wrapper.find('.notif-panel');
    expect(panel.exists()).toBe(true);
    expect(panel.attributes('aria-modal')).toBe('true');
    expect(document.body.classList.contains('overlay-open')).toBe(true);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await flushPromises();
    expect(wrapper.find('.notif-panel').exists()).toBe(false);
    expect(document.body.classList.contains('overlay-open')).toBe(false);
    expect(document.activeElement).toBe(bell.element);
    wrapper.unmount();
  });

  it('更多抽屉 Esc 关闭并摘掉滚动锁', async () => {
    const wrapper = mount(App, { global: viewStubs, attachTo: document.body });
    await wrapper.find('.bottom-nav button[aria-label="更多"]').trigger('click');
    expect(wrapper.find('.more-sheet').exists()).toBe(true);
    expect(document.body.classList.contains('overlay-open')).toBe(true);
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await flushPromises();
    expect(wrapper.find('.more-sheet').exists()).toBe(false);
    expect(document.body.classList.contains('overlay-open')).toBe(false);
    wrapper.unmount();
  });
});
```

（AppShell.test.ts 顶部需补 `import { flushPromises } from '@vue/test-utils'`，并给既有 `mount(App, { global: viewStubs })` 不需要改动。）

Run: `npx vitest run tests/frontend/AppShell.test.ts`
Expected: FAIL — `expected undefined to be 'true'`（`aria-modal` 缺失）

- [ ] **Step 2: 接线 4 个浮层**

`PlanDraftDialog.vue`（`<script setup>` 内）：

```ts
import { ref } from 'vue';
import { useOverlayA11y } from '@/modules/overlayA11y';

const overlayPanel = ref<HTMLElement | null>(null);
useOverlayA11y({
  id: 'plan-draft',
  isOpen: () => assist.visible,
  panelRef: overlayPanel,
  onClose: () => assist.close(),
});
```

模板 `<section class="dialog-panel plan-draft-panel" ...>` 加 `ref="overlayPanel"`（`v-if` 在父级 backdrop 上，元素仅在打开时存在 → 组合式函数在 `nextTick` 后取 ref）。

`CustomStrategyDialog.vue` 同形：

```ts
const overlayPanel = ref<HTMLElement | null>(null);
useOverlayA11y({
  id: 'custom-strategy',
  isOpen: () => screener.strategyEditorOpen,
  panelRef: overlayPanel,
  onClose: () => screener.closeStrategyEditor(),
});
```

模板 `<section class="dialog-panel custom-strategy-panel" ...>` 加 `ref="overlayPanel"`。

`App.vue`：

1. 通知面板 `<div v-if="notifOpen" class="notif-panel" role="dialog" aria-label="通知中心">` → 追加 `aria-modal="true"` 与 `ref="notifPanel"`；遮罩 `<div v-if="notifOpen" class="notif-backdrop" @click="notifOpen = false">` → `@click.self="notifOpen = false"`（功能等价，字面统一）。
2. 更多抽屉 `<section class="more-sheet" ...>` → 加 `ref="moreSheetPanel"`。

`<script setup>` 内（`notifOpen`/`moreSheetOpen` 已在作用域）：

```ts
import { useOverlayA11y } from '@/modules/overlayA11y';

const notifPanel = ref<HTMLElement | null>(null);
const moreSheetPanel = ref<HTMLElement | null>(null);

useOverlayA11y({
  id: 'notif',
  isOpen: () => notifOpen.value,
  panelRef: notifPanel,
  onClose: () => {
    notifOpen.value = false;
  },
});

useOverlayA11y({
  id: 'more-sheet',
  isOpen: () => moreSheetOpen.value,
  panelRef: moreSheetPanel,
  onClose: () => {
    moreSheetOpen.value = false;
  },
});
```

- [ ] **Step 3: 追加 PlanDraftDialog 焦点回归用例**

```ts
// tests/frontend/PlanDraftDialog.test.ts
it('打开时焦点进入面板、Esc 关闭（spec §6）', async () => {
  const assist = useAssistStore();
  assist.visible = true;
  const wrapper = mount(PlanDraftDialog, { attachTo: document.body });
  await nextTick();
  expect(document.activeElement?.closest('.dialog-panel')).not.toBeNull();
  window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
  await flushPromises();
  expect(assist.visible).toBe(false);
  wrapper.unmount();
});
```

- [ ] **Step 4: 全量门禁 + 提交**

Run: `npx vitest run` → 全绿；`npx vue-tsc --noEmit` → 0 error

```bash
git add frontend/src/App.vue frontend/src/components/PlanDraftDialog.vue frontend/src/components/CustomStrategyDialog.vue tests/frontend/AppShell.test.ts tests/frontend/PlanDraftDialog.test.ts
git commit -m "feat: 四个浮层接入统一键盘行为并补齐通知面板 ARIA"
```

---

### Task 3: 加载态与空态语义拆分（CSS + 5 处换类）

**Files:**
- Modify: `frontend/src/styles.css`（`:2606-2630` `.empty-state` 族 → 共享选择器；追加 `.loading-state` 与 reduced-motion）
- Modify: `frontend/src/views/ViewScreener.vue`（`:235-238`、`:410-413`、`:505-508`）
- Modify: `frontend/src/views/ViewOverview.vue`（`:144-148`）
- Test: `tests/frontend/ViewScreener.test.ts`、`tests/frontend/ViewOverview.test.ts`（追加）

**Interfaces:**
- Consumes: 无
- Produces: `.loading-state`（`role="status"` + 转圈）与 `.empty-state`（结论 + 动作）语义分开；后续任务的所有加载分支都用 `.loading-state`

- [ ] **Step 1: 写失败测试**

```ts
// tests/frontend/ViewScreener.test.ts（追加）
it('精选列表加载中显示 .loading-state[role="status"] 而非 .empty-state（spec §7）', async () => {
  const quotes = useQuotesStore();
  quotes.loading = true;
  const wrapper = mount(ViewScreener);
  await flushPromises();
  const loadingNode = wrapper.find('.loading-state[role="status"]');
  expect(loadingNode.exists()).toBe(true);
  expect(loadingNode.text()).toContain('正在读取真实行情');
  expect(wrapper.findAll('.empty-state').some((node) => node.text().includes('正在读取真实行情'))).toBe(false);
});
```

```ts
// tests/frontend/ViewOverview.test.ts（追加）
it('指数加载中显示 .loading-state[role="status"]（spec §7）', async () => {
  const quotes = useQuotesStore();
  quotes.loading = true;
  const wrapper = mount(ViewOverview);
  await flushPromises();
  expect(wrapper.find('.loading-state[role="status"]').text()).toContain('正在读取指数');
});
```

```ts
// tests/frontend/ViewScreener.test.ts（追加：精选空态就地动作）
it('精选无结果时空态带「重新读取行情」按钮并调用 fetchScreener（spec §7.4）', async () => {
  const screener = useScreenerStore();
  const spy = vi.spyOn(screener, 'fetchScreener').mockResolvedValue(undefined as any);
  const wrapper = mount(ViewScreener);
  await flushPromises();
  const empty = wrapper.findAll('.empty-state').find((node) => node.text().includes('没有找到符合条件的股票'));
  await empty!.find('button').trigger('click');
  expect(spy).toHaveBeenCalledTimes(1);
});
```

Run: `npx vitest run tests/frontend/ViewScreener.test.ts tests/frontend/ViewOverview.test.ts`
Expected: FAIL — `.loading-state` 不存在 / 空态无按钮

- [ ] **Step 2: 改 CSS（共享版式 + 转圈 + 无障碍降级）**

`frontend/src/styles.css:2606-2630` 四处选择器改为共享：

```css
:is(.empty-state, .loading-state) {
  display: grid;
  justify-items: center;
  gap: var(--space-2);
  padding: 44px var(--space-5);
  color: var(--muted);
  text-align: center;
}

:is(.empty-state, .loading-state) svg {
  width: 23px;
  height: 23px;
  margin-bottom: 2px;
  color: var(--coral);
}

:is(.empty-state, .loading-state) strong {
  color: var(--ink-soft);
  font-size: var(--fs-sm);
  font-weight: 500;
}

:is(.empty-state, .loading-state) span {
  font-size: var(--fs-xs);
}

/* 加载态 = 与空态同版式 + 转圈；空态图标保持静止（语义靠形状与文案区分） */
.loading-state svg {
  animation: spin 900ms linear infinite;
}

@media (prefers-reduced-motion: reduce) {
  .loading-state svg {
    animation: none;
  }
}
```

（已知既有 quirk，**本批不修**：`.compact-empty` 与 `.empty-state` 同特异性且声明更早，其 padding 早已被后者覆盖；本次仅把选择器扩成 `:is(...)`，声明位置不变，视觉逐字保持原样。）

- [ ] **Step 3: 5 处换类（文案逐字不变，仅类与 role）**

| 文件:行 | 改动 |
|---|---|
| `ViewScreener.vue:235` | `class="empty-state"` → `class="loading-state" role="status"` |
| `ViewScreener.vue:410` | 同上 |
| `ViewScreener.vue:505` | 同上 |
| `ViewOverview.vue:144` | `class="empty-state compact-empty"` → `class="loading-state compact-empty" role="status"` |
| 其余 `.empty-state`（ResultsPanel 空态等） | **不动** |

精选空态（`ViewScreener.vue:414-417`）就地动作（spec §7.4 第 1 行）：

```html
        <div v-else-if="!filteredRows.length" class="empty-state">
          <i data-lucide="search-x" aria-hidden="true"></i><strong>没有找到符合条件的股票</strong
          ><span>可以放宽 PE、PB 或涨幅条件再试一次。</span
          ><button class="button button-secondary" type="button" :disabled="loading" @click="fetchScreener()">
            重新读取行情
          </button>
        </div>
```

（`fetchScreener` 需从 screener store 解构：`ViewScreener.vue` 的 `storeToRefs(screener)` 旁补 `const { fetchScreener } = screener;`。）

Run: `npx vitest run tests/frontend/ViewScreener.test.ts tests/frontend/ViewOverview.test.ts`
Expected: PASS

- [ ] **Step 4: 机械核对无「用空态表示加载」残留**

Run: `npx rg -n -U 'class="empty-state[^"]*"[^>]*>\s*(<i[^>]*loader-circle|[\s\S]{0,200}?loader-circle)' frontend/src --glob '*.vue'`
Expected: 0 命中（`rg` 若未安装用 `grep -rn` 等价核实）

- [ ] **Step 5: 全量门禁 + 提交**

Run: `npx vitest run` 全绿；`npx vue-tsc --noEmit` 0 error

```bash
git add frontend/src/styles.css frontend/src/views/ViewScreener.vue frontend/src/views/ViewOverview.vue tests/frontend/ViewScreener.test.ts tests/frontend/ViewOverview.test.ts
git commit -m "refactor: 拆分加载态与空态语义并统一版式"
```

---

### Task 4: ViewGrid 三处加载分支 + 两处空态按钮

**Files:**
- Modify: `frontend/src/views/ViewGrid.vue`（`:211` 前插入网格建议加载；`:431` 前插入策略回测加载 + `:503-506` 空态按钮；`:581` 前插入对比加载 + `:663-666` 空态按钮）
- Test: `tests/frontend/ViewGrid.test.ts`

**Interfaces:**
- Consumes: Task 3 的 `.loading-state`；`gridLoading`/`strategyLoading`（grid/strategy store）、`compare.runLoading`（compare store）、`backtestStrategy()`、`compare.runCompare()`、`previewGrid()`
- Produces: 三个结果区都先给加载态再给结果/空态

- [ ] **Step 1: 写失败测试**

```ts
// tests/frontend/ViewGrid.test.ts（追加）
it('策略回测运行中显示加载态而非空态（spec §7.3-4）', async () => {
  const strategy = useStrategyStore();
  strategy.strategyType = 'ma_cross';
  strategy.strategyLoading = true;
  const wrapper = mount(ViewGrid, { global: { plugins: [] } });
  await flushPromises();
  expect(wrapper.find('.loading-state').text()).toContain('正在回放回测');
  expect(wrapper.text()).not.toContain('系统会基于历史日线按参数模拟买卖');
});

it('策略空态带「运行回测」按钮并调用 backtestStrategy（spec §7.4）', async () => {
  const strategy = useStrategyStore();
  strategy.strategyType = 'ma_cross';
  const spy = vi.spyOn(strategy, 'backtestStrategy').mockResolvedValue(undefined as any);
  const wrapper = mount(ViewGrid, { global: { plugins: [] } });
  await flushPromises();
  const empty = wrapper.findAll('.empty-state').find((node) => node.text().includes('运行'));
  await empty!.find('button').trigger('click');
  expect(spy).toHaveBeenCalledTimes(1);
});

it('多策略对比运行中显示加载态（spec §7.3-5）', async () => {
  const strategy = useStrategyStore();
  strategy.strategyType = 'compare';
  const compare = useCompareStore();
  compare.runLoading = true;
  const wrapper = mount(ViewGrid, { global: { plugins: [] } });
  await flushPromises();
  expect(wrapper.find('.loading-state').text()).toContain('正在对比');
});
```

Run: `npx vitest run tests/frontend/ViewGrid.test.ts`
Expected: FAIL — 找不到 `.loading-state` / 空态里没有按钮

- [ ] **Step 2: 插加载分支（把原 `v-if` 降为 `v-else-if`）**

网格建议（`:211` 之前插入，`:211` 的 `v-if="gridResult"` 改 `v-else-if="gridResult"`）：

```html
        <div v-if="gridLoading" class="loading-state" data-testid="grid-suggestion-loading" role="status">
          <i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在计算网格参数</strong
          ><span>基于历史日线给出区间、每格资金与建议投入。</span>
        </div>
```

策略回测（`:431` 之前插入，`:431` 的 `v-if="strategyResult"` 改 `v-else-if="strategyResult"`）：

```html
        <div v-if="strategyLoading" class="loading-state" data-testid="strategy-loading" role="status">
          <i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在回放回测</strong
          ><span>日线逐笔重放完成后显示权益曲线与指标。</span>
        </div>
```

多策略对比（`:581` 之前插入，`:581` 的 `v-if="compare.runResult"` 改 `v-else-if="compare.runResult"`）：

```html
        <div v-if="compare.runLoading" class="loading-state" data-testid="compare-loading" role="status">
          <i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在对比</strong
          ><span>勾选策略将在同一份日线上依次重放。</span>
        </div>
```

- [ ] **Step 3: 两处空态加就地动作按钮**

`ViewGrid.vue:503-506` → 追加按钮：

```html
        <div v-else class="empty-state">
          <i data-lucide="activity" aria-hidden="true"></i><strong>运行{{ strategyTypeLabel }}回测</strong
          ><span>系统会基于历史日线按参数模拟买卖并给出权益曲线与指标。</span
          ><button class="button button-secondary" type="button" :disabled="strategyLoading" @click="backtestStrategy()">
            运行回测
          </button>
        </div>
```

`ViewGrid.vue:663-666` → 追加按钮：

```html
        <div v-else class="empty-state">
          <i data-lucide="git-compare" aria-hidden="true"></i><strong>运行多策略对比</strong
          ><span>同一份历史日线在勾选的策略间重放，对比收益、回撤与夏普。</span
          ><button class="button button-secondary" type="button" :disabled="compare.runLoading" @click="compare.runCompare()">
            开始对比
          </button>
        </div>
```

（与配置面板同名同动作是**有意为之**：同一动作只写一遍语义，spec §7.4 已披露。）

- [ ] **Step 4: 回归 + 门禁 + 提交**

Run: `npx vitest run tests/frontend/ViewGrid.test.ts` → PASS；`npx vitest run` 全绿；`npx vue-tsc --noEmit` 0 error

```bash
git add frontend/src/views/ViewGrid.vue tests/frontend/ViewGrid.test.ts
git commit -m "feat: 策略视图补齐回测/对比/网格加载态与空态动作"
```

---

### Task 5: ViewPlans 复盘加载态 + 计划空态跳转按钮

**Files:**
- Modify: `frontend/src/views/ViewPlans.vue`（`:199-202` 空态按钮；`:229` KPI 区前插加载分支；`:327` 前插 trace 加载）
- Test: `tests/frontend/ViewPlans.test.ts`

**Interfaces:**
- Consumes: Task 3 的 `.loading-state`；`review.loading`/`review.traceLoading`（review store）、`quotes.switchView('screener')`
- Produces: 复盘首次加载不再显示一排裸 `--`

- [ ] **Step 1: 写失败测试**

```ts
// tests/frontend/ViewPlans.test.ts（追加）
it('复盘首次加载显示加载态而非裸 --（spec §7.3-7）', async () => {
  const review = useReviewStore();
  review.loading = true;
  review.review = null;
  review.expanded = true;
  const wrapper = mount(ViewPlans);
  await flushPromises();
  expect(wrapper.find('[data-testid="review-loading"]').text()).toContain('正在回放复盘');
  expect(wrapper.find('[data-testid="review-kpis"]').exists()).toBe(false);
});

it('无计划空态按钮跳转选股器（spec §7.4）', async () => {
  const wrapper = mount(ViewPlans);
  await flushPromises();
  const quotes = useQuotesStore();
  const empty = wrapper.findAll('.empty-state').find((node) => node.text().includes('还没有交易计划'));
  await empty!.find('button').trigger('click');
  expect(quotes.view).toBe('screener');
});
```

Run: `npx vitest run tests/frontend/ViewPlans.test.ts`
Expected: FAIL — `review-loading` 不存在

- [ ] **Step 2: 实现**

`:199-202` 空态：

```html
        <div v-if="!activePlans.length" class="empty-state">
          <i data-lucide="clipboard-plus" aria-hidden="true"></i><strong>还没有交易计划</strong
          ><span>先写下一个你愿意执行的交易剧本。</span
          ><button class="button button-secondary" type="button" @click="switchView('screener')">去选股器挑一只</button>
        </div>
```

`:229` 的 `<div class="review-kpis" data-testid="review-kpis">` **之前**插入，并把该 div 改成 `v-else`：

```html
          <div
            v-if="review.loading && !review.review"
            class="loading-state compact-empty"
            data-testid="review-loading"
            role="status"
          >
            <i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在回放复盘</strong
            ><span>按设计口径逐日回放交易计划。</span>
          </div>
```

`:327` 的 `<p v-if="review.traceError" ...>` **之前**插入：

```html
          <div
            v-if="review.traceLoading && !activeScanTrace.length"
            class="loading-state compact-empty"
            data-testid="review-trace-loading"
            role="status"
          >
            <i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在读取扫描记录</strong>
          </div>
```

`<script setup>` 里 `quotes` 的解构补齐 `switchView`（现为 `const { quoteFor, selectStock } = quotes;`）：

```ts
const { quoteFor, selectStock, switchView } = quotes;
```

- [ ] **Step 3: 回归 + 门禁 + 提交**

Run: `npx vitest run tests/frontend/ViewPlans.test.ts` → PASS；全量 vitest + `npx vue-tsc --noEmit` 全绿

```bash
git add frontend/src/views/ViewPlans.vue tests/frontend/ViewPlans.test.ts
git commit -m "feat: 交易计划补齐复盘加载态与空态动作"
```

---

### Task 6: ViewPortfolio KPI「计算中」+ 净值空态跳转按钮

**Files:**
- Modify: `frontend/src/views/ViewPortfolio.vue`（`:69-118` KPI 值槽；`:128-132` 空态按钮）
- Test: `tests/frontend/ViewPortfolio.test.ts`

**Interfaces:**
- Consumes: Task 3 的 `.loading-state`；`store.loading`/`kpis`、`quotes.switchView('plans')`
- Produces: `kpiText(rendered: string): string` —— `store.loading && !kpis` 时返回「计算中」，否则原样返回（缺失仍 `--`）

- [ ] **Step 1: 写失败测试**

```ts
// tests/frontend/ViewPortfolio.test.ts（追加）
it('加载中且无数据时 KPI 显示「计算中」而非裸 --（spec §7.3-10）', async () => {
  const store = usePortfolioStore();
  store.loading = true;
  const wrapper = mount(ViewPortfolio);
  await flushPromises();
  expect(wrapper.find('[data-testid="portfolio-kpis"]').text()).toContain('计算中');
});

it('已有数据时重算不清空旧值', async () => {
  const store = usePortfolioStore();
  store.payload = makePayload();
  store.loading = true;
  const wrapper = mount(ViewPortfolio);
  await flushPromises();
  expect(wrapper.find('[data-testid="portfolio-kpis"]').text()).not.toContain('计算中');
});

it('无净值空态按钮跳转交易计划（spec §7.4）', async () => {
  const wrapper = mount(ViewPortfolio);
  await flushPromises();
  const quotes = useQuotesStore();
  await wrapper.find('[data-testid="portfolio-empty"] button').trigger('click');
  expect(quotes.view).toBe('plans');
});
```

（`makePayload` 直接照该文件既有定义；`usePortfolioStore` 的 `payload` ref 已暴露且可写。）

Run: `npx vitest run tests/frontend/ViewPortfolio.test.ts`
Expected: FAIL — KPI 区无「计算中」

- [ ] **Step 2: 实现**

`<script setup>` 追加：

```ts
const kpiLoading = computed(() => store.loading && !kpis.value);
/** 加载中且无任何结果 → 「计算中」；已加载后字段缺失仍由格式化函数给 `--`（不造数）。 */
function kpiText(rendered: string): string {
  return kpiLoading.value ? '计算中' : rendered;
}
```

11 个 KPI 值槽逐个包一层 `kpiText(...)`（示例，其余同形）：

```html
      <div class="kpi">
        <b>{{ kpiText(formatAmount(kpis?.navNow)) }}</b
        ><span>毛净值</span>
      </div>
      <div class="kpi">
        <b>{{ kpiText(planText) }}</b>
        <span>计划 执行中/已触发/已了结/未入场</span>
      </div>
```

`:128-132` 空态追加按钮：

```html
      <div v-if="!hasNavPoints" class="empty-state" data-testid="portfolio-empty">
        <i data-lucide="chart-line" aria-hidden="true"></i>
        <strong>暂无计划持仓</strong>
        <span>窗口内还没有可回放的买入计划——先创建并触发买入计划，再回到这里查看毛/净净值曲线。</span>
        <button class="button button-secondary" type="button" @click="switchView('plans')">去交易计划</button>
      </div>
```

（`switchView` 需从 quotes 解构：`const { quoteFor, selectStock, switchView } = useQuotesStore();` —— `quoteFor` 供 Task 12 使用。）

- [ ] **Step 3: 回归 + 门禁 + 提交**

Run: `npx vitest run tests/frontend/ViewPortfolio.test.ts` → PASS；全量 vitest + `npx vue-tsc --noEmit` 全绿

```bash
git add frontend/src/views/ViewPortfolio.vue tests/frontend/ViewPortfolio.test.ts
git commit -m "feat: 组合风险 KPI 加载中显示计算中并补空态入口"
```

---

### Task 7: ViewStockDetail 报价与分钟线加载态

**Files:**
- Modify: `frontend/src/views/ViewStockDetail.vue`（`:23-24` 报价区、`:87-92` 分钟线区、`loadMinute`）
- Test: `tests/frontend/ViewStockDetail.test.ts`

**Interfaces:**
- Consumes: Task 3 的 `.loading-state`；`quotes.loading`、`fetchMinute`
- Produces: `minuteLoading` ref（请求在途时 true，`finally` 复位）

- [ ] **Step 1: 写失败测试**

```ts
// tests/frontend/ViewStockDetail.test.ts（追加）
it('行情未就绪时报价区显示加载态而非裸 --（spec §7.3-8）', async () => {
  const quotes = useQuotesStore();
  quotes.loading = true;
  quotes.watchlist = [];
  quotes.market = { provider: '', fetchedAt: 0, quotes: [], indices: [] } as any;
  const wrapper = mount(ViewStockDetail);
  await flushPromises();
  expect(wrapper.find('[data-testid="detail-loading"]').text()).toContain('正在读取行情');
});

it('分钟线请求在途显示加载态（spec §7.3-9）', async () => {
  let resolveMinute: (value: any) => void = () => {};
  fetchMinuteMock.mockImplementationOnce(() => new Promise((resolve) => (resolveMinute = resolve)));
  const wrapper = mount(ViewStockDetail, { attachTo: document.body });
  await flushPromises();
  await wrapper.findAll('.minute-toolbar button')[1].trigger('click');
  expect(wrapper.find('[data-testid="minute-loading"]').exists()).toBe(true);
  resolveMinute(minuteResponse());
  await flushPromises();
  expect(wrapper.find('[data-testid="minute-loading"]').exists()).toBe(false);
  wrapper.unmount();
});
```

Run: `npx vitest run tests/frontend/ViewStockDetail.test.ts`
Expected: FAIL — `detail-loading` / `minute-loading` 不存在

- [ ] **Step 2: 实现**

模板 `:23-24`（`<section class="selected-stock-panel surface">` 之后、`.selected-stock-summary` 之前）插入，并把 `.selected-stock-summary` 改成 `v-else`：

```html
      <div v-if="loading && !selectedStock" class="loading-state" data-testid="detail-loading" role="status">
        <i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在读取行情</strong
        ><span>行情返回后显示报价、指标与操作入口。</span>
      </div>
      <div v-else class="selected-stock-summary">
```

（`loading` 需加入既有 `storeToRefs(quotes)` 解构；已有缓存的 `selectedStock` 仍照常显示真实值。）

分钟线 `:87-92`（`.minute-toolbar` 之后）插入：

```html
      <div v-if="minuteLoading" class="loading-state" data-testid="minute-loading" role="status">
        <i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在读取分钟线</strong>
      </div>
```

`<script setup>`：新增 `const minuteLoading = ref(false);`，`loadMinute` 改为：

```ts
async function loadMinute(period: string) {
  minutePeriod.value = period;
  if (!selectedCode.value) return;
  minuteLoading.value = true;
  try {
    const res = await fetchMinute(selectedCode.value, period);
    minuteState.value = res.state;
    minuteSource.value = res.source;
    minuteDegraded.value = res.degraded;
    minuteUpdatedAtMs.value = res.updatedAtMs ?? null;
    minuteBars.value = res.bars || [];
    minuteChartPeriod.value = period;
  } catch (error: any) {
    if (error?.status === 429) {
      workspace.showToast('请求过于频繁', 'error');
      return;
    }
    minuteState.value = 'unavailable';
    minuteSource.value = null;
    minuteDegraded.value = true;
    minuteUpdatedAtMs.value = null;
    minuteBars.value = [];
  } finally {
    minuteLoading.value = false;
  }
}
```

（降级态文案映射 `MINUTE_STRIP_TEXT`、429 分支与状态条**一律不动**。）

- [ ] **Step 3: 回归 + 门禁 + 提交**

Run: `npx vitest run tests/frontend/ViewStockDetail.test.ts` → PASS（含既有降级态用例）；全量 vitest + `npx vue-tsc --noEmit` 全绿

```bash
git add frontend/src/views/ViewStockDetail.vue tests/frontend/ViewStockDetail.test.ts
git commit -m "feat: 个股详情补齐报价与分钟线加载态"
```

---

### Task 8: Toast 队列（去重/上限/可关闭/暂停/分时长）

**Files:**
- Create: `frontend/src/modules/toastQueue.ts`
- Modify: `frontend/src/stores/useWorkspaceStore.ts`（`:73-91` `showToast` 变薄委托）
- Modify: `frontend/src/styles.css`（`.toast` 族追加辅助类，`:2756-2790` 之后）
- Modify: `frontend/src/App.vue:279`（去掉 `aria-atomic="true"`）
- Test: `tests/frontend/toastQueue.test.ts`（新建）

**Interfaces:**
- Consumes: 无
- Produces: `TOAST_CAP = 3`、`durationFor(tone)`、`toastKey(tone, message)`、`showToast(message, tone, deps)`、`resetToasts()`；`useWorkspaceStore.showToast(message, tone = 'success')` 签名与返回值不变

- [ ] **Step 1: 写失败测试**

```ts
// tests/frontend/toastQueue.test.ts
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { TOAST_CAP, durationFor, resetToasts, showToast, toastKey } from '@/modules/toastQueue';

function region() {
  return document.getElementById('toast-region') as HTMLElement;
}

beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML = '<div id="toast-region" aria-live="polite"></div>';
  resetToasts();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('toastQueue 策略', () => {
  it('时长：error 6s，其余 3.2s', () => {
    expect(durationFor('error')).toBe(6000);
    expect(durationFor('success')).toBe(3200);
  });

  it('同文案去重：不新增节点，重置计时', () => {
    showToast('同步失败', 'error');
    showToast('同步失败', 'error');
    expect(region().children).toHaveLength(1);
    vi.advanceTimersByTime(5999);
    expect(region().children).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(region().children).toHaveLength(0);
  });

  it('不同 tone 同文案不去重', () => {
    showToast('已保存', 'success');
    showToast('已保存', 'error');
    expect(region().children).toHaveLength(2);
    expect(toastKey('error', '已保存')).not.toBe(toastKey('success', '已保存'));
  });

  it('上限 3：超出先淘最旧', () => {
    showToast('一'); showToast('二'); showToast('三'); showToast('四');
    vi.advanceTimersByTime(130);
    expect(region().children).toHaveLength(TOAST_CAP);
    expect(region().textContent).toContain('四');
    expect(region().textContent).not.toContain('一');
  });

  it('点击整条关闭', () => {
    showToast('可关闭');
    region().firstElementChild!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    vi.advanceTimersByTime(130);
    expect(region().children).toHaveLength(0);
  });

  it('悬停暂停、移出后重新计时', () => {
    showToast('暂停我');
    const node = region().firstElementChild as HTMLElement;
    node.dispatchEvent(new MouseEvent('mouseenter'));
    vi.advanceTimersByTime(10000);
    expect(region().children).toHaveLength(1);
    node.dispatchEvent(new MouseEvent('mouseleave'));
    vi.advanceTimersByTime(3200);
    expect(region().children).toHaveLength(0);
  });

  it('关闭按钮带中文 aria-label，且 renderIcons 被调用', () => {
    const renderIcons = vi.fn();
    showToast('带图标', 'success', { renderIcons });
    const close = region().querySelector('.toast-close') as HTMLElement;
    expect(close.getAttribute('aria-label')).toBe('关闭提示');
    expect(renderIcons).toHaveBeenCalled();
  });
});
```

Run: `npx vitest run tests/frontend/toastQueue.test.ts`
Expected: FAIL — `Failed to resolve import "@/modules/toastQueue"`

- [ ] **Step 2: 实现模块**

```ts
// frontend/src/modules/toastQueue.ts
/** Toast 队列策略：同文案去重、堆叠上限、可关闭、悬停暂停、按 tone 分时长。 */
export const TOAST_CAP = 3;
const DURATION_MS: Record<string, number> = { error: 6000 };
const DEFAULT_DURATION_MS = 3200;
const LEAVE_MS = 120;

export function durationFor(tone: string): number {
  return DURATION_MS[tone] ?? DEFAULT_DURATION_MS;
}

export function toastKey(tone: string, message: string): string {
  return `${tone}\u0000${message}`;
}

interface Entry {
  key: string;
  el: HTMLElement;
  timer: ReturnType<typeof setTimeout> | null;
  tone: string;
}

const entries: Entry[] = [];

function region(): HTMLElement | null {
  return document.getElementById('toast-region');
}

function remove(entry: Entry): void {
  const index = entries.indexOf(entry);
  if (index !== -1) entries.splice(index, 1);
  if (entry.timer) clearTimeout(entry.timer);
  entry.el.classList.add('toast-leaving');
  setTimeout(() => entry.el.remove(), LEAVE_MS);
}

function arm(entry: Entry): void {
  if (entry.timer) clearTimeout(entry.timer);
  entry.timer = setTimeout(() => remove(entry), durationFor(entry.tone));
}

export function showToast(
  message: string,
  tone = 'success',
  deps: { renderIcons?: () => void } = {}
): void {
  const host = region();
  if (!host) return;
  const text = String(message ?? '');
  const key = toastKey(tone, text);

  const existing = entries.find((entry) => entry.key === key);
  if (existing) {
    existing.el.classList.remove('toast-pulse');
    void existing.el.offsetWidth; // 触发重排以便重放高亮动画
    existing.el.classList.add('toast-pulse');
    arm(existing);
    return;
  }

  const el = document.createElement('div');
  el.className = tone === 'error' ? 'toast error' : 'toast';
  const icon = document.createElement('i');
  icon.setAttribute('data-lucide', tone === 'error' ? 'triangle-alert' : 'check-circle-2');
  icon.setAttribute('aria-hidden', 'true');
  const span = document.createElement('span');
  span.textContent = text;
  const close = document.createElement('button');
  close.className = 'toast-close';
  close.type = 'button';
  close.setAttribute('aria-label', '关闭提示');
  const closeIcon = document.createElement('i');
  closeIcon.setAttribute('data-lucide', 'x');
  closeIcon.setAttribute('aria-hidden', 'true');
  close.appendChild(closeIcon);
  el.append(icon, span, close);
  host.appendChild(el);

  const entry: Entry = { key, el, timer: null, tone };
  entries.push(entry);
  el.addEventListener('click', () => remove(entry));
  el.addEventListener('mouseenter', () => {
    if (entry.timer) clearTimeout(entry.timer);
    entry.timer = null;
  });
  el.addEventListener('focusin', () => {
    if (entry.timer) clearTimeout(entry.timer);
    entry.timer = null;
  });
  el.addEventListener('mouseleave', () => arm(entry));
  el.addEventListener('focusout', () => arm(entry));
  deps.renderIcons?.();
  arm(entry);

  while (entries.length > TOAST_CAP) remove(entries[0]);
}

export function resetToasts(): void {
  entries.splice(0).forEach((entry) => {
    if (entry.timer) clearTimeout(entry.timer);
    entry.el.remove();
  });
}
```

注意：`toast-close` 的 `click` 会冒泡到整条 toast 的 click（同样 `remove`）——`remove` 对已移除条目幂等（`indexOf === -1` 仍会重排一次动画定时器，无害）。

- [ ] **Step 3: store 委托 + aria-atomic + CSS**

`useWorkspaceStore.ts:73-91` 整体替换：

```ts
  function showToast(message: string, tone = 'success') {
    showToastEntry(message, tone, { renderIcons });
  }
```

并在文件顶部 `import { showToast as showToastEntry } from '@/modules/toastQueue';`（`renderIcons` 已是同 store 函数，保持后调；`createIcons`/`UI_ICONS` 导入不动）。

`App.vue:279`：

```html
  <div class="toast-region" id="toast-region" aria-live="polite"></div>
```

`styles.css`（`:2779` 之后追加）：

```css
.toast {
  cursor: pointer;
}

.toast-close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-left: auto;
  padding: 0;
  border: 0;
  background: transparent;
  color: var(--muted);
  cursor: pointer;
}

.toast-close svg {
  width: 14px;
  height: 14px;
  color: inherit;
}

.toast-pulse {
  animation: toast-pulse 200ms ease;
}

.toast-leaving {
  opacity: 0;
  transition: opacity 120ms ease;
}

@keyframes toast-pulse {
  from {
    border-color: var(--line-strong);
  }
  to {
    border-color: var(--line);
  }
}
```

- [ ] **Step 4: 回归 + 门禁 + 提交**

Run: `npx vitest run tests/frontend/toastQueue.test.ts` → PASS；`npx vitest run` 全绿（既有 toast spy 断言必须仍然通过）；`npx vue-tsc --noEmit` 0 error

```bash
git add frontend/src/modules/toastQueue.ts frontend/src/stores/useWorkspaceStore.ts frontend/src/styles.css frontend/src/App.vue tests/frontend/toastQueue.test.ts
git commit -m "feat: Toast 去重/上限/可关闭/暂停/分时长策略"
```

---

### Task 9: 快捷键模块 + `app.ts` 派发器 + 抑制规则

**Files:**
- Create: `frontend/src/modules/shortcuts.ts`
- Modify: `frontend/src/app.ts`（`:88-102`）
- Modify: `frontend/src/App.vue`（导航项/抽屉项 `aria-keyshortcuts`、搜索框）
- Test: `tests/frontend/shortcuts.test.ts`（新建）、`tests/frontend/AppShell.test.ts`（追加）

**Interfaces:**
- Consumes: Task 1 的 `isAnyOverlayOpen()`
- Produces:
  - `VIEW_SHORTCUTS: Record<string, string>`（`'1'..'7'`）
  - `shortcutForView(viewId: string): string | null`
  - `helpOpen: Ref<boolean>`、`toggleHelp(): void`
  - `isTypingTarget(target: EventTarget | null): boolean`
  - `shortcutFor(event: KeyboardEvent, ctx: { overlayOpen: boolean; helpOpen: boolean }): ShortcutAction | null`，其中 `ShortcutAction = { type: 'view'; view: string } | { type: 'search' } | { type: 'toggle-help' }`

- [ ] **Step 1: 写失败测试**

```ts
// tests/frontend/shortcuts.test.ts
import { describe, expect, it } from 'vitest';
import { shortcutFor, shortcutForView, isTypingTarget, helpOpen, toggleHelp } from '@/modules/shortcuts';

function key(k: string, init: KeyboardEventInit = {}) {
  return new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...init });
}
const ctx = { overlayOpen: false, helpOpen: false };

describe('shortcuts 键表与抑制', () => {
  it('数字键映射 7 个视图（顺序同 NAV_ITEMS）', () => {
    expect(shortcutFor(key('7'), ctx)).toEqual({ type: 'view', view: 'settings' });
    expect(shortcutFor(key('1'), ctx)).toEqual({ type: 'view', view: 'overview' });
    expect(shortcutFor(key('0'), ctx)).toBeNull();
    expect(shortcutForView('portfolio')).toBe('6');
    expect(shortcutForView('stock-detail')).toBeNull();
  });

  it('斜杠聚焦搜索、问号切帮助；Esc 不在此处理', () => {
    expect(shortcutFor(key('/'), ctx)).toEqual({ type: 'search' });
    expect(shortcutFor(key('?'), ctx)).toEqual({ type: 'toggle-help' });
    expect(shortcutFor(key('？'), ctx)).toEqual({ type: 'toggle-help' });
    expect(shortcutFor(key('Escape'), ctx)).toBeNull();
  });

  it('抑制矩阵：输入控件内不触发', () => {
    for (const node of [document.createElement('input'), document.createElement('select'), document.createElement('div')]) {
      if (node.tagName === 'DIV') node.contentEditable = 'true';
      document.body.appendChild(node);
      expect(isTypingTarget(node)).toBe(true);
      const event = key('2');
      node.dispatchEvent(event);
      expect(event.target).toBe(node);
      expect(shortcutFor(event, ctx)).toBeNull();
      node.remove();
    }
    expect(isTypingTarget(document.body)).toBe(false);
  });

  it('抑制矩阵：修饰键 / 输入法组合中 / 浮层打开', () => {
    expect(shortcutFor(key('2', { ctrlKey: true }), ctx)).toBeNull();
    const composing = key('2');
    Object.defineProperty(composing, 'isComposing', { value: true });
    expect(shortcutFor(composing, ctx)).toBeNull();
    expect(shortcutFor(key('2'), { overlayOpen: true, helpOpen: false })).toBeNull();
    expect(shortcutFor(key('/'), { overlayOpen: true, helpOpen: false })).toBeNull();
  });

  it('帮助浮层打开时问号关闭它，其它键仍被浮层抑制', () => {
    expect(shortcutFor(key('?'), { overlayOpen: true, helpOpen: true })).toEqual({ type: 'toggle-help' });
    expect(shortcutFor(key('3'), { overlayOpen: true, helpOpen: true })).toBeNull();
  });

  it('toggleHelp 翻转 helpOpen', () => {
    const before = helpOpen.value;
    toggleHelp();
    expect(helpOpen.value).toBe(!before);
  });
});
```

（`isTypingTarget` 的入参是事件 target：上面直接派发到控件上让 `event.target` 就是该控件。）

Run: `npx vitest run tests/frontend/shortcuts.test.ts`
Expected: FAIL — `Failed to resolve import "@/modules/shortcuts"`

- [ ] **Step 2: 实现模块**

```ts
// frontend/src/modules/shortcuts.ts
import { ref } from 'vue';

/** 数字键 → 视图。顺序与 NAV_ITEMS 一致；'7' 是 ③b 新增（个人中心）。 */
export const VIEW_SHORTCUTS: Record<string, string> = {
  '1': 'overview',
  '2': 'screener',
  '3': 'grid',
  '4': 'plans',
  '5': 'monitor',
  '6': 'portfolio',
  '7': 'settings',
};

export function shortcutForView(viewId: string): string | null {
  const hit = Object.entries(VIEW_SHORTCUTS).find(([, view]) => view === viewId);
  return hit ? hit[0] : null;
}

/** 帮助浮层开关：模块级状态（先例：modules/theme.ts）。 */
export const helpOpen = ref(false);

export function toggleHelp(): void {
  helpOpen.value = !helpOpen.value;
}

export type ShortcutAction = { type: 'view'; view: string } | { type: 'search' } | { type: 'toggle-help' };

export interface ShortcutContext {
  overlayOpen: boolean;
  helpOpen: boolean;
}

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

export function shortcutFor(event: KeyboardEvent, ctx: ShortcutContext): ShortcutAction | null {
  if (event.ctrlKey || event.metaKey || event.altKey) return null;
  if (event.isComposing) return null;
  if (isTypingTarget(event.target)) return null;

  if (event.key === '?' || event.key === '？') {
    if (ctx.overlayOpen && !ctx.helpOpen) return null;
    return { type: 'toggle-help' };
  }
  if (ctx.overlayOpen) return null; // 浮层打开时其余键不穿透（Esc 由浮层栈独占处理）

  if (event.key === '/') return { type: 'search' };
  const view = VIEW_SHORTCUTS[event.key];
  return view ? { type: 'view', view } : null;
}
```

- [ ] **Step 3: app.ts 重构为派发器**

`frontend/src/app.ts` 顶部补：

```ts
import { helpOpen, shortcutFor, toggleHelp } from '@/modules/shortcuts';
import { isAnyOverlayOpen } from '@/modules/overlayA11y';
```

`:88-102` 的监听整体替换（并在 `onBeforeUnmount` 里移除）：

```ts
      const onShortcutKeydown = (event: KeyboardEvent) => {
        const action = shortcutFor(event, { overlayOpen: isAnyOverlayOpen(), helpOpen: helpOpen.value });
        if (!action) return;
        if (action.type === 'view') {
          quotes.switchView(action.view);
          return;
        }
        if (action.type === 'search') {
          event.preventDefault();
          (document.querySelector('.global-search input') as HTMLInputElement | null)?.focus();
          return;
        }
        event.preventDefault();
        toggleHelp();
      };
      document.addEventListener('keydown', onShortcutKeydown);
      keydownDisposer = () => document.removeEventListener('keydown', onShortcutKeydown);
```

`setup()` 作用域顶部声明 `let keydownDisposer: (() => void) | null = null;`，`onBeforeUnmount` 内追加：

```ts
      keydownDisposer?.();
      keydownDisposer = null;
```

- [ ] **Step 4: `aria-keyshortcuts` 接线 + AppShell 契约用例**

`App.vue` 导航项按钮（`:24-32` 的 `<button class="nav-item" ...>`）与抽屉项（`:263-269`）各加：

```html
            :aria-keyshortcuts="shortcutForView(item.id) || undefined"
```

搜索输入框加 `aria-keyshortcuts="/"`。`<script setup>` 补 `import { shortcutForView } from '@/modules/shortcuts';`。

```ts
// tests/frontend/AppShell.test.ts（追加）
it('导航项声明数字键快捷键（含 7 → 个人中心）', () => {
  const wrapper = mount(App, { global: viewStubs });
  const items = wrapper.findAll('.sidebar .nav-item');
  expect(items.map((node) => node.attributes('aria-keyshortcuts'))).toEqual(['1', '2', '3', '4', '5', '6', '7']);
  wrapper.unmount();
});
```

Run: `npx vitest run tests/frontend/shortcuts.test.ts tests/frontend/AppShell.test.ts` → PASS；`npx vitest run` 全绿；`npx vue-tsc --noEmit` 0 error

- [ ] **Step 5: 提交**

```bash
git add frontend/src/modules/shortcuts.ts frontend/src/app.ts frontend/src/App.vue tests/frontend/shortcuts.test.ts tests/frontend/AppShell.test.ts
git commit -m "feat: 快捷键补齐 1-7 与统一抑制规则并重构为键位派发"
```

---

### Task 10: 快捷键帮助浮层 + 顶栏 `?` 入口

**Files:**
- Create: `frontend/src/components/ShortcutHelpDialog.vue`
- Modify: `frontend/src/App.vue`（顶栏 `?` 按钮 + 挂载组件）
- Test: `tests/frontend/ShortcutHelpDialog.test.ts`（新建）

**Interfaces:**
- Consumes: Task 1 的 `useOverlayA11y`；Task 9 的 `helpOpen`/`toggleHelp`/`VIEW_SHORTCUTS`/`shortcutForView`
- Produces: `ShortcutHelpDialog.vue`（读模块级 `helpOpen`，关闭写回 `false`）

- [ ] **Step 1: 写失败测试**

```ts
// tests/frontend/ShortcutHelpDialog.test.ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));

import ShortcutHelpDialog from '@/components/ShortcutHelpDialog.vue';
import { helpOpen } from '@/modules/shortcuts';
import { resetOverlayStack } from '@/modules/overlayA11y';

beforeEach(() => {
  setActivePinia(createPinia());
  resetOverlayStack();
  document.body.innerHTML = '';
  helpOpen.value = true;
});

describe('快捷键帮助浮层（spec §9.3）', () => {
  it('列出全部键位并声明 dialog 语义', () => {
    const wrapper = mount(ShortcutHelpDialog, { attachTo: document.body });
    const panel = wrapper.find('.dialog-panel');
    expect(panel.attributes('role')).toBe('dialog');
    expect(panel.attributes('aria-modal')).toBe('true');
    expect(panel.attributes('aria-label')).toBe('键盘快捷键');
    for (const text of ['聚焦搜索', '打开 / 关闭帮助', '切换到个人中心']) {
      expect(panel.text()).toContain(text);
    }
    wrapper.unmount();
    helpOpen.value = false;
  });

  it('Esc 关闭（写回 helpOpen=false）', async () => {
    const wrapper = mount(ShortcutHelpDialog, { attachTo: document.body });
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await flushPromises();
    expect(helpOpen.value).toBe(false);
    wrapper.unmount();
  });

  it('关闭按钮与遮罩都能关', async () => {
    const wrapper = mount(ShortcutHelpDialog, { attachTo: document.body });
    await wrapper.find('.dialog-head .text-button').trigger('click');
    expect(helpOpen.value).toBe(false);
    helpOpen.value = true;
    await flushPromises();
    await wrapper.find('.dialog-backdrop').trigger('click.self');
    expect(helpOpen.value).toBe(false);
    wrapper.unmount();
  });
});
```

Run: `npx vitest run tests/frontend/ShortcutHelpDialog.test.ts`
Expected: FAIL — 组件不存在

- [ ] **Step 2: 实现组件**

```vue
<!-- frontend/src/components/ShortcutHelpDialog.vue -->
<template>
  <div v-if="helpOpen" class="dialog-backdrop" @click.self="close">
    <section ref="overlayPanel" class="dialog-panel shortcut-help-panel" role="dialog" aria-modal="true" aria-label="键盘快捷键">
      <header class="dialog-head">
        <h2>键盘快捷键</h2>
        <button class="text-button" type="button" @click="close">关闭</button>
      </header>
      <table class="shortcut-table">
        <tbody>
          <tr v-for="row in rows" :key="row.keys">
            <th scope="row"><kbd>{{ row.keys }}</kbd></th>
            <td>{{ row.label }}</td>
          </tr>
        </tbody>
      </table>
      <p class="heading-note">数字键为桌面快捷键；手机端可用顶部「?」按钮随时查看本表。</p>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue';
import { useOverlayA11y } from '@/modules/overlayA11y';
import { VIEW_SHORTCUTS, helpOpen } from '@/modules/shortcuts';
import { NAV_ITEMS } from '@/modules/constants';

const overlayPanel = ref<HTMLElement | null>(null);
const rows = computed(() => [
  { keys: '/', label: '聚焦搜索' },
  ...Object.entries(VIEW_SHORTCUTS).map(([digit, view]) => ({
    keys: digit,
    label: `切换到${NAV_ITEMS.find((item) => item.id === view)?.label ?? view}`,
  })),
  { keys: '?', label: '打开 / 关闭帮助' },
  { keys: 'Esc', label: '关闭当前浮层' },
]);

function close(): void {
  helpOpen.value = false;
}

useOverlayA11y({ id: 'shortcut-help', isOpen: () => helpOpen.value, panelRef: overlayPanel, onClose: close });
</script>
```

`styles.css` 追加（放在 `.dialog-panel` 族附近）：

```css
.shortcut-help-panel .shortcut-table {
  width: 100%;
  border-collapse: collapse;
}

.shortcut-table th {
  width: 84px;
  padding: var(--space-2) var(--space-3) var(--space-2) 0;
  text-align: left;
  vertical-align: top;
}

.shortcut-table td {
  padding: var(--space-2) 0;
  color: var(--ink-soft);
  font-size: var(--fs-sm);
}
```

- [ ] **Step 3: App.vue 接入入口**

顶栏 `.topbar-actions` 内、`.global-search` 之后：

```html
          <button
            class="icon-button"
            type="button"
            aria-label="键盘快捷键"
            aria-keyshortcuts="?"
            data-tooltip="键盘快捷键"
            @click="toggleHelp"
          >
            <i data-lucide="circle-question-mark" aria-hidden="true"></i>
          </button>
```

模板末尾（`.more-sheet-backdrop` 之后、`.toast-region` 之前）挂载：

```html
  <ShortcutHelpDialog />
```

`<script setup>`：`import ShortcutHelpDialog from '@/components/ShortcutHelpDialog.vue';`、`import { toggleHelp } from '@/modules/shortcuts';`；并在 `openMoreSheet` 同侧确保新图标已注册（`modules/lucideIcons.ts` 的 `UI_ICONS` 加入 `CircleQuestionMark` 与 `X`，导入名照 lucide 命名 `CircleQuestionMark`/`X`）。

顶栏入口的 DOM 契约（`tests/frontend/AppShell.test.ts` 追加；`App.vue` 需 `import { helpOpen } from '@/modules/shortcuts'` 供断言）：

```ts
it('顶栏唯一致的一个「键盘快捷键」入口，点击打开帮助浮层', async () => {
  const wrapper = mount(App, { global: viewStubs, attachTo: document.body });
  const help = wrapper.findAll('.topbar-actions button').find((node) => node.attributes('aria-label') === '键盘快捷键');
  expect(help).toBeTruthy();
  expect(help!.attributes('aria-keyshortcuts')).toBe('?');
  await help!.trigger('click');
  await flushPromises();
  expect(wrapper.find('.shortcut-help-panel').exists()).toBe(true);
  helpOpen.value = false;
  wrapper.unmount();
});
```

- [ ] **Step 4: 图标注册守卫 + 门禁 + 提交**

`tests/frontend/lucideIcons.test.ts` 的模板扫描用例会自动覆盖新模板（若模板用到未注册图标即失败）。

Run: `npx vitest run tests/frontend/ShortcutHelpDialog.test.ts tests/frontend/lucideIcons.test.ts tests/frontend/AppShell.test.ts` → PASS；全量 vitest + `npx vue-tsc --noEmit` 全绿

```bash
git add frontend/src/components/ShortcutHelpDialog.vue frontend/src/App.vue frontend/src/modules/lucideIcons.ts frontend/src/styles.css tests/frontend/ShortcutHelpDialog.test.ts
git commit -m "feat: 新增快捷键帮助浮层与顶栏入口"
```

---

### Task 11: ≤1060 图标条主题开关文案

**Files:**
- Modify: `frontend/src/styles.css`（`@media (max-width: 1060px)` 块，`:2841-2892`）
- Test: 无单测（jsdom 不跑媒体查询）；由 Task 13 真实浏览器验收

**Interfaces:**
- Consumes: 无
- Produces: 82px 图标条里主题开关只剩居中图标

- [ ] **Step 1: 改 CSS**

在 `@media (max-width: 1060px)` 的既有隐藏列表里加入主题开关文案，并让按钮居中：

```css
  .brand-copy,
  .nav-item span,
  .nav-item kbd,
  .sidebar-section-label,
  .sidebar-theme-toggle span {
    display: none;
  }

  .sidebar-theme-toggle {
    justify-content: center;
    padding: var(--space-2) 0;
  }
```

- [ ] **Step 2: 机械核对**

Run: `Select-String -Path frontend/src/styles.css -Pattern 'sidebar-theme-toggle span' -Context 3,3`
Expected: 命中位置位于 `@media (max-width: 1060px)` 块内（前后可看到 `.nav-item kbd`）

- [ ] **Step 3: 门禁 + 提交**

Run: `npx vitest run` 全绿（CSS 改动不影响断言）；`npx vue-tsc --noEmit` 0 error

```bash
git add frontend/src/styles.css
git commit -m "fix: 1060px 图标条隐藏主题开关文案并居中图标"
```

---

### Task 12: 5 处下钻控件逐行可访问名

**Files:**
- Modify: `frontend/src/modules/format.ts`（新增 `viewDetailLabel`）
- Modify: `frontend/src/App.vue:157-165`、`frontend/src/views/ViewSettings.vue:75-83`、`frontend/src/views/ViewPlans.vue:138-145`、`frontend/src/views/ViewPlans.vue:304-312`、`frontend/src/views/ViewPortfolio.vue:249-257`
- Test: `tests/frontend/format.test.ts`、`tests/frontend/ViewPlans.test.ts`、`tests/frontend/ViewPortfolio.test.ts`、`tests/frontend/ViewSettings.test.ts`、`tests/frontend/AppShell.test.ts`

**Interfaces:**
- Consumes: `quoteFor(code)`（quotes store，已有）
- Produces: `viewDetailLabel(code: string, name?: string | null): string` → `` 查看 {name} {code} 的详情 ``（无 name 时 `查看 {code} 的详情`；代码必在，保证逐行唯一）

- [ ] **Step 1: 写失败测试**

```ts
// tests/frontend/format.test.ts（追加）
import { viewDetailLabel } from '@/modules/format';

it('viewDetailLabel：有名称带名称，无名称只用代码（spec §10.2）', () => {
  expect(viewDetailLabel('600519', '贵州茅台')).toBe('查看 贵州茅台 600519 的详情');
  expect(viewDetailLabel('600519', null)).toBe('查看 600519 的详情');
  expect(viewDetailLabel('600519', '')).toBe('查看 600519 的详情');
});
```

```ts
// tests/frontend/ViewPlans.test.ts（追加）
it('计划行与复盘行下钻控件带逐行可访问名', async () => {
  const wrapper = mount(ViewPlans);
  await flushPromises();
  const link = wrapper.find('[data-testid="plan-code-link"]');
  expect(link.attributes('aria-label')).toMatch(/^查看 .*600519 的详情$/);
});
```

Run: `npx vitest run tests/frontend/format.test.ts tests/frontend/ViewPlans.test.ts`
Expected: FAIL — `viewDetailLabel is not a function`

- [ ] **Step 2: 实现 helper + 5 处接线**

`frontend/src/modules/format.ts` 追加：

```ts
/** 下钻控件的逐行可访问名：代码必在（保证唯一），有名称时带上名称。 */
export function viewDetailLabel(code: string, name?: string | null): string {
  return name ? `查看 ${name} ${code} 的详情` : `查看 ${code} 的详情`;
}
```

接线（5 处，均**不新增任何请求**）：

| 文件:行 | 绑定 |
|---|---|
| `App.vue:157-165` | `:aria-label="viewDetailLabel(alert.code, null)"`（导入 `viewDetailLabel`；提醒行的 `title` 是事件标题而非股票名，故只用代码，代码已保证逐行唯一） |
| `ViewSettings.vue:75-83` | `:aria-label="viewDetailLabel(alert.code, null)"` |
| `ViewPlans.vue:138-145` | `:aria-label="viewDetailLabel(plan.code, quoteFor(plan.code)?.name)"` |
| `ViewPlans.vue:304-312` | `:aria-label="viewDetailLabel(item.code, quoteFor(item.code)?.name)"` |
| `ViewPortfolio.vue:249-257` | `:aria-label="viewDetailLabel(pair.buy.code, quoteFor(pair.buy.code)?.name)"` |

各文件按需补 `import { viewDetailLabel } from '@/modules/format';`。

- [ ] **Step 3: 各视图断言 + 门禁 + 提交**

在 `ViewPortfolio.test.ts`/`ViewSettings.test.ts`/`AppShell.test.ts` 各补一条：

```ts
expect(wrapper.find('[data-testid="pair-code-link"]').attributes('aria-label')).toBe('查看 600519 的详情');
```

Run: `npx vitest run` 全绿；`npx vue-tsc --noEmit` 0 error

```bash
git add frontend/src/modules/format.ts frontend/src/App.vue frontend/src/views/ViewSettings.vue frontend/src/views/ViewPlans.vue frontend/src/views/ViewPortfolio.vue tests/frontend/format.test.ts tests/frontend/ViewPlans.test.ts tests/frontend/ViewPortfolio.test.ts tests/frontend/ViewSettings.test.ts tests/frontend/AppShell.test.ts
git commit -m "feat: 下钻控件补逐行可访问名"
```

---

### Task 13: 真实浏览器验收 + 机械断言 + 文档收口

**Files:**
- Create: `.superpowers/sdd/2026-10-17-ui-interaction-consistency/visual/`（截图 + `report.json`，gitignored 证据）
- Scripts（**仓库外**，避免 ESLint 全仓扫到）：`C:\Users\xiaoning\AppData\Local\Temp\opencode\atlas-interaction-consistency-visual\visual-check.mjs`
- Modify: `docs/superpowers/plans/2026-10-17-ui-interaction-consistency.md`（勾选复选框 + 执行期裁定）
- Modify: `.superpowers/sdd/2026-10-17-ui-interaction-consistency/progress.md`（账本）

**Interfaces:**
- Consumes: 全部前置任务
- Produces: 验收证据 + 最终状态交接清单

- [ ] **Step 1: 真实浏览器探针**

以 `npm run dev`（Vite 5173 + FastAPI 4173，真后端）为前置，用 Playwright 真 chromium 脚本逐项断言并截图（1440 / 1060 / 900 / 680 四档）：

```js
// 关键断言（脚本内逐条 assert + 截图，写法照 ③a 的 visual-check.mjs）
// 1) Esc 关 4 个浮层：PlanDraft（选股器/计划页「制定计划」）→ notif → more-sheet → help
// 2) Tab 循环：面板内连续 12 次 Tab，activeElement 始终在 .dialog-panel 内
// 3) 滚动锁：浮层打开时 document.querySelector('.view-panel.is-active').scrollTop 不变，
//    且 getComputedStyle(...).overflow === 'hidden'；关闭后恢复 'auto'
// 4) Toast：同一 error 连点 3 次 → region 只 1 条；再触发 3 条不同文案 → 上限 3 条且最旧被淘
// 5) 快捷键：按 1..7 依次切视图（比对 h1 文案）；SELECT 内按 2 不切；notif 打开时按 2 不切；
//    按 ? 打开帮助浮层再按 ? 关闭
// 6) ≤1060：.sidebar-theme-toggle span 的 computed display === 'none'
```

- [ ] **Step 2: 9 条机械断言**

```bash
# 1 加载态不再用空态类
npx rg -n 'class="empty-state' frontend/src --glob '*.vue' -A2 | rg loader-circle   # 期望 0 命中
# 2 浮层接线数
npx rg -c 'useOverlayA11y\(' frontend/src                                            # 期望 5
# 3 aria-modal 数
npx rg -c 'aria-modal="true"' frontend/src --glob '*.vue'                            # 期望 5
# 4 Esc 只在浮层模块
npx rg -n "'Escape'" frontend/src                                                     # 期望仅 overlayA11y.ts
# 5 aria-keyshortcuts 覆盖
npx rg -n 'aria-keyshortcuts' frontend/src --glob '*.vue'                            # 期望 ≥10
# 6 滚动锁 CSS 规则
npx rg -n 'body\.overlay-open \.view-panel\.is-active' frontend/src/styles.css       # 期望 1
# 7 ViewGrid 空态数不变
npx rg -c 'class="empty-state"' frontend/src/views/ViewGrid.vue                       # 期望 4
# 8 策略/键表集中
npx rg -n 'TOAST_CAP|VIEW_SHORTCUTS' frontend/src --glob '!*/modules/*'               # 期望 0 命中
# 9 非目标守卫
npx rg -n 'skeleton|inert' frontend/src                                              # 期望 0 命中
```

- [ ] **Step 3: 全量门禁**

Run: `npm run verify`
Expected: vitest 全绿（原 309 项 + 新增用例）、`vue-tsc --noEmit` 0 error、pytest 679 通过、覆盖率 ≥80%
Run: `git diff --stat develop...HEAD -- backend/ tests/`
Expected: 空（后端零改动；`tests/` 指后端测试目录）

- [ ] **Step 4: 文档收口**

- 计划文档：勾选全部复选框，追加「执行期裁定」节（记录每条偏离与理由）。
- 账本 `.superpowers/sdd/2026-10-17-ui-interaction-consistency/progress.md`：记录每个任务的复核结论、延后 minor、最终状态与 ③ 批次收口清单。
- 若验收发现用户可见行为变更超出 spec，回到 spec 补记（不悄悄改行为）。

- [ ] **Step 5: 提交**

```bash
git add docs/superpowers/plans/2026-10-17-ui-interaction-consistency.md
git commit -m "docs: 勾选第③b批计划步骤并补记执行期裁定与最终状态"
```

---

## 任务依赖与顺序

```
Task 1 ──┬─→ Task 2（浮层接线）
         └─→ Task 10（帮助浮层）
Task 3 ──┬─→ Task 4 / 5 / 6 / 7（各视图加载态与空态动作，彼此独立，可并行）
Task 8（Toast，独立）
Task 9 ──→ Task 10
Task 11 / 12（独立）
Task 13（所有任务完成后）
```

并行安全边界：Task 4/5/6/7/11/12 触碰的文件互不重叠（各自视图 + 各自测试文件；Task 12 额外碰 `format.ts` 与 `App.vue`，需与 Task 9/10 的 `App.vue` 改动串行）。
