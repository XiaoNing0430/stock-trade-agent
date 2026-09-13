import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useAssistStore } from '@/stores/useAssistStore';
import { useSettingsStore } from '@/stores/useSettingsStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import type { Plan } from '@/types/models';

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

const basePlan: Plan = {
  id: 'plan-000001-1',
  code: '000001',
  direction: 'buy',
  entry: 10,
  stop: 9,
  target: 12,
  capital: 100000,
  position: 10,
  validity: '本周内',
  note: '',
  status: '执行中',
  triggered: {},
  createdAtMs: Date.now(),
};

/** useAssistStore 走 workspace.requestJson（跨 store 属性调用），内部落在 fetch 层。 */
function jsonResponse(payload: unknown, ok = true, status = 200) {
  return { ok, status, headers: { get: () => null }, json: async () => payload };
}

describe('useAssistStore', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  describe('recalc', () => {
    const baseInput = {
      entry: 10,
      stopMode: 'atr' as const,
      rrRatio: 2,
      riskPct: 1,
      capPct: 25,
      manualStop: null,
      equity: 100000,
    };

    it('recalc 用 assistCalc 重算 shares 与 target（零 API）', () => {
      const assist = useAssistStore();
      assist.draft = structuredClone(DRAFT);
      const base = assist.recalc({ ...baseInput });
      expect(base).not.toBeNull();
      expect(base!.stop).toBe(9); // ATR 候选：10 - 2*0.5
      expect(base!.target).toBe(12); // 10 + 止损距 1 * 盈亏比 2
      expect(base!.suggestedShares).toBe(1000); // 风险额 1000 / 止损距 1 → 1000 股
      expect(base!.positionPct).toBe(10);
      const retuned = assist.recalc({ ...baseInput, rrRatio: 3, riskPct: 2 });
      expect(retuned!.target).toBe(13);
      expect(retuned!.suggestedShares).toBe(2000); // 风险额 2000 → 2000 股
      expect(assist.suggestion).toEqual(retuned);
    });

    it('手动止损接管候选并按其重算', () => {
      const assist = useAssistStore();
      assist.draft = structuredClone(DRAFT);
      const manual = assist.recalc({ ...baseInput, manualStop: 9.5 });
      expect(manual!.stop).toBe(9.5);
      expect(manual!.target).toBe(11); // 10 + 0.5*2
      expect(manual!.suggestedShares).toBe(2000); // 风险额 1000 / 0.5 → 2000 股
    });

    it('手动止损不低于入场价时回退候选（sizePositionAtStop 守卫）', () => {
      const assist = useAssistStore();
      assist.draft = structuredClone(DRAFT);
      const out = assist.recalc({ ...baseInput, manualStop: 10.5 });
      expect(out!.stop).toBe(9); // 回退 ATR 候选
    });

    it('零股：权益不足一手警示，suggestion 供确认按钮置灰', () => {
      const assist = useAssistStore();
      assist.draft = structuredClone(DRAFT);
      const zero = assist.recalc({ ...baseInput, equity: 1000 }); // 风险额 10 元不足一手
      expect(zero!.suggestedShares).toBe(0);
      expect(zero!.warnings).toContain('权益不足一手，无法按该风险比例建仓');
      expect(assist.suggestion).toEqual(zero);
    });

    it('draft 为空时 recalc 返回 null 且 suggestion 置空', () => {
      const assist = useAssistStore();
      expect(assist.recalc({ ...baseInput })).toBeNull();
      expect(assist.suggestion).toBeNull();
    });
  });

  describe('openFor', () => {
    it('请求草案端点并解包 {data} 包裹填充 draft', async () => {
      const workspace = useWorkspaceStore();
      const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
        jsonResponse({ data: structuredClone(DRAFT) })
      );
      vi.stubGlobal('fetch', fetchMock);
      const assist = useAssistStore();
      await assist.openFor({ code: '600519', name: '贵州茅台', price: 10, asOfMs: 1 });
      expect(assist.visible).toBe(true);
      expect(assist.loading).toBe(false);
      expect(assist.error).toBe('');
      expect(assist.draft).toEqual(DRAFT);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, options] = fetchMock.mock.calls[0];
      expect(String(url)).toBe('/api/assist/plan-draft');
      expect((options as RequestInit).method).toBe('POST');
      expect(JSON.parse(String((options as RequestInit).body))).toEqual({
        code: '600519',
        name: '贵州茅台',
        entryPrice: 10,
        entryAsOfMs: 1,
      });
    });

    it('openFor 携带 source 时写入同一 draft 状态对象（B6：与 code 同路，确认落计划透传）', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ data: structuredClone(DRAFT) }))
      );
      const assist = useAssistStore();
      await assist.openFor({ code: '600519', source: 'scan:trend_breakout' });
      expect(assist.draft?.source).toBe('scan:trend_breakout');
    });

    it('openFor 未传 source 时 draft.source 为空（计划构造点兜底 manual）', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ data: structuredClone(DRAFT) }))
      );
      const assist = useAssistStore();
      await assist.openFor({ code: '600519' });
      expect(assist.draft?.source).toBeUndefined();
    });

    it('上游错误透传 detail.error 并 error toast', async () => {
      const workspace = useWorkspaceStore();
      const toastSpy = vi.spyOn(workspace, 'showToast');
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
          jsonResponse({ detail: { error: '行情数据不可用' } }, false, 502)
        )
      );
      const assist = useAssistStore();
      await assist.openFor({ code: '600519' });
      expect(assist.error).toBe('行情数据不可用');
      expect(toastSpy).toHaveBeenCalledWith('行情数据不可用', 'error');
      expect(assist.draft).toBeNull();
      expect(assist.loading).toBe(false);
      expect(assist.visible).toBe(true); // 对话框保持打开展示错误
    });

    it('网络错误使用兜底文案「草案生成失败」', async () => {
      const workspace = useWorkspaceStore();
      const toastSpy = vi.spyOn(workspace, 'showToast');
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => {
          throw new TypeError('Failed to fetch');
        })
      );
      const assist = useAssistStore();
      await assist.openFor({ code: '600519' });
      expect(assist.error).toBe('草案生成失败');
      expect(toastSpy).toHaveBeenCalledWith('草案生成失败', 'error');
    });
  });

  describe('confirmDraft', () => {
    it('成功路径：plan 入列（savePlan 同形）→ syncNow 立即 PUT → toast → 关闭对话框', async () => {
      const workspace = useWorkspaceStore();
      workspace.workspaceSynced = true;
      workspace.plans = [{ ...basePlan }];
      const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ revision: 2 }));
      vi.stubGlobal('fetch', fetchMock);
      const toastSpy = vi.spyOn(workspace, 'showToast');
      const assist = useAssistStore();
      assist.visible = true;
      const plan: Plan & { createdAt: string } = {
        id: `plan-${DRAFT.code}-${Date.now()}`,
        code: DRAFT.code,
        direction: 'buy',
        entry: 10,
        stop: 9,
        target: 12,
        capital: 100000,
        position: 10,
        validity: '本周内',
        note: '辅助草案',
        status: '执行中',
        triggered: {},
        createdAtMs: Date.now(),
        createdAt: '10:00',
      };
      const result = await assist.confirmDraft(plan);
      expect(result).toBe('saved');
      expect(workspace.plans).toHaveLength(2);
      expect(workspace.plans[0].id).toBe(plan.id);
      expect(fetchMock).toHaveBeenCalledTimes(1);
      const [url, options] = fetchMock.mock.calls[0];
      expect(String(url)).toContain('/api/workspace?baseRevision=');
      expect((options as RequestInit).method).toBe('PUT');
      expect(JSON.parse(String((options as RequestInit).body)).plans).toHaveLength(2);
      expect(toastSpy).toHaveBeenCalledWith('交易计划已保存：600519 10.00 → 12.00');
      expect(assist.visible).toBe(false);
      expect(assist.submitting).toBe(false);
    });

    it('409 冲突：回滚本地计划 + conflict toast，绝不自动重试，对话框保持打开', async () => {
      const workspace = useWorkspaceStore();
      workspace.workspaceSynced = true;
      workspace.plans = [{ ...basePlan }];
      const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) =>
        jsonResponse({ detail: { error: '冲突' } }, false, 409)
      );
      vi.stubGlobal('fetch', fetchMock);
      const toastSpy = vi.spyOn(workspace, 'showToast');
      const assist = useAssistStore();
      assist.visible = true;
      const result = await assist.confirmDraft({
        id: 'plan-600519-2',
        code: '600519',
        direction: 'buy',
        entry: 10,
        stop: 9,
        target: 12,
        capital: 100000,
        position: 10,
        validity: '本周内',
        note: '辅助草案',
        status: '执行中',
        triggered: {},
        createdAtMs: Date.now(),
      });
      expect(result).toBe('conflict');
      expect(workspace.plans).toHaveLength(1); // 仅剩既有计划，新计划已回滚
      expect(workspace.plans[0].id).toBe(basePlan.id);
      expect(fetchMock).toHaveBeenCalledTimes(1); // 绝不自动重试 409
      expect(toastSpy).toHaveBeenCalledWith('工作区有新变更，请刷新后重试', 'error');
      expect(assist.visible).toBe(true);
      expect(assist.submitting).toBe(false);
    });

    it('非 409 失败：本地保留（恢复后自动同步）+ 提示 + 关闭对话框', async () => {
      const workspace = useWorkspaceStore();
      workspace.workspaceSynced = true;
      const fetchMock = vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({}, false, 503));
      vi.stubGlobal('fetch', fetchMock);
      const toastSpy = vi.spyOn(workspace, 'showToast');
      const assist = useAssistStore();
      const result = await assist.confirmDraft({
        id: 'plan-600519-3',
        code: '600519',
        direction: 'buy',
        entry: 10,
        stop: 9,
        target: 12,
        capital: 100000,
        position: 10,
        validity: '本周内',
        note: '',
        status: '执行中',
        triggered: {},
        createdAtMs: Date.now(),
      });
      expect(result).toBe('error');
      expect(workspace.plans).toHaveLength(1); // 本地保留
      expect(workspace.plans[0].code).toBe('600519');
      expect(fetchMock).toHaveBeenCalledTimes(1);
      expect(toastSpy).toHaveBeenCalledWith('工作区同步失败，本地已保留（恢复后自动同步）');
      expect(assist.visible).toBe(false);
    });

    it('提交中拒绝重入（single-flight：双击只保存一次）', async () => {
      const workspace = useWorkspaceStore();
      workspace.workspaceSynced = true;
      let resolveOnce: (value: unknown) => void = () => {};
      vi.stubGlobal(
        'fetch',
        vi.fn(
          async (_url: RequestInfo | URL, _init?: RequestInit) =>
            new Promise((resolve) => {
              resolveOnce = () =>
                resolve({ ok: true, status: 200, headers: { get: () => null }, json: async () => ({ revision: 2 }) });
            })
        )
      );
      const assist = useAssistStore();
      const makePlan = (suffix: number): Plan => ({
        id: `plan-600519-${suffix}`,
        code: '600519',
        direction: 'buy',
        entry: 10,
        stop: 9,
        target: 12,
        capital: 100000,
        position: 10,
        validity: '本周内',
        note: '',
        status: '执行中',
        triggered: {},
        createdAtMs: Date.now(),
      });
      const first = assist.confirmDraft(makePlan(1));
      const second = assist.confirmDraft(makePlan(2));
      resolveOnce({ revision: 2 });
      const [firstResult, secondResult] = await Promise.all([first, second]);
      expect(firstResult).toBe('saved');
      expect(secondResult).toBe('error');
      expect(workspace.plans.filter((plan) => plan.code === '600519')).toHaveLength(1);
    });

    it('未自选代码确认后自动加入自选', async () => {
      const workspace = useWorkspaceStore();
      workspace.watchlistCodes = ['000001'];
      vi.stubGlobal(
        'fetch',
        vi.fn(async (_url: RequestInfo | URL, _init?: RequestInit) => jsonResponse({ revision: 2 }))
      );
      const assist = useAssistStore();
      await assist.confirmDraft({ ...basePlan, code: '600519', id: 'plan-600519-9' });
      expect(workspace.watchlistCodes).toContain('600519');
      expect(workspace.watchlistCodes).toContain('000001');
    });
  });

  describe('close', () => {
    it('提交中不可关闭，空闲时可关闭', async () => {
      const assist = useAssistStore();
      assist.visible = true;
      assist.submitting = true;
      assist.close();
      expect(assist.visible).toBe(true);
      assist.submitting = false;
      assist.close();
      expect(assist.visible).toBe(false);
    });
  });

  describe('设置接线（settingsDraft 4 键）', () => {
    it('openFor 前暴露 assistDefaults：settingsDraft 未加载（空对象）→ 回退 1/2/atr/25 且不发起设置请求', () => {
      const settings = useSettingsStore();
      const workspace = useWorkspaceStore();
      const requestSpy = vi.spyOn(workspace, 'requestJson');
      // settingsDraft 为空对象（未加载）：逐键 Object.assign 覆盖为 undefined
      Object.assign(settings.settingsDraft, {
        riskPerTradePct: undefined,
        rrRatio: undefined,
        stopMode: undefined,
        positionCapPct: undefined,
        defaultCapital: undefined,
      });
      const assist = useAssistStore();
      const defaults = assist.assistDefaults;
      expect(defaults.riskPct).toBe(1);
      expect(defaults.rrRatio).toBe(2);
      expect(defaults.stopMode).toBe('atr');
      expect(defaults.capPct).toBe(25);
      expect(defaults.equity).toBe(100000);
      expect(requestSpy).not.toHaveBeenCalled();
    });

    it('settingsDraft 已加载 → assistDefaults 逐键镜像（equity 取 defaultCapital）', () => {
      const settings = useSettingsStore();
      Object.assign(settings.settingsDraft, {
        riskPerTradePct: 1.5,
        rrRatio: 3,
        stopMode: 'ma20',
        positionCapPct: 40,
        defaultCapital: 200000,
      });
      const assist = useAssistStore();
      expect(assist.assistDefaults).toEqual({ riskPct: 1.5, rrRatio: 3, stopMode: 'ma20', capPct: 40, equity: 200000 });
    });
  });
});
