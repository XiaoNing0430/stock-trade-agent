import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { flushPromises, mount } from '@vue/test-utils';

vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));

import { useCompareStore } from '@/stores/useCompareStore';
import { useGridStore } from '@/stores/useGridStore';
import { useStrategyStore } from '@/stores/useStrategyStore';
import ViewGrid from '@/views/ViewGrid.vue';

const RUN_PAYLOAD = {
  code: '600519',
  profile: {},
  dataSource: 'tencent',
  dataAsOf: '2026-08-30',
  barCount: 60,
  benchmarkCurve: [{ date: '2026-01-01', equity: 1 }],
  results: [
    {
      strategyType: 'grid',
      label: '网格',
      config: { gridCount: 8, lower: 90, upper: 110 },
      metrics: { returnPct: 5.2, maxDrawdownPct: 3, tradeCount: 12, totalFees: 120 },
      equityCurve: [{ date: '2026-01-01', equity: 1 }],
      trades: [],
      assumptions: '网格假设',
      error: null,
    },
    { strategyType: 'macd', label: 'MACD', error: '回测失败：引擎炸了' },
  ],
};

describe('ViewGrid 对比 tab', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('tab 栏含「对比」且切换后渲染对比区块（8 个策略勾选 + 警示脚注）', async () => {
    const wrapper = mount(ViewGrid, { global: { plugins: [] } });
    await wrapper
      .find('.strategy-tabs')
      .findAll('button')
      .find((b) => b.text().includes('对比'))!
      .trigger('click');
    await flushPromises();
    expect(wrapper.text()).toContain('多策略横向对比');
    const checks = wrapper.findAll('.compare-type-check');
    expect(checks).toHaveLength(8);
  });

  it('对比结果渲染：指标行 / error 行 / 网格偏乐观警示 / 导出按钮', async () => {
    const wrapper = mount(ViewGrid, { global: { plugins: [] } });
    const strategy = useStrategyStore();
    strategy.strategyType = 'compare';
    const compare = useCompareStore();
    compare.runResult = RUN_PAYLOAD;
    await flushPromises();
    expect(wrapper.text()).toContain('网格区间为样本内自动建议，结果偏乐观');
    expect(wrapper.text()).toContain('回测失败：引擎炸了');
    // formatPct 输出带符号两位小数（+5.20%），brief 原断言 '5.2%' 与仓库百分比口径不符，等价修正
    expect(wrapper.text()).toContain('+5.20%');
    const exportButtons = wrapper.findAll('button').filter((b) => b.text().includes('导出'));
    expect(exportButtons.length).toBe(3);
  });

  it('已保存策略对比：无保存策略时空态文案', async () => {
    const wrapper = mount(ViewGrid, { global: { plugins: [] } });
    useStrategyStore().strategyType = 'compare';
    await flushPromises();
    expect(wrapper.text()).toContain('暂无已保存策略');
  });
});

describe('ViewGrid 结果区加载态与空态动作', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it('网格建议计算中显示加载态（spec §7.3-3）', async () => {
    useStrategyStore().strategyType = 'grid';
    const grid = useGridStore();
    grid.gridLoading = true;
    const wrapper = mount(ViewGrid, { global: { plugins: [] } });
    await flushPromises();
    const loading = wrapper.find('[data-testid="grid-suggestion-loading"]');
    expect(loading.exists()).toBe(true);
    expect(loading.text()).toContain('正在计算网格参数');
  });

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

  it('对比空态带「开始对比」按钮并调用 runCompare（spec §7.4）', async () => {
    const strategy = useStrategyStore();
    strategy.strategyType = 'compare';
    const compare = useCompareStore();
    const spy = vi.spyOn(compare, 'runCompare').mockResolvedValue(undefined as any);
    const wrapper = mount(ViewGrid, { global: { plugins: [] } });
    await flushPromises();
    const empty = wrapper.findAll('.empty-state').find((node) => node.text().includes('运行多策略对比'));
    await empty!.find('button').trigger('click');
    expect(spy).toHaveBeenCalledTimes(1);
  });
});
