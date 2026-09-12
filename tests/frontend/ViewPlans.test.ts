import { describe, expect, it, vi, beforeEach } from 'vitest';
import { nextTick } from 'vue';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ViewPlans from '@/views/ViewPlans.vue';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { usePlansStore } from '@/stores/usePlansStore';
import type { Plan } from '@/types/models';
import { requestJson } from '@/api/client';

// renderIcons() 在 onMounted 时调用 createIcons 扫描 DOM，测试中替换为 no-op。
vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));
// 绩效复盘面板（Task 8）：mock @/api/client，照抄 ViewScreener.test.ts 模式
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return { ...actual, requestJson: vi.fn() };
});

const reviewPayload = {
  kpis: { total: 2, decided: 1, flatCount: 0, winRate: 1, avgWinR: 1.97, avgLossR: null,
          payoffRatio: null, expectancyR: 1.97, notEnteredRate: 0, openCount: 1, invalidCount: 0 },
  groups: {
    source: [{ key: 'manual', label: '手动新建', decided: 1, flatCount: 0, wins: 1,
               winRate: 1, expectancyR: 1.97, smallSample: true }],
    direction: [{ key: 'buy', label: '买入', decided: 1, flatCount: 0, wins: 1,
                  winRate: 1, expectancyR: 1.97, smallSample: false }],
  },
  items: [{ planId: 'p1', code: '300750', source: 'manual', direction: 'buy', entry: 10,
            stop: 9.5, target: 11, validity: '本月内', status: '执行中', outcome: 'win',
            rValue: 2, netR: 1.97, costR: 0.03, entryDate: '2026-09-14', exitDate: '2026-09-15',
            ambiguous: false, gapFill: false, limitDeferred: false }],
};

const activePlan: Plan = {
  id: 'p1',
  code: '600519',
  direction: 'buy',
  entry: 1700,
  stop: 1600,
  target: 1900,
  capital: 100000,
  position: 50,
  validity: '今日',
  note: '',
  status: '执行中',
  triggered: {},
  createdAtMs: Date.now(),
};

describe('ViewPlans', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it('渲染执行中计划列表', () => {
    const workspace = useWorkspaceStore();
    workspace.plans = [activePlan];
    const wrapper = mount(ViewPlans);
    expect(wrapper.text()).toContain('600519');
    expect(wrapper.text()).toContain('执行中');
    expect(wrapper.text()).toContain('1,700.00');
  });

  it('activePlans 只包含执行中与已触发计划', () => {
    const workspace = useWorkspaceStore();
    workspace.plans = [
      activePlan,
      { ...activePlan, id: 'p2', code: '000001', status: '已归档' },
      { ...activePlan, id: 'p3', code: '000002', status: '已触发' },
    ];
    const wrapper = mount(ViewPlans);
    expect(wrapper.text()).toContain('600519');
    expect(wrapper.text()).toContain('000002');
    expect(wrapper.text()).not.toContain('000001');
  });

  it('无计划时显示空状态', () => {
    const wrapper = mount(ViewPlans);
    expect(wrapper.text()).toContain('还没有交易计划');
  });

  it('创建表单字段存在且回显草稿值', () => {
    const plans = usePlansStore();
    plans.draft.code = '600519';
    plans.draft.entry = 1700;
    plans.draft.stop = 1600;
    plans.draft.target = 1900;
    plans.draft.capital = 100000;
    plans.draft.position = 50;
    const wrapper = mount(ViewPlans);
    expect(wrapper.find('select').exists()).toBe(true);
    expect(wrapper.findAll('input[type="number"]').length).toBeGreaterThanOrEqual(4);
    expect(wrapper.find('input[type="range"]').exists()).toBe(true);
    expect(wrapper.find('textarea').exists()).toBe(true);
    expect(wrapper.text()).toContain('保存计划');
    const entryInput = wrapper.find('input[type="number"]');
    expect((entryInput.element as HTMLInputElement).value).toBe('1700');
  });

  it('提交有效表单后保存计划到工作区', async () => {
    const workspace = useWorkspaceStore();
    const plans = usePlansStore();
    plans.draft.code = '600519';
    plans.draft.entry = 1700;
    plans.draft.stop = 1600;
    plans.draft.target = 1900;
    plans.draft.capital = 100000;
    const wrapper = mount(ViewPlans);
    await wrapper.find('form').trigger('submit');
    expect(workspace.plans.length).toBe(1);
    expect(workspace.plans[0].code).toBe('600519');
    expect(workspace.plans[0].status).toBe('执行中');
  });

  it('mount 后新增计划列表与计数响应式更新', async () => {
    const workspace = useWorkspaceStore();
    const wrapper = mount(ViewPlans);
    expect(wrapper.findAll('.plan-card').length).toBe(0);
    expect(wrapper.text()).toContain('还没有交易计划');
    workspace.plans = [activePlan];
    await nextTick();
    expect(wrapper.findAll('.plan-card').length).toBe(1);
    expect(wrapper.find('.plan-count strong').text()).toBe('1');
    expect(wrapper.text()).toContain('600519');
    expect(wrapper.text()).not.toContain('还没有交易计划');
  });

  it('展开绩效面板时首次拉取并渲染 testids', async () => {
    vi.mocked(requestJson).mockResolvedValue(reviewPayload);
    const wrapper = mount(ViewPlans);
    await wrapper.find('[data-testid="review-toggle"]').trigger('click');
    await flushPromises();
    expect(vi.mocked(requestJson).mock.calls.some((c) => String(c[0]).includes('/api/plans/review'))).toBe(true);
    expect(wrapper.find('[data-testid="review-kpis"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="review-disclaimer"]').text()).toContain('不构成投资建议');
    expect(wrapper.find('[data-testid="review-fee-note"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="review-items"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="review-toggle"]').text()).toContain('近 90 天');
  });

  it('分组 Tab 切换与 smallSample 徽标', async () => {
    vi.mocked(requestJson).mockResolvedValue(reviewPayload);
    const wrapper = mount(ViewPlans);
    await wrapper.find('[data-testid="review-toggle"]').trigger('click');
    await flushPromises();
    const tabs = wrapper.findAll('[data-testid="review-group-tab"]');
    expect(tabs.length).toBeGreaterThanOrEqual(4);
    expect(wrapper.text()).toContain('样本不足，仅供参考');
    await tabs[1].trigger('click');
    await nextTick();
    expect(wrapper.find('[data-testid="review-items"]').exists()).toBe(true);
    expect(wrapper.text()).toContain('买入');
    expect(wrapper.text()).not.toContain('样本不足，仅供参考');
  });
});
