import { defineStore } from 'pinia';
import { computed, nextTick, reactive } from 'vue';
import { expiredPlans } from '@/modules/planUtils';
import { signalText as signalTextFor, signalClass as signalClassFor } from '@/modules/signalUtils';
import { useWorkspaceStore } from './useWorkspaceStore';
import { useQuotesStore } from './useQuotesStore';
import { useScreenerStore } from './useScreenerStore';
import { useAlertsStore } from './useAlertsStore';

/**
 * 交易计划 store：草稿 / 计划 CRUD / 触发检查 / 过期归档 / 测算。
 * 行为与重构前 app.ts setup() 对应域一致（字段名逐字保持）。
 */
export const usePlansStore = defineStore('plans', () => {
  const workspace = useWorkspaceStore();
  const quotes = useQuotesStore();
  const draft = reactive({
    code: quotes.selectedCode,
    direction: 'buy',
    validity: '本周内',
    entry: 0,
    stop: 0,
    target: 0,
    capital: 100000,
    position: 30,
    note: '',
  });

  const planOptions = computed(() => {
    const map = new Map();
    [...quotes.market.quotes, ...useScreenerStore().screenRows, ...quotes.watchlistQuotes].forEach((stock) => {
      if (stock?.code) map.set(stock.code, stock);
    });
    if (!map.has(quotes.selectedCode)) {
      map.set(quotes.selectedCode, {
        code: quotes.selectedCode,
        name: quotes.selectedCode,
        exchange: '未知',
        board: '未知',
        market: '未知',
      });
    }
    return [...map.values()];
  });

  const planMetrics = computed(() => {
    const entry = Number(draft.entry) || 0;
    const stop = Number(draft.stop) || 0;
    const target = Number(draft.target) || 0;
    const budget = (Number(draft.capital) || 0) * ((Number(draft.position) || 0) / 100);
    const shares = entry > 0 ? Math.max(0, Math.floor(budget / entry / 100) * 100) : 0;
    const risk = Math.max(0, (entry - stop) * shares);
    const rr = entry > stop ? Math.max(0, target - entry) / Math.max(0.01, entry - stop) : 0;
    return { shares, risk, rr };
  });

  function planFor(code: string) {
    return workspace.activePlans.find((plan) => plan.code === code) || null;
  }

  // 视图仍以单参调用，薄适配层委托纯模块（ctx API 不变）
  function signalText(stock: any) {
    return signalTextFor(stock, planFor(stock?.code));
  }
  function signalClass(stock: any) {
    return signalClassFor(signalTextFor(stock, planFor(stock?.code)));
  }

  function hydrateDraft() {
    const stock = quotes.quoteFor(draft.code) || quotes.quoteFor(quotes.selectedCode);
    if (!stock?.price) return;
    workspace.draftWatchSuppressed = true;
    draft.entry = Number(stock.price.toFixed(2));
    draft.stop = Number((stock.price * 0.95).toFixed(2));
    draft.target = Number((stock.price * 1.08).toFixed(2));
    nextTick(() => {
      workspace.draftWatchSuppressed = false;
    });
  }

  function createPlan(code?: string) {
    quotes.selectedCode = code || quotes.selectedCode;
    draft.code = quotes.selectedCode;
    hydrateDraft();
    workspace.draftDirty = false;
    quotes.view = 'plans';
    workspace.persist();
    nextTick(workspace.renderIcons);
  }

  function savePlan() {
    if (
      !draft.code ||
      !draft.entry ||
      !draft.stop ||
      !draft.target ||
      draft.stop >= draft.entry ||
      draft.target <= draft.entry
    ) {
      workspace.showToast('请检查计划价、止损价和目标价的关系', 'error');
      return;
    }
    const stock = quotes.quoteFor(draft.code);
    const plan = {
      id: `plan-${draft.code}-${Date.now()}`,
      code: draft.code,
      direction: draft.direction,
      entry: Number(draft.entry),
      stop: Number(draft.stop),
      target: Number(draft.target),
      capital: Number(draft.capital),
      position: Number(draft.position),
      validity: draft.validity,
      note: draft.note || '未填写交易逻辑',
      status: '执行中',
      createdAt: formatTimeNow().slice(0, 5),
      createdAtMs: Date.now(),
      triggered: {},
    };
    workspace.plans.unshift(plan as any);
    if (!quotes.isWatched(plan.code)) workspace.watchlistCodes.push(plan.code);
    useAlertsStore().addAlert(
      'success',
      `${stock?.name || plan.code} 交易计划已保存`,
      `计划价 ${formatNumber(plan.entry)}，止损 ${formatNumber(plan.stop)}，目标 ${formatNumber(plan.target)}。`
    );
    workspace.draftDirty = false;
    workspace.persist();
    workspace.showToast('交易计划已保存');
  }

  function formatTimeNow() {
    return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
  }
  function formatNumber(value: number) {
    return value != null ? Number(value).toFixed(2) : '--';
  }

  function archivePlan(id: string) {
    const plan = workspace.plans.find((item) => item.id === id);
    if (!plan) return;
    plan.status = '已归档';
    workspace.persist();
    workspace.showToast('计划已归档');
  }

  function monitorPlan(plan: any) {
    quotes.selectedCode = plan.code;
    quotes.view = 'monitor';
    workspace.persist();
    nextTick(workspace.renderIcons);
  }

  function checkPlanTriggers() {
    workspace.activePlans.forEach((plan) => {
      const quote = quotes.quoteFor(plan.code);
      if (!quote || quote.price === null || quote.price === undefined) return;
      plan.triggered = plan.triggered || {};
      if (quote.price <= plan.stop && !plan.triggered.stop) {
        plan.triggered.stop = true;
        plan.status = '已触发';
        useAlertsStore().addAlert(
          'alert',
          `${quote.name}触及止损线`,
          `最新价 ${formatNumber(quote.price)}，请确认是否执行止损规则。`
        );
      } else if (quote.price >= plan.target && !plan.triggered.target) {
        plan.triggered.target = true;
        plan.status = '已触发';
        useAlertsStore().addAlert(
          'success',
          `${quote.name}触及目标价`,
          `最新价 ${formatNumber(quote.price)}，请确认是否分批止盈。`
        );
      } else if (quote.price <= plan.entry && !plan.triggered.entry) {
        plan.triggered.entry = true;
        useAlertsStore().addAlert(
          'success',
          `${quote.name}触及计划买入价`,
          `最新价 ${formatNumber(quote.price)}，已进入计划价附近。`
        );
      }
    });
  }

  function expirePlans() {
    const expired = expiredPlans(workspace.plans, Date.now());
    if (expired.length) {
      workspace.plans = workspace.plans.map((p) =>
        expired.find((e) => e.id === p.id) ? { ...p, status: '已过期' } : p
      );
      useAlertsStore().addAlert('info', '有交易计划已到期', `${expired.length} 份计划超过有效期，已自动归档为已过期。`);
      workspace.persist();
    }
  }

  return {
    draft,
    planOptions,
    planMetrics,
    planFor,
    signalText,
    signalClass,
    hydrateDraft,
    createPlan,
    savePlan,
    archivePlan,
    monitorPlan,
    checkPlanTriggers,
    expirePlans,
  };
});
