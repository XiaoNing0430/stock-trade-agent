import { defineStore } from 'pinia';
import { computed, nextTick, ref, reactive } from 'vue';
import { STRATEGY_SCHEMAS, STRATEGY_TYPES as STRATEGY_TYPES_LIST } from '@/modules/constants';
import { useWorkspaceStore } from './useWorkspaceStore';
import { useQuotesStore } from './useQuotesStore';
import { useAlertsStore } from './useAlertsStore';

/**
 * 策略 store：多类型策略草稿 / 回测 / 策略 CRUD。
 * 行为与重构前 app.ts setup() 对应域一致（字段名逐字保持）。
 */
export const useStrategyStore = defineStore('strategy', () => {
  const workspace = useWorkspaceStore();
  const quotes = useQuotesStore();
  const strategyType = ref('grid');
  const strategyLoading = ref(false);
  const strategySuggestion = ref<any>(null);
  const strategyResult = ref<any>(null);
  const strategies = ref<any[]>([]);
  // storeToRefs 只解构 ref/reactive/computed——普通常量数组需用 ref 包装，
  // 否则 ViewGrid 中解构出的 STRATEGY_TYPES 为 undefined 导致策略 tab 不渲染。
  const STRATEGY_TYPES = ref(STRATEGY_TYPES_LIST);
  const strategyDraft = reactive({
    id: '',
    code: quotes.selectedCode,
    name: '',
    capital: 100000,
    feeBps: 3,
    schedule: 'manual',
    lookback: 120,
    config: {} as Record<string, any>,
  });

  const strategySchema = computed(() => STRATEGY_SCHEMAS[strategyType.value] || []);
  const normalizedStrategyCode = computed(() => String(strategyDraft.code || '').trim());
  const strategyInstrument = computed(() => quotes.quoteFor(normalizedStrategyCode.value));
  const hasStrategyResult = computed(() => Boolean(strategyResult.value));
  const strategyTypeLabel = computed(
    () => (STRATEGY_TYPES.value.find((item) => item.id === strategyType.value) || {}).label || '策略'
  );

  const strategyProvenance = computed(() => {
    const result = strategyResult.value;
    if (!result || !Array.isArray(result.history) || !result.history.length) return '';
    const first = result.history[0]?.date || '--';
    const last = result.history[result.history.length - 1]?.date || '--';
    const src = result.dataSource === 'local' ? '本地缓存' : quotes.providerLabel;
    return `数据区间 ${first} ~ ${last} · ${result.history.length} 个交易日 · 前复权日线 · 来源 ${src} · 数据截止 ${result.config?.dataAsOf || last}`;
  });

  const strategyStats = computed(() => {
    const running = useGridStore().gridStrategies.filter((strategy) => strategy.status === '启用');
    const now = Date.now();
    const pending = running.filter(
      (strategy) => !strategy.lastBacktestAt || now - new Date(strategy.lastBacktestAt).getTime() > 24 * 3600 * 1000
    );
    const withExcess = useGridStore().gridStrategies.filter(
      (strategy) => strategy.latestMetrics && strategy.latestMetrics.excessReturnPct != null
    );
    return {
      running: running.length,
      pending: pending.length,
      latestExcess: withExcess.length ? withExcess[0].latestMetrics.excessReturnPct : null,
    };
  });

  const riskStats = computed(() => {
    const stopHit = workspace.activePlans.filter((plan) => {
      if (plan.triggered && plan.triggered.stop) return true;
      const quote = quotes.quoteFor(plan.code);
      return quote && quote.price != null && quote.price <= plan.stop;
    }).length;
    return { active: workspace.activePlans.length, stopHit, unread: workspace.unreadAlerts };
  });

  function switchStrategyType(type: string) {
    if (type === strategyType.value) return;
    strategyType.value = type;
    strategyResult.value = null;
    strategySuggestion.value = null;
    if (type !== 'grid') {
      strategyDraft.code = strategyDraft.code || quotes.selectedCode;
      strategyDraft.id = '';
      strategyDraft.config = {};
      strategySchema.value.forEach((field) => {
        strategyDraft.config[field.key] = field.default;
      });
    }
    nextTick(workspace.renderIcons);
  }

  async function previewStrategy() {
    strategyLoading.value = true;
    try {
      const payload = await workspace.requestJson('/api/strategy/preview', {
        method: 'POST',
        body: JSON.stringify({ strategyType: strategyType.value, config: strategyDraft.config }),
      });
      strategySuggestion.value = payload.suggestion || null;
      if (payload.suggestion) {
        Object.keys(payload.suggestion).forEach((key) => {
          if (payload.suggestion[key] !== undefined) strategyDraft.config[key] = payload.suggestion[key];
        });
      }
      strategyResult.value = null;
      workspace.showToast(`已填入 ${strategyTypeLabel.value} 默认参数，可调整后回测`);
    } catch (error: any) {
      workspace.showToast(error.message || '无法生成策略建议', 'error');
    } finally {
      strategyLoading.value = false;
    }
  }

  async function backtestStrategy(save = false) {
    if (save && !hasStrategyResult.value) {
      workspace.showToast('请先运行回测，再保存策略', 'error');
      return;
    }
    strategyLoading.value = true;
    try {
      const payload = await workspace.requestJson('/api/strategy/backtest', {
        method: 'POST',
        body: JSON.stringify({
          ...strategyDraft,
          strategyType: strategyType.value,
          config: strategyDraft.config,
          save,
        }),
      });
      strategyResult.value = payload;
      if (payload.strategy) {
        strategyDraft.id = payload.strategy.id;
        await loadStrategies();
      }
      workspace.showToast(
        save ? `${strategyTypeLabel.value}策略已保存并记录回测` : `${strategyTypeLabel.value}回测完成`
      );
    } catch (error: any) {
      workspace.showToast(error.message || `${strategyTypeLabel.value}回测失败`, 'error');
      if (save)
        useAlertsStore().addAlert('system', `${strategyTypeLabel.value}策略保存失败`, error.message || '未知错误');
    } finally {
      strategyLoading.value = false;
    }
  }

  async function loadStrategies() {
    try {
      const payload = await workspace.requestJson('/api/strategy/strategies');
      strategies.value = payload.strategies || [];
    } catch {
      strategies.value = [];
    }
  }

  function loadStrategy(strategy: any) {
    Object.assign(strategyDraft, {
      id: strategy.id,
      code: strategy.code,
      name: strategy.name,
      capital: strategy.capital,
      feeBps: strategy.feeBps,
      schedule: strategy.schedule,
      lookback: strategy.config?.lookback || 120,
      config: { ...(strategy.config || {}) },
    });
    strategyType.value = strategy.strategyType;
    strategyResult.value = null;
    strategySuggestion.value = null;
    workspace.showToast(`已载入 ${strategy.name}`);
    nextTick(workspace.renderIcons);
  }

  async function toggleStrategy(strategy: any) {
    const status = strategy.status === '启用' ? '暂停' : '启用';
    try {
      await workspace.requestJson(`/api/strategy/strategies/${encodeURIComponent(strategy.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      });
      await loadStrategies();
    } catch (error: any) {
      workspace.showToast(error.message || '更新策略状态失败', 'error');
    }
  }

  async function deleteStrategy(strategy: any) {
    if (!window.confirm(`删除策略“${strategy.name}”及其回测记录？`)) return;
    try {
      await workspace.requestJson(`/api/strategy/strategies/${encodeURIComponent(strategy.id)}`, { method: 'DELETE' });
      if (strategyDraft.id === strategy.id) strategyDraft.id = '';
      await loadStrategies();
      workspace.showToast('策略及其回测记录已删除');
    } catch (error: any) {
      workspace.showToast(error.message || '删除策略失败', 'error');
    }
  }

  async function openStrategy(type: string, code: string) {
    switchStrategyType(type || 'ma_cross');
    if (/^\d{6}$/.test(String(code || '').trim())) {
      quotes.selectedCode = String(code).trim();
      strategyDraft.code = String(code).trim();
      strategyDraft.id = '';
      strategyResult.value = null;
    }
    quotes.view = 'grid';
    workspace.persist();
    await nextTick();
    workspace.renderIcons();
  }

  return {
    strategyType,
    strategyLoading,
    strategySuggestion,
    strategyResult,
    strategies,
    strategyDraft,
    strategySchema,
    normalizedStrategyCode,
    strategyInstrument,
    hasStrategyResult,
    strategyTypeLabel,
    strategyProvenance,
    strategyStats,
    riskStats,
    STRATEGY_SCHEMAS,
    STRATEGY_TYPES,
    switchStrategyType,
    previewStrategy,
    backtestStrategy,
    loadStrategies,
    loadStrategy,
    toggleStrategy,
    deleteStrategy,
    openStrategy,
  };
});

import { useGridStore } from './useGridStore';
