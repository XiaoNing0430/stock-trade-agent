import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

// App.vue 挂载所需的最小 mock（同 useAlertsStore.test.ts 模式）：图标渲染 + 关闭全局协调副作用。
vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));
vi.mock('@/app', () => ({ appOptions: { setup: vi.fn() } }));
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return { ...actual, requestJson: vi.fn() };
});

import App from '@/App.vue';
import { helpOpen } from '@/modules/shortcuts';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import type { Alert } from '@/types/models';

// AppShell.test.ts 额外需要视图 stub（否则子视图会拉真实 store 副作用）：
const stubView = { template: '<div />' };
const viewStubs = {
  components: {
    'view-overview': stubView,
    'view-screener': stubView,
    'view-stock-detail': stubView,
    'view-grid': stubView,
    'view-plans': stubView,
    'view-monitor': stubView,
    'view-portfolio': stubView,
    'view-settings': stubView,
  },
};

beforeEach(() => {
  localStorage.clear();
  setActivePinia(createPinia());
  // 模块级 helpOpen 在同一测试文件内共享：用例中途失败不得把开着的帮助浮层漏给后续用例
  helpOpen.value = false;
});

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

  it('导航项声明数字键快捷键（含 7 → 个人中心）', () => {
    const wrapper = mount(App, { global: viewStubs });
    const items = wrapper.findAll('.sidebar .nav-item');
    expect(items.map((node) => node.attributes('aria-keyshortcuts'))).toEqual(['1', '2', '3', '4', '5', '6', '7']);
    wrapper.unmount();
  });
});

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
    const sidebarSettings = wrapper.findAll('.sidebar .nav-item').find((node) => node.text().includes('个人中心'));
    expect(sidebarSettings!.find('.nav-count').text()).toBe('1');
    await more.trigger('click');
    const settingsRow = wrapper.findAll('.more-sheet-item')[2];
    expect(settingsRow.find('.nav-count').text()).toBe('1');
    wrapper.unmount();
  });
});

describe('标题唯一化（spec §8）', () => {
  it('顶栏无英文 eyebrow，视图区无 section-kicker 残留类', () => {
    const wrapper = mount(App, { global: viewStubs });
    expect(wrapper.find('.topbar-eyebrow').exists()).toBe(false);
    expect(wrapper.find('.section-kicker').exists()).toBe(false);
    wrapper.unmount();
  });
});

describe('顶栏行情状态控件与页脚（spec §6/§7）', () => {
  it('顶栏唯一状态控件暴露 data-state，页脚去重复行情源，侧栏渲染版本号', () => {
    const wrapper = mount(App, { global: viewStubs });
    // 行情状态收归顶栏单控件：全局恰好一个，且 data-state 是 store 的真实态
    const controls = wrapper.findAll('[data-testid="market-status-control"]');
    expect(controls).toHaveLength(1);
    const state = controls[0].attributes('data-state');
    expect(state).toBe(useQuotesStore().dataState);
    expect(['connecting', 'live', 'stale', 'error']).toContain(state);
    // 假数据徽标已删除
    expect(wrapper.find('.demo-badge').exists()).toBe(false);
    // 页脚只留免责声明，行情源行已迁入顶栏控件
    const footer = wrapper.find('.app-footer');
    expect(footer.text()).toContain('研究工具不构成投资建议');
    expect(footer.text()).not.toContain('行情接口');
    // 侧栏版本号真实文案
    expect(wrapper.find('.sidebar-version').text()).toBe('v0.7.1');
    wrapper.unmount();
  });
});

describe('快捷键帮助浮层入口（spec §9.3）', () => {
  it('顶栏唯一致的一个「键盘快捷键」入口，点击打开帮助浮层', async () => {
    const wrapper = mount(App, { global: viewStubs, attachTo: document.body });
    const help = wrapper
      .findAll('.topbar-actions button')
      .find((node) => node.attributes('aria-label') === '键盘快捷键');
    expect(help).toBeTruthy();
    expect(help!.attributes('aria-keyshortcuts')).toBe('?');
    await help!.trigger('click');
    await flushPromises();
    expect(wrapper.find('.shortcut-help-panel').exists()).toBe(true);
    helpOpen.value = false;
    wrapper.unmount();
  });
});

describe('浮层键盘行为（spec §6）', () => {
  it('通知面板带 aria-modal，Esc 关闭并归还焦点给铃铛', async () => {
    const wrapper = mount(App, { global: viewStubs, attachTo: document.body });
    const bell = wrapper.find('.notif-wrap button');
    // jsdom 不会在 dispatchEvent('click') 时移动焦点，显式聚焦以还原真实浏览器点击后的焦点归位前置条件
    (bell.element as HTMLElement).focus();
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
