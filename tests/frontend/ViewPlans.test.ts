import { describe, expect, it, vi, beforeEach } from 'vitest';
import { nextTick } from 'vue';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ViewPlans from '@/views/ViewPlans.vue';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { usePlansStore } from '@/stores/usePlansStore';
import type { Plan } from '@/types/models';

// renderIcons() 在 onMounted 时调用 createIcons 扫描 DOM，测试中替换为 no-op。
vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));

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
});
