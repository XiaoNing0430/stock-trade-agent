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

  it('复盘加载失败 → 渲染 review-error 且不误渲染 review-trace-error（N4 分离）', async () => {
    vi.mocked(requestJson).mockRejectedValue(new Error('网络中断'));
    const wrapper = mount(ViewPlans);
    await wrapper.find('[data-testid="review-toggle"]').trigger('click');
    await flushPromises();
    const err = wrapper.find('[data-testid="review-error"]');
    expect(err.exists()).toBe(true);
    expect(err.text()).toContain('复盘数据加载失败');
    expect(err.text()).toContain('网络中断');
    expect(wrapper.find('[data-testid="review-trace-error"]').exists()).toBe(false); // 复盘错误不触发留痕错误条
  });

  it('仅留痕加载失败 → 渲染 review-trace-error 且无 review-error（N4 分离）', async () => {
    const withScan = {
      ...reviewPayload,
      groups: { ...reviewPayload.groups,
        source: [{ key: 'scan:trend_breakout', label: '扫描·趋势突破', decided: 2, flatCount: 0, wins: 1,
                   winRate: 0.5, expectancyR: 0.4, smallSample: false }] },
    };
    vi.mocked(requestJson).mockImplementation((url: unknown) =>
      String(url).includes('/api/plans/review')
        ? Promise.resolve(withScan)                                    // 复盘成功 → reviewError null
        : Promise.reject(new Error('留痕上游不可用')),                  // 留痕失败 → traceError
    );
    const wrapper = mount(ViewPlans);
    await wrapper.find('[data-testid="review-toggle"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="review-error"]').exists()).toBe(false);
    const te = wrapper.find('[data-testid="review-trace-error"]');
    expect(te.exists()).toBe(true);
    expect(te.text()).toContain('扫描留痕加载失败');
    expect(te.text()).toContain('留痕上游不可用');
    expect(wrapper.find('[data-testid="review-trace"]').exists()).toBe(false); // trace 失败置空，不留半截面板
  });

  it('降级披露：degraded 非空 → 渲染 review-degraded 且含各代码（N1）', async () => {
    vi.mocked(requestJson).mockResolvedValue({ ...reviewPayload, degraded: ['600519', '000001'] });
    const wrapper = mount(ViewPlans);
    await wrapper.find('[data-testid="review-toggle"]').trigger('click');
    await flushPromises();
    const line = wrapper.find('[data-testid="review-degraded"]');
    expect(line.exists()).toBe(true);
    expect(line.text()).toContain('600519');
    expect(line.text()).toContain('000001');
    expect(line.text()).toContain('本地历史兜底');
  });

  it('降级披露：degraded 缺省 → 不渲染 review-degraded（N1）', async () => {
    vi.mocked(requestJson).mockResolvedValue(reviewPayload);
    const wrapper = mount(ViewPlans);
    await wrapper.find('[data-testid="review-toggle"]').trigger('click');
    await flushPromises();
    expect(wrapper.find('[data-testid="review-degraded"]').exists()).toBe(false);
  });

  it('扫描留痕降序渲染至多 10 条、runAtMs null 行渲染 --（终审 F4/F5）', async () => {
    const withScan = {
      ...reviewPayload,
      groups: {
        ...reviewPayload.groups,
        source: [{ key: 'scan:trend_breakout', label: '扫描·趋势突破', decided: 2, flatCount: 0, wins: 1,
                   winRate: 0.5, expectancyR: 0.4, smallSample: false }],
      },
    };
    const rows = Array.from({ length: 12 }, (_, i) => ({
      strategyId: 'trend_breakout', runAtMs: i === 0 ? null : 1_789_000_000_000 - i, status: 'ok',
      hitCount: 2, newCount: 1, elapsedMs: 1200, traceId: `t${i}`,
    }));
    vi.mocked(requestJson).mockImplementation((url: unknown) =>
      String(url).includes('/api/plans/review')
        ? Promise.resolve(withScan)
        : Promise.resolve({ history: rows }),
    );
    const wrapper = mount(ViewPlans);
    await wrapper.find('[data-testid="review-toggle"]').trigger('click');
    await flushPromises();
    const trace = wrapper.find('[data-testid="review-trace"]');
    expect(trace.exists()).toBe(true);
    // 行 `<p>` 含「/ 新增」，概览 `<p>`（近 30 天运行 … 平均命中 …）不含，据此仅取数据行。
    const rowTexts = trace.findAll('p.muted').filter((p) => p.text().includes('新增')).map((p) => p.text());
    expect(rowTexts).toHaveLength(10);                  // 12 → 钳制 10
    expect(rowTexts[0]).toContain('--');                // 首行 runAtMs null → 占位，不崩溃
    expect(rowTexts.some((t) => !t.startsWith('--'))).toBe(true); // 其余行正常显示时间
  });

  // ── Task 9 交易对关联：sell 行内 关联建仓下拉 + exitMode 四档 + sell_only 二次确认 ──
  describe('交易对关联（Task 9）', () => {
    // s1 已配 b1；b2 被归档卖单 s2 占用（后端先到先得整表扫描，归档卖家同样占坑）；b3 跨 code。
    const sellS1: Plan = { ...activePlan, id: 's1', direction: 'sell', status: '已触发', relatedPlan: 'b1' };
    const buyB1: Plan = { ...activePlan, id: 'b1' };
    const buyTaken: Plan = { ...activePlan, id: 'b2' };
    const sellTaker: Plan = { ...activePlan, id: 's2', direction: 'sell', status: '已归档', relatedPlan: 'b2' };
    const buyOtherCode: Plan = { ...activePlan, id: 'b3', code: '000001' };

    function seedLinked() {
      const workspace = useWorkspaceStore();
      workspace.plans = [sellS1, buyB1, buyTaken, sellTaker, buyOtherCode];
      return workspace;
    }

    it('sell 行渲染关联控件；下拉仅列同 code 未配对 buy（已归档/跨 code/被占排除，当前关联回显）', () => {
      seedLinked();
      const wrapper = mount(ViewPlans);
      const pair = wrapper.find('[data-testid="pair-select"]');
      const exit = wrapper.find('[data-testid="exit-mode-select"]');
      expect(pair.exists()).toBe(true); // activePlans 仅 执行中/已触发：归档 s2 与全部 buy 行无控件
      expect(exit.exists()).toBe(true);
      expect(wrapper.findAll('[data-testid="pair-select"]')).toHaveLength(1);
      const values = pair.findAll('option').map((o) => (o.element as HTMLOptionElement).value);
      expect(values).toEqual(['', 'b1']);
      expect((pair.element as HTMLSelectElement).value).toBe('b1'); // 当前关联回显
      expect(pair.findAll('option')[0].text()).toContain('解除关联');
      const exitOptions = exit.findAll('option'); // 四档中文标签 + 后端值，默认回显 race（NULL≡race）
      expect(exitOptions.map((o) => (o.element as HTMLOptionElement).value)).toEqual([
        'race',
        'sell_priority',
        'sell_stop_only',
        'sell_only',
      ]);
      expect(exitOptions.map((o) => o.text())).toEqual(['先到先平', '平仓单优先', '止损优先', '仅平仓单']);
      expect((exit.element as HTMLSelectElement).value).toBe('race');
    });

    it('未关联 sell：空值选项为（未关联）且列出全部可用 buy', () => {
      const workspace = useWorkspaceStore();
      workspace.plans = [
        { ...activePlan, id: 's3', direction: 'sell', status: '执行中' },
        buyB1,
        buyTaken,
      ];
      const wrapper = mount(ViewPlans);
      const pair = wrapper.find('[data-testid="pair-select"]');
      const values = pair.findAll('option').map((o) => (o.element as HTMLOptionElement).value);
      expect(values).toEqual(['', 'b1', 'b2']);
      expect(pair.findAll('option')[0].text()).toContain('未关联');
    });

    it('选择（解除关联）→ updatePlanLinkage(s1, { relatedPlan: null })', async () => {
      seedLinked();
      const plans = usePlansStore();
      const action = vi.fn().mockResolvedValue(undefined);
      plans.updatePlanLinkage = action;
      const wrapper = mount(ViewPlans);
      await wrapper.find('[data-testid="pair-select"]').setValue('');
      expect(action).toHaveBeenCalledTimes(1);
      expect(action).toHaveBeenCalledWith('s1', { relatedPlan: null });
    });

    it('sell_only 取消二次确认 → 不写不调用，下拉回退 race', async () => {
      const confirmMock = vi.fn((_message?: string) => false);
      vi.stubGlobal('confirm', confirmMock);
      try {
        seedLinked();
        const plans = usePlansStore();
        const action = vi.fn().mockResolvedValue(undefined);
        plans.updatePlanLinkage = action;
        const wrapper = mount(ViewPlans);
        const exit = wrapper.find('[data-testid="exit-mode-select"]');
        await exit.setValue('sell_only');
        expect(confirmMock).toHaveBeenCalledTimes(1);
        expect(String(confirmMock.mock.calls[0][0])).toContain('仅由关联平仓单离场，无止损保护');
        expect(action).not.toHaveBeenCalled();
        expect(useWorkspaceStore().plans.find((p) => p.id === 's1')?.exitMode).toBeUndefined();
        expect((exit.element as HTMLSelectElement).value).toBe('race'); // 取消=回退显示
      } finally {
        vi.unstubAllGlobals();
      }
    });

    it('sell_only 确认通过 → 真实 action 写入 exitMode 并触发保存（persist）', async () => {
      const confirmMock = vi.fn(() => true);
      vi.stubGlobal('confirm', confirmMock);
      try {
        const workspace = seedLinked();
        const persistSpy = vi.spyOn(workspace, 'persist');
        const wrapper = mount(ViewPlans);
        await wrapper.find('[data-testid="exit-mode-select"]').setValue('sell_only');
        await flushPromises();
        const stored = workspace.plans.find((p) => p.id === 's1');
        expect(stored?.exitMode).toBe('sell_only'); // 真实 action 落库字段（workspaceSynced=false → syncNow 视作成功）
        expect(stored?.relatedPlan).toBe('b1'); // 不误伤既有交易对关联
        expect(persistSpy).toHaveBeenCalled(); // 走既有保存 action
        expect(confirmMock).toHaveBeenCalledTimes(1);
      } finally {
        vi.unstubAllGlobals();
      }
    });

    it('exitMode 非 sell_only 档不弹 confirm，直接写入', async () => {
      const confirmMock = vi.fn(() => true);
      vi.stubGlobal('confirm', confirmMock);
      try {
        const workspace = seedLinked();
        const wrapper = mount(ViewPlans);
        await wrapper.find('[data-testid="exit-mode-select"]').setValue('sell_stop_only');
        await flushPromises();
        expect(confirmMock).not.toHaveBeenCalled();
        expect(workspace.plans.find((p) => p.id === 's1')?.exitMode).toBe('sell_stop_only');
      } finally {
        vi.unstubAllGlobals();
      }
    });

    it('保存失败（store reject 后端 422 中文 detail）→ error toast 透传消息且下拉回退', async () => {
      const workspace = seedLinked();
      const toastSpy = vi.spyOn(workspace, 'showToast');
      const plans = usePlansStore();
      plans.updatePlanLinkage = vi.fn().mockRejectedValue(
        new Error('建仓计划「b2」已被卖出计划「s2」关联，不能被「s1」重复关联；如需换绑请先解除原关联')
      );
      const wrapper = mount(ViewPlans);
      const pair = wrapper.find('[data-testid="pair-select"]');
      await pair.setValue(''); // 以解除关联动作触发失败路径（本用例只钉失败语义）
      await flushPromises();
      expect(toastSpy).toHaveBeenCalledTimes(1);
      expect(toastSpy.mock.calls[0][0]).toContain('重复关联');
      expect(toastSpy.mock.calls[0][1]).toBe('error');
      expect((pair.element as HTMLSelectElement).value).toBe('b1'); // 失败回退到数据真值
    });
  });

  // ── Task 9 写路径（真实 updatePlanLinkage + 真实 syncNow + fetch 桩）：成功 PUT / 422 回滚 ──
  describe('usePlansStore.updatePlanLinkage 写路径（Task 9）', () => {
    function jsonResponse(payload: unknown, ok = true, status = 200) {
      return { ok, status, headers: { get: () => null }, json: async () => payload };
    }
    const sell: Plan = { ...activePlan, id: 's1', direction: 'sell', relatedPlan: 'b1' };
    const buy: Plan = { ...activePlan, id: 'b1' };

    it('workspaceSynced=true 成功：本地写入 + PUT 携带 relatedPlan/exitMode + 成功 toast', async () => {
      const workspace = useWorkspaceStore();
      workspace.workspaceSynced = true;
      workspace.plans = [sell, buy];
      const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ revision: 9 }));
      vi.stubGlobal('fetch', fetchMock);
      const toastSpy = vi.spyOn(workspace, 'showToast');
      try {
        await usePlansStore().updatePlanLinkage('s1', { exitMode: 'sell_priority' });
        expect(workspace.plans.find((p) => p.id === 's1')?.exitMode).toBe('sell_priority');
        const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
        const s1 = body.plans.find((p: { id: string }) => p.id === 's1');
        expect(s1.relatedPlan).toBe('b1');
        expect(s1.exitMode).toBe('sell_priority');
        expect(toastSpy).toHaveBeenCalledTimes(1);
        expect(toastSpy.mock.calls[0][1]).not.toBe('error');
      } finally {
        vi.unstubAllGlobals();
      }
    });

    it('解除关联成功：PUT body 该 plan 键整体省略（undefined 不落 null——后端 None≡未配对）（收尾硬化 L3）', async () => {
      const workspace = useWorkspaceStore();
      workspace.workspaceSynced = true;
      // 本组件级共享 sell/buy 会被写路径真实 mutate——本例用私有副本，防污染相邻用例
      workspace.plans = [{ ...sell, exitMode: undefined }, { ...buy }];
      const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ revision: 10 }));
      vi.stubGlobal('fetch', fetchMock);
      try {
        await usePlansStore().updatePlanLinkage('s1', { relatedPlan: null });
        const body = JSON.parse(String((fetchMock.mock.calls[0][1] as RequestInit).body));
        const s1 = body.plans.find((p: { id: string }) => p.id === 's1');
        expect(s1).not.toHaveProperty('relatedPlan');
        expect(s1).not.toHaveProperty('exitMode');
      } finally {
        vi.unstubAllGlobals();
      }
    });

    it('后端 422（双配竞态中文 detail）：回滚本地字段 + toast 透传后端消息', async () => {
      const workspace = useWorkspaceStore();
      workspace.workspaceSynced = true;
      workspace.plans = [sell, buy];
      vi.stubGlobal(
        'fetch',
        vi.fn(async () => jsonResponse({ detail: { error: '建仓计划「b1」已被卖出计划「s9」关联' } }, false, 422))
      );
      const toastSpy = vi.spyOn(workspace, 'showToast');
      try {
        await expect(usePlansStore().updatePlanLinkage('s1', { relatedPlan: null })).rejects.toThrow(
          '建仓计划「b1」已被卖出计划「s9」关联'
        );
        expect(workspace.plans.find((p) => p.id === 's1')?.relatedPlan).toBe('b1'); // 已回滚
        expect(toastSpy).not.toHaveBeenCalled(); // toast 由视图 catch 负责，store 不加戏
      } finally {
        vi.unstubAllGlobals();
      }
    });
  });
});
