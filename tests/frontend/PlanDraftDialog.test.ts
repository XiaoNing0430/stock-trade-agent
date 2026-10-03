import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import PlanDraftDialog from '@/components/PlanDraftDialog.vue';
import { useAssistStore } from '@/stores/useAssistStore';
import { useSettingsStore } from '@/stores/useSettingsStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import type { Plan } from '@/types/models';

vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));

const DRAFT = {
  code: '600519',
  name: '贵州茅台',
  direction: 'buy',
  entry: 10,
  stopAtr: 9.0,
  stopMa20: 9.8,
  stop: 9.0,
  target: 11.0,
  stopDistance: 1.0,
  atr14: 0.5,
  ma20: 9.8,
  riskAmount: 1000,
  suggestedShares: 1000,
  positionPct: 10.0,
  referenceDate: '2026-09-02',
  entryAsOf: 1,
  stale: false,
  fallbackUsed: false,
  provider: 'x',
  warnings: ['A 股 T+1：当日买入次交易日方可卖出，止损自次一交易日生效'],
  disclaimer: '算法生成的建议，非投资建议',
};

async function mountDialog() {
  const wrapper = mount(PlanDraftDialog);
  const assist = useAssistStore();
  assist.draft = structuredClone(DRAFT);
  assist.visible = true;
  await wrapper.vm.$nextTick();
  return { wrapper, assist };
}

describe('PlanDraftDialog', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it('stale=true 显示过期快照横幅，正常时无横幅', async () => {
    const { wrapper, assist } = await mountDialog();
    expect(wrapper.find('[data-testid="stale-banner"]').exists()).toBe(false);
    assist.draft = { ...structuredClone(DRAFT), stale: true };
    await wrapper.vm.$nextTick();
    expect(wrapper.find('[data-testid="stale-banner"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="stale-banner"]').text()).toContain('入场价可能已过期');
  });

  it('fallbackUsed=true 显示备用源黄标，正常时无黄标', async () => {
    const { wrapper, assist } = await mountDialog();
    expect(wrapper.find('[data-testid="fallback-badge"]').exists()).toBe(false);
    assist.draft = { ...structuredClone(DRAFT), fallbackUsed: true };
    await wrapper.vm.$nextTick();
    expect(wrapper.find('[data-testid="fallback-badge"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="fallback-badge"]').text()).toContain('备用数据源');
  });

  it('后端 warnings 在前、sizing 警示在后（调参触发「权益不足一手」）', async () => {
    const { wrapper } = await mountDialog();
    // equity=1000、riskPct=1% → 风险额 10 元，止损距 1 元 → 不足一手 → sizing 警示
    await wrapper.find('input[data-testid="equity-input"]').setValue('1000');
    const texts = wrapper.findAll('[data-testid="warning-item"]').map((item) => item.text());
    expect(texts.length).toBeGreaterThanOrEqual(3);
    expect(texts[0]).toContain('T+1'); // 后端警示在前
    expect(texts).toContain('权益不足一手，无法按该风险比例建仓'); // sizing 警示在列表中
    expect(texts[texts.length - 1]).toContain('目标位距入场价超单日涨幅上限，需多日达成'); // sizing 警示收尾（在后）
  });

  it('调参重算零 API：改盈亏比仅本地重算 target', async () => {
    const { wrapper } = await mountDialog();
    const workspace = useWorkspaceStore();
    const spy = vi.spyOn(workspace, 'requestJson');
    spy.mockClear();
    await wrapper.find('input[data-testid="rr-input"]').setValue('3');
    expect(spy).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="target"]').text()).toContain('13.00'); // 10 + (10-9)*3
  });

  it('target/shares/positionPct 只读展示（与默认参数重算一致）', async () => {
    const { wrapper } = await mountDialog();
    // 默认 rr=2、riskPct=1%、equity=100000 → risk 1000 元 / 止损距 1 元 → 1000 股、10%、目标 12.00
    expect(wrapper.find('[data-testid="target"]').text()).toContain('12.00');
    expect(wrapper.find('[data-testid="shares"]').text()).toContain('1000');
    expect(wrapper.find('[data-testid="position"]').text()).toContain('10.00%');
  });

  it('shares=0 时确认按钮置灰并显示资金不足提示', async () => {
    const { wrapper } = await mountDialog();
    await wrapper.find('input[data-testid="equity-input"]').setValue('1000'); // 风险额 10 元不足一手
    await wrapper.vm.$nextTick();
    const btn = wrapper.find('button[data-testid="confirm"]');
    expect(btn.attributes('disabled')).toBeDefined();
    expect(wrapper.text()).toContain('资金不足以按该风险比例建仓，请调高风险比例或降低入场价');
  });

  it('stop=null（候选止损均无效）时确认置灰并显示无有效止损提示（非资金不足文案）', async () => {
    const { wrapper, assist } = await mountDialog();
    // 后端数据不足透传 null 候选（atr14/ma20 均 null）→ recalc 后 suggestion.stop == null
    assist.draft = { ...structuredClone(DRAFT), atr14: null, ma20: null };
    await wrapper.vm.$nextTick();
    const btn = wrapper.find('button[data-testid="confirm"]');
    expect(btn.attributes('disabled')).toBeDefined();
    expect(wrapper.text()).toContain('暂无有效止损，请调整参数或手动设定止损');
    expect(wrapper.text()).not.toContain('资金不足以按该风险比例建仓');
  });

  it('确认触发 confirmDraft：构建 savePlan 同形计划（status 执行中 / triggered:{}）', async () => {
    const { wrapper, assist } = await mountDialog();
    // B6：source 经 openFor 写入 draft 状态对象（与 code 同路），对话框同源读取后随确认落计划
    assist.draft = { ...structuredClone(DRAFT), source: 'scan:trend_breakout' };
    await wrapper.vm.$nextTick();
    const confirmSpy = vi.spyOn(assist, 'confirmDraft').mockImplementation(async () => {
      assist.visible = false;
      return 'saved';
    });
    await wrapper.find('button[data-testid="confirm"]').trigger('click');
    await vi.waitFor(() => expect(confirmSpy).toHaveBeenCalledTimes(1));
    const plan = confirmSpy.mock.calls[0][0] as Plan & { createdAt?: string };
    expect(plan.code).toBe('600519');
    expect(plan.direction).toBe('buy');
    expect(plan.entry).toBe(10);
    expect(plan.stop).toBe(9); // atr 模式：10 - 2*0.5
    expect(plan.target).toBe(12); // rr=2
    expect(plan.capital).toBe(100000);
    expect(plan.position).toBe(10);
    expect(plan.validity).toBe('本周内');
    expect(plan.status).toBe('执行中');
    expect(plan.triggered).toEqual({});
    expect(plan.createdAtMs).toEqual(expect.any(Number));
    expect(plan.createdAt).toEqual(expect.any(String));
    expect(plan.id).toContain('plan-600519-');
    expect(plan.source).toBe('scan:trend_breakout'); // 入口归因随计划落库
  });

  it('confirmDraft 落计划 source 缺省兜底 manual，且入场价附近显示口径提示行', async () => {
    const { wrapper, assist } = await mountDialog();
    const note = wrapper.find('[data-testid="draft-price-scope-note"]');
    expect(note.exists()).toBe(true);
    expect(note.text()).toContain('K 线图为前复权价，请勿直接照抄图表价位');
    const confirmSpy = vi.spyOn(assist, 'confirmDraft').mockImplementation(async () => {
      assist.visible = false;
      return 'saved';
    });
    await wrapper.find('button[data-testid="confirm"]').trigger('click');
    await vi.waitFor(() => expect(confirmSpy).toHaveBeenCalledTimes(1));
    const plan = confirmSpy.mock.calls[0][0] as Plan & { createdAt?: string };
    expect(plan.source).toBe('manual');
  });

  it('确认成功后对话框关闭且计划入列（真实 confirmDraft 流程）', async () => {
    const { wrapper, assist } = await mountDialog();
    const workspace = useWorkspaceStore();
    const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => ({
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: async () => ({ revision: 2 }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    await wrapper.find('button[data-testid="confirm"]').trigger('click');
    await vi.waitFor(() => expect(assist.visible).toBe(false));
    expect(workspace.plans[0].code).toBe('600519');
    expect(workspace.plans[0].status).toBe('执行中');
    expect(assist.submitting).toBe(false);
  });

  it('提交中确认按钮置灰（single-flight）', async () => {
    const { wrapper, assist } = await mountDialog();
    assist.submitting = true;
    await wrapper.vm.$nextTick();
    expect(wrapper.find('button[data-testid="confirm"]').attributes('disabled')).toBeDefined();
  });

  it('Kelly 折叠参考：默认折叠，空输入显示 --，填 55/2 显示半凯利 16.3%（纯展示不影响建议）', async () => {
    const { wrapper } = await mountDialog();
    const kelly = wrapper.find('details[data-testid="kelly-ref"]');
    expect(kelly.exists()).toBe(true);
    expect(kelly.attributes('open')).toBeUndefined(); // 默认折叠
    const result = kelly.find('[data-testid="kelly-result"]');
    expect(result.text()).toContain('--'); // 空输入绝不造数
    await kelly.find('input[data-testid="kelly-winrate"]').setValue('55');
    await kelly.find('input[data-testid="kelly-payoff"]').setValue('2');
    // (0.55 - 0.45/2) × 0.5 = 0.1625 → 16.25% → toFixed(1) → 16.3%
    expect(result.text()).toContain('16.3%');
    // 纯展示：计划建议数学仍为 risk-pct 基，target 不受 Kelly 输入影响
    expect(wrapper.find('[data-testid="target"]').text()).toContain('12.00');
  });

  it('新草案打开：调参参数镜像设置 4 键（stopMode/rr/riskPct/capPct），equity 随 defaultCapital', async () => {
    const settings = useSettingsStore();
    Object.assign(settings.settingsDraft, {
      riskPerTradePct: 1.5,
      rrRatio: 3,
      stopMode: 'ma20',
      positionCapPct: 40,
      defaultCapital: 200000,
    });
    const { wrapper } = await mountDialog();
    expect((wrapper.find('select[data-testid="stop-mode-select"]').element as HTMLSelectElement).value).toBe('ma20');
    expect((wrapper.find('input[data-testid="rr-input"]').element as HTMLInputElement).value).toBe('3');
    expect((wrapper.find('input[data-testid="risk-pct-input"]').element as HTMLInputElement).value).toBe('1.5');
    expect((wrapper.find('input[data-testid="cap-pct-input"]').element as HTMLInputElement).value).toBe('40');
    expect((wrapper.find('input[data-testid="equity-input"]').element as HTMLInputElement).value).toBe('200000');
  });

  it('设置未加载（空 settingsDraft）→ 对话框回显回退默认 atr/2/1/25（不造数、不发设置请求）', async () => {
    const settings = useSettingsStore();
    const workspace = useWorkspaceStore();
    const requestSpy = vi.spyOn(workspace, 'requestJson');
    Object.assign(settings.settingsDraft, {
      riskPerTradePct: undefined,
      rrRatio: undefined,
      stopMode: undefined,
      positionCapPct: undefined,
      defaultCapital: undefined,
    });
    const { wrapper } = await mountDialog();
    expect((wrapper.find('select[data-testid="stop-mode-select"]').element as HTMLSelectElement).value).toBe('atr');
    expect((wrapper.find('input[data-testid="rr-input"]').element as HTMLInputElement).value).toBe('2');
    expect((wrapper.find('input[data-testid="risk-pct-input"]').element as HTMLInputElement).value).toBe('1');
    expect((wrapper.find('input[data-testid="cap-pct-input"]').element as HTMLInputElement).value).toBe('25');
    expect(requestSpy).not.toHaveBeenCalled();
  });
});
