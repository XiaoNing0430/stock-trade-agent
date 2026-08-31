import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ViewScreener from '@/views/ViewScreener.vue';
import { useScreenerStore } from '@/stores/useScreenerStore';

vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));

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
});
