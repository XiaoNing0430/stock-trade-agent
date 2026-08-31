import { defineStore } from 'pinia';
import { computed, nextTick, ref, reactive } from 'vue';
import { useWorkspaceStore } from './useWorkspaceStore';
import { useQuotesStore } from './useQuotesStore';

/**
 * 网格策略 store：网格草稿 / 回测 / 优化 / 策略 CRUD。
 * 行为与重构前 app.ts setup() 对应域一致（字段名逐字保持）。
 */
export const useGridStore = defineStore('grid', () => {
  const workspace = useWorkspaceStore();
  const quotes = useQuotesStore();
  const gridDraft = reactive({
    id: '',
    code: quotes.selectedCode,
    name: '',
    lookback: 120,
    gridCount: 8,
    lower: 0,
    upper: 0,
    capital: 100000,
    feeBps: 3,
    mode: 'classic',
    settlementDays: 1,
    slippageBps: 5,
    schedule: 'daily',
  });
  const gridLoading = ref(false);
  const gridSuggestion = ref<any>(null);
  const gridResult = ref<any>(null);
  const gridCandidates = ref<any[]>([]);
  const gridStrategies = ref<any[]>([]);
  const gridSuggestedCode = ref('');

  const normalizedGridCode = computed(() => String(gridDraft.code || '').trim());
  const gridInstrument = computed(() => quotes.quoteFor(normalizedGridCode.value));
  const hasGridSuggestion = computed(
    () => Boolean(gridSuggestion.value) && gridSuggestedCode.value === normalizedGridCode.value
  );
  const hasGridResult = computed(() => Boolean(gridResult.value));

  const gridProvenance = computed(() => {
    const result = gridResult.value;
    if (!result || !Array.isArray(result.history) || !result.history.length) return '';
    const first = result.history[0]?.date || '--';
    const last = result.history[result.history.length - 1]?.date || '--';
    const metrics = result.metrics || {};
    const src = result.dataSource === 'local' ? '本地缓存' : quotes.providerLabel;
    const parts = [
      `数据区间 ${first} ~ ${last}`,
      `${result.history.length} 个交易日`,
      '前复权日线',
      `来源 ${src}`,
      `数据截止 ${result.config?.dataAsOf || last}`,
      `涨跌停跳过 ${metrics.skippedLimitUpDays ?? 0}/${metrics.skippedLimitDownDays ?? 0}`,
      `一字板 ${metrics.onePriceLimitUpDays ?? 0}/${metrics.onePriceLimitDownDays ?? 0}`,
      `停牌 ${metrics.skippedSuspensionDays ?? 0}`,
    ];
    return parts.join(' · ');
  });

  async function previewGrid() {
    const code = normalizedGridCode.value;
    if (!/^\d{6}$/.test(code)) {
      workspace.showToast('请输入 6 位股票或 ETF 代码', 'error');
      return;
    }
    gridLoading.value = true;
    try {
      await quotes.ensureQuote(code);
      const payload = await workspace.requestJson('/api/grid/preview', {
        method: 'POST',
        body: JSON.stringify(gridDraft),
      });
      gridDraft.lower = payload.suggestion.lower;
      gridDraft.upper = payload.suggestion.upper;
      gridDraft.capital = payload.suggestion.suggestedCapital;
      gridSuggestion.value = payload.suggestion;
      gridSuggestedCode.value = code;
      gridResult.value = null;
      workspace.showToast('已根据历史波动生成网格区间');
    } catch (error: any) {
      workspace.showToast(error.message || '无法生成网格区间', 'error');
    } finally {
      gridLoading.value = false;
    }
  }

  async function backtestGrid(save = false) {
    if (save && !hasGridResult.value) {
      workspace.showToast('请先运行回测，再保存策略', 'error');
      return;
    }
    gridLoading.value = true;
    try {
      const payload = await workspace.requestJson('/api/grid/backtest', {
        method: 'POST',
        body: JSON.stringify({ ...gridDraft, save }),
      });
      gridResult.value = payload;
      if (payload.strategy) {
        gridDraft.id = payload.strategy.id;
        await loadGridStrategies();
      }
      workspace.showToast(save ? '网格策略已保存并记录回测' : '网格回测完成');
    } catch (error: any) {
      workspace.showToast(error.message || '网格回测失败', 'error');
      if (save) useAlertsStore().addAlert('system', '网格策略保存失败', error.message || '未知错误');
    } finally {
      gridLoading.value = false;
    }
  }

  async function optimizeGrid() {
    gridLoading.value = true;
    try {
      const payload = await workspace.requestJson('/api/grid/optimize', {
        method: 'POST',
        body: JSON.stringify(gridDraft),
      });
      gridCandidates.value = payload.candidates || [];
      const best = gridCandidates.value[0];
      if (best) {
        gridDraft.gridCount = best.gridCount;
        gridDraft.lower = best.lower;
        gridDraft.upper = best.upper;
      }
      workspace.showToast(
        best?.recommended ? '已选出历史回测表现最优的参数' : '已填入最优候选（暂不推荐，请查看稳健性标记）'
      );
    } catch (error: any) {
      workspace.showToast(error.message || '参数优化失败', 'error');
    } finally {
      gridLoading.value = false;
    }
  }

  async function loadGridStrategies() {
    try {
      const payload = await workspace.requestJson('/api/grid/strategies');
      gridStrategies.value = payload.strategies || [];
    } catch {
      gridStrategies.value = [];
    }
  }

  function loadGridStrategy(strategy: any) {
    Object.assign(gridDraft, {
      id: strategy.id,
      code: strategy.code,
      name: strategy.name,
      lookback: strategy.lookback,
      gridCount: strategy.gridCount,
      lower: strategy.lower,
      upper: strategy.upper,
      capital: strategy.capital,
      feeBps: strategy.feeBps,
      mode: strategy.mode,
      settlementDays: strategy.settlementDays,
      slippageBps: strategy.slippageBps,
      schedule: strategy.schedule,
    });
    gridSuggestion.value = null;
    gridSuggestedCode.value = '';
    gridResult.value = null;
    workspace.showToast(`已载入 ${strategy.name}`);
  }

  async function toggleGridStrategy(strategy: any) {
    const status = strategy.status === '启用' ? '暂停' : '启用';
    try {
      await workspace.requestJson(`/api/grid/strategies/${encodeURIComponent(strategy.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ status }),
      });
      await loadGridStrategies();
    } catch (error: any) {
      workspace.showToast(error.message || '更新策略状态失败', 'error');
    }
  }

  async function deleteGridStrategy(strategy: any) {
    if (!window.confirm(`删除策略“${strategy.name}”及其回测记录？`)) return;
    try {
      await workspace.requestJson(`/api/grid/strategies/${encodeURIComponent(strategy.id)}`, { method: 'DELETE' });
      if (gridDraft.id === strategy.id) gridDraft.id = '';
      await loadGridStrategies();
      workspace.showToast('策略及其回测记录已删除');
    } catch (error: any) {
      workspace.showToast(error.message || '删除策略失败', 'error');
    }
  }

  async function openGridStrategy(code: string = quotes.selectedCode) {
    useStrategyStore().strategyType = 'grid';
    const normalizedCode = String(code || '').trim();
    if (/^\d{6}$/.test(normalizedCode)) {
      quotes.selectedCode = normalizedCode;
      gridDraft.code = normalizedCode;
      gridDraft.id = '';
      gridResult.value = null;
      gridCandidates.value = [];
      if (gridSuggestedCode.value !== normalizedCode) gridSuggestion.value = null;
    }
    quotes.view = 'grid';
    workspace.persist();
    await nextTick();
    workspace.renderIcons();
    if (/^\d{6}$/.test(normalizedCode) && !gridLoading.value && !hasGridSuggestion.value) {
      await previewGrid();
    }
  }

  async function restoreGridSuggestion() {
    if (quotes.view !== 'grid' || gridLoading.value || hasGridSuggestion.value || hasGridResult.value) return;
    if (!/^\d{6}$/.test(normalizedGridCode.value)) return;
    await previewGrid();
  }

  return {
    gridDraft,
    gridLoading,
    gridSuggestion,
    gridResult,
    gridCandidates,
    gridStrategies,
    gridSuggestedCode,
    normalizedGridCode,
    gridInstrument,
    hasGridSuggestion,
    hasGridResult,
    gridProvenance,
    previewGrid,
    backtestGrid,
    optimizeGrid,
    loadGridStrategies,
    loadGridStrategy,
    toggleGridStrategy,
    deleteGridStrategy,
    openGridStrategy,
    restoreGridSuggestion,
  };
});

import { useAlertsStore } from './useAlertsStore';
import { useStrategyStore } from './useStrategyStore';
