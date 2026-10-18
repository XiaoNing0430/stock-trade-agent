import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick, ref } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import { createShortcutHandler, appOptions, type ShortcutHandlerDeps } from '@/app';
import { NAV_ITEMS } from '@/modules/constants';
import { VIEW_SHORTCUTS, helpOpen } from '@/modules/shortcuts';
import { isAnyOverlayOpen, resetOverlayStack, useOverlayA11y } from '@/modules/overlayA11y';

/**
 * 派发器（app.ts）的端到端用例：真实 createShortcutHandler + 真实 shortcutFor，
 * 只把副作用（switchView / toggleHelp）与浮层状态换成可控输入。
 * AppShell.test.ts 把 @/app 整体 mock 掉了，此处是派发逻辑唯一的仓内覆盖。
 *
 * store 模块整体换成可控桩，使 unmount-mid-init 泄漏守护可直接驱动：app.ts 只读取
 * 少量字段与 onMounted 链上的方法，桩足以让链走完并把监听器真的挂上/摘掉。
 */
const stores = vi.hoisted(() => ({
  workspace: {} as Record<string, any>,
  quotes: {} as Record<string, any>,
  screener: {} as Record<string, any>,
  plans: {} as Record<string, any>,
  settings: {} as Record<string, any>,
  grid: {} as Record<string, any>,
  strategy: {} as Record<string, any>,
}));

vi.mock('@/stores/useWorkspaceStore', () => ({ useWorkspaceStore: () => stores.workspace }));
vi.mock('@/stores/useQuotesStore', () => ({ useQuotesStore: () => stores.quotes }));
vi.mock('@/stores/useScreenerStore', () => ({ useScreenerStore: () => stores.screener }));
vi.mock('@/stores/usePlansStore', () => ({ usePlansStore: () => stores.plans }));
vi.mock('@/stores/useSettingsStore', () => ({ useSettingsStore: () => stores.settings }));
vi.mock('@/stores/useGridStore', () => ({ useGridStore: () => stores.grid }));
vi.mock('@/stores/useStrategyStore', () => ({ useStrategyStore: () => stores.strategy }));

/** 每例重建桩方法与 spy，避免调用计数跨例泄漏。 */
function resetStores(): void {
  Object.assign(stores.workspace, {
    draftWatchSuppressed: false,
    draftDirty: false,
    monitorEnabled: false,
    refreshTimer: null,
    workspaceSyncTimer: null,
    loadWorkspace: vi.fn(async () => {}),
    refreshAll: vi.fn(async () => {}),
    renderIcons: vi.fn(),
    armRefreshTimer: vi.fn(),
    persist: vi.fn(),
    showToast: vi.fn(),
  });
  Object.assign(stores.quotes, { view: 'overview', switchView: vi.fn() });
  Object.assign(stores.screener, { filters: { exchange: '', market: '' }, loading: false, scanNow: vi.fn() });
  Object.assign(stores.plans, { draft: { code: '' }, hydrateDraft: vi.fn() });
  Object.assign(stores.settings, { loadSettings: vi.fn(async () => {}) });
  Object.assign(stores.grid, {
    gridDraft: { code: '' },
    gridSuggestedCode: '',
    normalizedGridCode: '',
    gridSuggestion: null,
    gridResult: null,
    loadGridStrategies: vi.fn(async () => {}),
    restoreGridSuggestion: vi.fn(async () => {}),
  });
  Object.assign(stores.strategy, { loadStrategies: vi.fn(async () => {}) });
}

/** 把派发器按生产方式挂到 document 上，返回摘除函数。 */
function attach(deps: ShortcutHandlerDeps): () => void {
  const handler = createShortcutHandler(deps);
  document.addEventListener('keydown', handler);
  return () => document.removeEventListener('keydown', handler);
}

/** 在 target（默认 document）上派发可冒泡的 keydown，返回事件以检查 defaultPrevented。 */
function press(key: string, init: KeyboardEventInit = {}, target: EventTarget = document): KeyboardEvent {
  const event = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true, ...init });
  target.dispatchEvent(event);
  return event;
}

beforeEach(() => {
  helpOpen.value = false;
  document.body.innerHTML = '';
  resetOverlayStack();
  resetStores();
});

afterEach(() => {
  document.body.innerHTML = '';
  helpOpen.value = false;
  resetOverlayStack();
});

describe('快捷键派发器（createShortcutHandler）', () => {
  it('数字键 1–7 各自切到 NAV_ITEMS 顺序对应的具体视图 id', () => {
    const expected: Array<[string, string]> = [
      ['1', 'overview'],
      ['2', 'screener'],
      ['3', 'grid'],
      ['4', 'plans'],
      ['5', 'monitor'],
      ['6', 'portfolio'],
      ['7', 'settings'],
    ];
    // 交叉核对：任一未来重排 / 重编号都会先在此变红，而不是静默切错视图
    expect(NAV_ITEMS.map((item) => item.id)).toEqual(expected.map(([, view]) => view));
    expect(Object.entries(VIEW_SHORTCUTS)).toEqual(expected);

    for (const [key, viewId] of expected) {
      const switchView = vi.fn();
      const dispose = attach({ switchView });
      press(key);
      expect(switchView).toHaveBeenCalledTimes(1);
      expect(switchView).toHaveBeenCalledWith(viewId);
      dispose();
    }
  });

  it('输入控件内按键不切视图、也不吞键（input/textarea/select 直接作事件目标）', () => {
    for (const tag of ['input', 'textarea', 'select'] as const) {
      const el = document.createElement(tag);
      document.body.appendChild(el);
      const switchView = vi.fn();
      const dispose = attach({ switchView });
      const event = press('2', {}, el);
      expect(event.target).toBe(el);
      expect(switchView).not.toHaveBeenCalled();
      expect(event.defaultPrevented).toBe(false);
      dispose();
      el.remove();
    }
  });

  it('斜杠：存在 .global-search input 时聚焦输入框并 preventDefault', () => {
    const wrap = document.createElement('div');
    wrap.className = 'global-search';
    const input = document.createElement('input');
    wrap.appendChild(input);
    document.body.appendChild(wrap);
    const dispose = attach({ switchView: vi.fn() });
    const event = press('/');
    expect(document.activeElement).toBe(input);
    expect(event.defaultPrevented).toBe(true);
    dispose();
  });

  it('斜杠：无 .global-search input 时不抛错、不 preventDefault（本轮刻意改变的契约）', () => {
    const dispose = attach({ switchView: vi.fn() });
    const event = press('/');
    expect(event.defaultPrevented).toBe(false);
    dispose();
  });

  it('问号：默认接线翻转模块 helpOpen 并 preventDefault', () => {
    const dispose = attach({ switchView: vi.fn() });
    expect(helpOpen.value).toBe(false);
    const opened = press('?');
    expect(helpOpen.value).toBe(true);
    expect(opened.defaultPrevented).toBe(true);
    press('?');
    expect(helpOpen.value).toBe(false);
    dispose();
  });

  it('浮层打开：数字键不切换、问号未开帮助时不打开；帮助已开时问号仍可关闭', () => {
    const switchView = vi.fn();
    const toggleHelp = vi.fn();
    const dispose = attach({ switchView, toggleHelp, isOverlayOpen: () => true, isHelpOpen: () => false });
    const digit = press('2');
    expect(switchView).not.toHaveBeenCalled();
    expect(digit.defaultPrevented).toBe(false);
    const question = press('?');
    expect(toggleHelp).not.toHaveBeenCalled();
    expect(question.defaultPrevented).toBe(false);
    dispose();

    // 帮助浮层自身开着：同一套抑制下 '?' 是它的关闭键（spec 的例外）
    const toggleHelpOpen = vi.fn();
    const disposeOpen = attach({
      switchView,
      toggleHelp: toggleHelpOpen,
      isOverlayOpen: () => true,
      isHelpOpen: () => true,
    });
    const closeQuestion = press('?');
    expect(toggleHelpOpen).toHaveBeenCalledTimes(1);
    expect(closeQuestion.defaultPrevented).toBe(true);
    disposeOpen();
  });

  it('修饰键抑制：ctrl / meta / alt 各自都不切视图', () => {
    for (const mod of ['ctrlKey', 'metaKey', 'altKey'] as const) {
      const switchView = vi.fn();
      const dispose = attach({ switchView });
      press('2', { [mod]: true });
      expect(switchView).not.toHaveBeenCalled();
      dispose();
    }
  });

  it('默认依赖 + 真实挂载浮层：真实 isAnyOverlayOpen() 驱动抑制', async () => {
    const OverlayHarness = defineComponent({
      props: { id: { type: String, required: true }, open: { type: Boolean, required: true } },
      setup(props) {
        const panel = ref<HTMLElement | null>(null);
        useOverlayA11y({ id: props.id, isOpen: () => props.open, panelRef: panel, onClose: () => {} });
        return () =>
          props.open ? h('section', { ref: panel, 'data-testid': `panel-${props.id}` }, [h('button', 'A')]) : null;
      },
    });
    const wrapper = mount(OverlayHarness, { props: { id: 'real', open: true }, attachTo: document.body });
    await nextTick();
    expect(isAnyOverlayOpen()).toBe(true);

    // 其余依赖留默认：isOverlayOpen → 真实浮层栈，证明 app 与 overlayA11y 的接线而非注入桩
    const switchView = vi.fn();
    const dispose = attach({ switchView });
    expect(press('2').defaultPrevented).toBe(false);
    expect(switchView).not.toHaveBeenCalled();
    dispose();

    // resetOverlayStack 不清理实例内部状态，故必须 unmount 卸载监听器与锁
    wrapper.unmount();
    resetOverlayStack();
    expect(isAnyOverlayOpen()).toBe(false);
  });
});

describe('真实 appOptions.setup 的监听器注册与注销', () => {
  /** 用真实 appOptions.setup 挂载一个最小宿主（App.vue 的做法），store 走可控桩。 */
  function mountHost() {
    const Host = defineComponent({
      setup() {
        appOptions.setup();
        return () => h('div');
      },
    });
    return mount(Host);
  }

  it('初始化链走完后按键生效；卸载后监听器被摘除', async () => {
    const wrapper = mountHost();
    await flushPromises();
    press('2');
    expect(stores.quotes.switchView).toHaveBeenCalledWith('screener');

    wrapper.unmount();
    (stores.quotes.switchView as ReturnType<typeof vi.fn>).mockClear();
    press('3');
    expect(stores.quotes.switchView).not.toHaveBeenCalled();
  });

  it('初始化链未走完即卸载：链尾仍会补摘监听器（卸载后再按键不生效）', async () => {
    // 首个 await 卡住，模拟「组件在异步初始化链中途被卸载」
    let release!: () => void;
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    stores.workspace.loadWorkspace = vi.fn(() => gate);

    const wrapper = mountHost();
    await Promise.resolve(); // 让 onMounted 进入链并停在 gate（此时尚未注册监听器）
    wrapper.unmount(); // onBeforeUnmount 此时 keydownDisposer 仍为 null

    release();
    await flushPromises(); // 链继续跑完 → 补摘守护在此生效

    press('2');
    expect(stores.quotes.switchView).not.toHaveBeenCalled();
  });
});
