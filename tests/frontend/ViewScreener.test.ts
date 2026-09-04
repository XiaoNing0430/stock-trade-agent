import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ViewScreener from '@/views/ViewScreener.vue';
import { useScreenerStore } from '@/stores/useScreenerStore';

vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));

const makeRow = (overrides: Partial<Record<string, unknown>> = {}) => ({
  code: '600519',
  name: '贵州茅台',
  exchange: '上交所',
  board: '主板',
  market: '沪市主板',
  price: 1700,
  change: 2.5,
  pe: 30,
  pb: 8,
  volumeRatio: 1.8,
  turnoverRate: 0.5,
  ...overrides,
});

describe('ViewScreener', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it('渲染筛选结果行（代码/名称/涨跌幅/行数统计）', () => {
    const screener = useScreenerStore();
    screener.screenRows = [makeRow()];
    screener.screenTotal = 50;
    const wrapper = mount(ViewScreener);
    expect(wrapper.text()).toContain('贵州茅台');
    expect(wrapper.text()).toContain('600519');
    expect(wrapper.text()).toContain('2.50%');
    expect(wrapper.text()).toContain('1 只股票符合条件');
    expect(wrapper.text()).toContain('候选池 50 只');
  });

  it('无筛选结果时显示空状态', () => {
    const wrapper = mount(ViewScreener);
    expect(wrapper.text()).toContain('没有找到符合条件的股票');
  });

  it('筛选条件排除不达标的股票并正确统计行数', () => {
    const screener = useScreenerStore();
    // 贵州茅台符合默认筛选条件；平安银行涨跌幅 0.2% < changeMin(1) 被排除
    screener.screenRows = [makeRow(), makeRow({ code: '000001', name: '平安银行', change: 0.2 })];
    const wrapper = mount(ViewScreener);
    expect(wrapper.text()).toContain('贵州茅台');
    expect(wrapper.text()).not.toContain('平安银行');
    expect(wrapper.text()).toContain('1 只股票符合条件');
  });

  it('结果洞察显示当前预设名称与描述，筛选面板字段完整', () => {
    const wrapper = mount(ViewScreener);
    // result-insight 显示当前预设（不受 storeToRefs 跳过 plain array 影响）
    expect(wrapper.text()).toContain('趋势突破');
    expect(wrapper.text()).toContain('放量、强势、价格向上');
    // 筛选字段
    expect(wrapper.text()).toContain('交易所');
    expect(wrapper.text()).toContain('板块');
    expect(wrapper.text()).toContain('搜索');
    expect(wrapper.text()).toContain('PE');
    expect(wrapper.text()).toContain('PB');
  });

  it('预设按钮列表渲染（storeToRefs 可解包 presets ref）', () => {
    const wrapper = mount(ViewScreener);
    const presetButtons = wrapper.findAll('.preset-item');
    expect(presetButtons.length).toBeGreaterThanOrEqual(3);
    expect(presetButtons[0].text()).toContain('趋势突破');
    expect(wrapper.text()).toContain('低估修复');
  });

  it('策略 tab：默认隐藏，点击后显示策略面板并加载策略列表', async () => {
    const { useWorkspaceStore } = await import('@/stores/useWorkspaceStore');
    const ws = useWorkspaceStore();
    const fetchSpy = vi.fn().mockResolvedValue({
      strategies: [
        { id: 'oversold_bounce', name: '超跌反弹', description: 'RSI 超卖', topN: 10, deepCap: 200, factorCount: 3 },
        { id: 'trend_breakout', name: '趋势突破', description: '多头排列', topN: 10, deepCap: 200, factorCount: 3 },
      ],
    });
    vi.spyOn(ws, 'requestJson').mockImplementation(fetchSpy);

    const wrapper = mount(ViewScreener);
    expect(wrapper.text()).not.toContain('策略选股');
    const tabs = wrapper.findAll('.screener-tab');
    const strategyTab = tabs.find((t) => t.text() === '策略');
    expect(strategyTab).toBeTruthy();
    await strategyTab!.trigger('click');
    expect(wrapper.text()).toContain('策略选股');
    expect(fetchSpy).toHaveBeenCalledWith('/api/screener/strategies');
    expect(wrapper.text()).toContain('超跌反弹');
  });

  it('策略 tab：默认极速模式，切换深度与运行调用 POST /api/screener/strategy', async () => {
    const { useWorkspaceStore } = await import('@/stores/useWorkspaceStore');
    const ws = useWorkspaceStore();
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        strategies: [{ id: 'oversold_bounce', name: '超跌反弹', description: 'RSI 超卖', topN: 10, deepCap: 200, factorCount: 3 }],
      })
      .mockResolvedValueOnce({
        strategy: 'oversold_bounce',
        name: '超跌反弹',
        mode: 'deep',
        referenceDate: '2026-08-28',
        provider: 'Tencent public quote API',
        rows: [
          {
            code: '600001',
            name: '测试股',
            price: 10.0,
            changePct: 1.5,
            pe: 12.0,
            pb: 1.5,
            roe: 15.0,
            score: 3,
            factors: { rsi: { value: 25.1, met: true, weight: 2 } },
          },
        ],
        total: 1,
        cached: false,
        stale: false,
        elapsedMs: 123,
      });
    vi.spyOn(ws, 'requestJson').mockImplementation(fetchSpy);

    const wrapper = mount(ViewScreener);
    const tabs = wrapper.findAll('.screener-tab');
    await tabs.find((t) => t.text() === '策略')!.trigger('click');
    await wrapper.findAll('.screener-tab').find((t) => t.text() === '深度')!.trigger('click');
    await wrapper.findAll('button').find((b) => b.text().includes('运行策略'))!.trigger('click');
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchSpy).toHaveBeenLastCalledWith('/api/screener/strategy', {
      method: 'POST',
      body: expect.stringContaining('"mode":"deep"'),
    });
    expect(wrapper.text()).toContain('测试股');
    expect(wrapper.text()).toContain('2026-08-28');
    expect(wrapper.text()).toContain('rsi 25.1');
  });

  it('策略 stale 降级显示警告横幅', async () => {
    const { useWorkspaceStore } = await import('@/stores/useWorkspaceStore');
    const ws = useWorkspaceStore();
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({ strategies: [{ id: 'oversold_bounce', name: '超跌反弹', description: 'x', topN: 10, deepCap: 200, factorCount: 1 }] })
      .mockResolvedValueOnce({
        strategy: 'oversold_bounce',
        name: '超跌反弹',
        mode: 'quick',
        referenceDate: '2026-08-28',
        provider: 'p',
        rows: [],
        total: 0,
        cached: true,
        stale: true,
        elapsedMs: 5,
      });
    vi.spyOn(ws, 'requestJson').mockImplementation(fetchSpy);

    const wrapper = mount(ViewScreener);
    const tabs = wrapper.findAll('.screener-tab');
    await tabs.find((t) => t.text() === '策略')!.trigger('click');
    await wrapper.findAll('button').find((b) => b.text().includes('运行策略'))!.trigger('click');
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(wrapper.text()).toContain('数据可能滞后');
  });
});
