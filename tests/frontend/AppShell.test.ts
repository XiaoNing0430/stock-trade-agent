import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
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
