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
