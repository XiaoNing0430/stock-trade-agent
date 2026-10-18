import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { nextTick } from 'vue';
import { createPinia, setActivePinia } from 'pinia';
import ViewOverview from '@/views/ViewOverview.vue';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { useScreenerStore } from '@/stores/useScreenerStore';
import { useGridStore } from '@/stores/useGridStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import type { Alert } from '@/types/models';

// renderIcons() 在 onMounted 时调用 createIcons 扫描 DOM，测试中替换为 no-op。
vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));

describe('总览状态带（spec §7）', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

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
    workspace.alerts = [{ id: 'a1', kind: 'alert', title: 'x', message: 'y', read: false, createdAtMs: 1 }] as Alert[];
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

  it('挂载后替换 alerts，提醒计数与动态列表随之更新（store 响应性回归）', async () => {
    const workspace = useWorkspaceStore();
    workspace.alerts = [];
    const wrapper = mount(ViewOverview);
    const alertCount = () => wrapper.findAll('.desk-status-strip .desk-status-item')[3].text().replace(/\s+/g, '');
    expect(alertCount()).toBe('提醒0');
    expect(wrapper.findAll('.activity-item')).toHaveLength(0);
    workspace.alerts = [
      {
        id: 'a-late',
        kind: 'alert',
        title: '触及止损',
        message: '贵州茅台 触及止损',
        read: false,
        createdAtMs: 1,
      } as Alert,
    ];
    await nextTick();
    expect(alertCount()).toBe('提醒1');
    expect(wrapper.findAll('.activity-item')).toHaveLength(1);
    expect(wrapper.find('.activity-item').text()).toContain('触及止损');
    wrapper.unmount();
  });

  it('已删除重复的 KPI 卡与「验证策略」面板', () => {
    const wrapper = mount(ViewOverview);
    expect(wrapper.find('.desk-kpi').exists()).toBe(false);
    expect(wrapper.text()).not.toContain('验证策略');
    expect(wrapper.text()).not.toContain('待重新回测');
    wrapper.unmount();
  });

  it('指数加载中显示 .loading-state[role="status"]（spec §7）', async () => {
    const quotes = useQuotesStore();
    quotes.loading = true;
    const wrapper = mount(ViewOverview);
    await flushPromises();
    expect(wrapper.find('.loading-state[role="status"]').text()).toContain('正在读取指数');
    wrapper.unmount();
  });

  it('执行跟踪不再渲染与状态带重复的指标行', () => {
    const wrapper = mount(ViewOverview);
    expect(wrapper.findAll('.activity-item').length).toBeLessThanOrEqual(2);
    expect(wrapper.text()).not.toContain('触及止损');
    wrapper.unmount();
  });
});
