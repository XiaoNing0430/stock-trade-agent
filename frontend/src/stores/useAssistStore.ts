import { defineStore } from 'pinia';
import { ref } from 'vue';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { formatNumber } from '@/modules/format';
import { priceLimitRatio, selectStop, sizePositionAtStop } from '@/modules/assistCalc';
import type { SizingOutput } from '@/modules/assistCalc';
import type { AssistDraft, Plan } from '@/types/models';

/** 对话框调参输入（组件本地态，确认 / 调参时经 recalc 注入纯函数，零 API）。 */
export interface AssistRecalcInput {
  entry: number;
  stopMode: 'atr' | 'ma20';
  rrRatio: number;
  riskPct: number;
  capPct: number;
  manualStop: number | null;
  equity: number;
}

/**
 * 交易辅助 store：草案获取（openFor）→ 本地调参重算（recalc，纯 assistCalc）→ 确认落计划（confirmDraft）。
 * confirmDraft 接收与 usePlansStore.savePlan 完全同形的 plan（额外容忍 createdAt 显示串），
 * 本地入列 → workspace.syncNow() 立即 PUT；409 回滚（绝不自动重试），非 409 失败本地保留。
 */
export const useAssistStore = defineStore('assist', () => {
  const workspace = useWorkspaceStore();
  const visible = ref(false);
  const loading = ref(false);
  const submitting = ref(false);
  const error = ref('');
  const draft = ref<AssistDraft | null>(null);
  const suggestion = ref<SizingOutput | null>(null);

  /** 草案统一入口：screener 行 / 个股详情快照携带价格与时间戳（null → 后端取实时价）。 */
  async function openFor(payload: { code: string; name?: string; price?: number | null; asOfMs?: number | null }) {
    visible.value = true;
    loading.value = true;
    error.value = '';
    draft.value = null;
    try {
      const result = await workspace.requestJson('/api/assist/plan-draft', {
        method: 'POST',
        body: JSON.stringify({
          code: payload.code,
          name: payload.name ?? null,
          entryPrice: payload.price ?? null,
          entryAsOfMs: payload.asOfMs ?? null,
        }),
      });
      // 响应包裹 {data: 草案}（与 /api/settings 的 data 包裹一致）
      draft.value = (result?.data ?? result) as AssistDraft;
    } catch (e: any) {
      const message = typeof e?.message === 'string' ? e.message : '';
      // 网络层失败（fetch 抛出）统一兜底文案；服务端 detail.error 中文信息原样透传
      error.value =
        e instanceof TypeError || /fetch failed|network/i.test(message) ? '草案生成失败' : message || '草案生成失败';
      workspace.showToast(error.value, 'error');
    } finally {
      loading.value = false;
    }
  }

  function close() {
    if (submitting.value) return;
    visible.value = false;
  }

  /** 调参重算（零 API）：手动止损优先（须 < 入场价），否则按模式选候选；结果同步到 suggestion。 */
  function recalc(input: AssistRecalcInput): SizingOutput | null {
    const current = draft.value;
    if (!current) {
      suggestion.value = null;
      return null;
    }
    const entry = Number(input.entry) || 0;
    const manual = input.manualStop;
    const stop =
      typeof manual === 'number' && Number.isFinite(manual) && manual < entry
        ? manual
        : selectStop(entry, current.atr14 ?? null, current.ma20 ?? null, input.stopMode).stop;
    const output = sizePositionAtStop({
      entry,
      stop,
      equity: input.equity,
      riskPct: input.riskPct,
      rrRatio: input.rrRatio,
      capPct: input.capPct,
      limitRatio: priceLimitRatio(current.code),
    });
    suggestion.value = output;
    return output;
  }

  /** 确认落计划：本地入列 → 立即 PUT；409 回滚 + 提示（绝不自动重试），其余失败本地保留。 */
  async function confirmDraft(plan: Plan & { createdAt?: string }): Promise<'saved' | 'conflict' | 'error'> {
    if (submitting.value) return 'error';
    submitting.value = true;
    try {
      workspace.plans.unshift(plan as Plan);
      if (!useQuotesStore().isWatched(plan.code)) workspace.watchlistCodes.push(plan.code);
      workspace.persist();
      const result = await workspace.syncNow();
      if (result.conflict) {
        const index = workspace.plans.findIndex((item) => item.id === plan.id);
        if (index >= 0) workspace.plans.splice(index, 1);
        workspace.persist();
        workspace.showToast('工作区有新变更，请刷新后重试', 'error');
        return 'conflict';
      }
      if (!result.ok) {
        // 同步正忙 / 服务暂不可用：本地已入列，恢复后由定时同步兜底
        workspace.showToast('工作区同步失败，本地已保留（恢复后自动同步）');
        visible.value = false;
        return 'error';
      }
      workspace.showToast(`交易计划已保存：${plan.code} ${formatNumber(plan.entry)} → ${formatNumber(plan.target)}`);
      visible.value = false;
      return 'saved';
    } finally {
      submitting.value = false;
    }
  }

  return { visible, loading, submitting, error, draft, suggestion, openFor, recalc, close, confirmDraft };
});
