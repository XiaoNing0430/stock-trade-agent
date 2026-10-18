import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { multiLineSvg, type MultiLineSeries } from '@/modules/chart';
import { COMPARE_STRATEGY_TYPES, STRATEGY_TYPES as STRATEGY_TYPES_LIST } from '@/modules/constants';
import {
  buildCompareCurvesCsv,
  buildCompareMetricsCsv,
  buildCompareTradesCsv,
  downloadCsv,
  summarizeConfig,
  type CompareMetricRow,
} from '@/modules/csv';
import { useWorkspaceStore } from './useWorkspaceStore';
import { useGridStore } from './useGridStore';
import { useStrategyStore } from './useStrategyStore';

export type CompareExportKind = 'metrics' | 'curves' | 'trades';
export type CompareSavedMode = 'snapshot' | 'rerun';

const COMPARE_COLORS = [
  'var(--chart-1)',
  'var(--chart-2)',
  'var(--chart-3)',
  'var(--chart-4)',
  'var(--chart-5)',
  'var(--chart-6)',
  'var(--chart-7)',
  'var(--chart-8)',
];
const COMPARE_SAVED_LIMIT = 10;

/**
 * 多策略对比 store：同标的横向对比 + 已保存策略对比（快照/rerun）。
 * 对比结果纯内存不落库（spec §2 非目标）；CSV 组装全部委托 modules/csv。
 */
export const useCompareStore = defineStore('compare', () => {
  const workspace = useWorkspaceStore();
  const runLoading = ref(false);
  const runResult = ref<any>(null);
  const selectedTypes = ref<string[]>(COMPARE_STRATEGY_TYPES.map((item) => item.id));
  const compareDraft = ref({ code: '', lookback: 120, capital: 100000, feeBps: 3 });
  const savedLoading = ref(false);
  const savedResult = ref<any>(null);
  const savedSelection = ref<string[]>([]);

  function toggleType(id: string) {
    selectedTypes.value = selectedTypes.value.includes(id)
      ? selectedTypes.value.filter((item) => item !== id)
      : [...selectedTypes.value, id];
  }

  async function runCompare() {
    if (!selectedTypes.value.length) {
      workspace.showToast('至少勾选一个策略类型', 'error');
      return;
    }
    runLoading.value = true;
    try {
      const payload = await workspace.requestJson('/api/strategy/compare', {
        method: 'POST',
        body: JSON.stringify({ ...compareDraft.value, strategyTypes: selectedTypes.value }),
      });
      runResult.value = payload;
      workspace.showToast('对比完成');
    } catch (error: any) {
      workspace.showToast(error.message || '策略对比失败', 'error');
    } finally {
      runLoading.value = false;
    }
  }

  const runSeries = computed<MultiLineSeries[]>(() => {
    const run = runResult.value;
    if (!run) return [];
    const series: MultiLineSeries[] = (run.results || [])
      .filter((item: any) => Array.isArray(item.equityCurve))
      .map((item: any, index: number) => ({
        label: String(item.label || item.strategyType),
        points: item.equityCurve.map((point: any) => (typeof point?.equity === 'number' ? point.equity : null)),
        style: 'solid' as const,
        color: COMPARE_COLORS[index % COMPARE_COLORS.length],
      }));
    if (Array.isArray(run.benchmarkCurve)) {
      series.push({
        label: '基准',
        points: run.benchmarkCurve.map((point: any) => (typeof point?.equity === 'number' ? point.equity : null)),
        style: 'dash',
        color: 'var(--chart-baseline)',
      });
    }
    return series;
  });

  const runChartSvg = computed(() =>
    runSeries.value.length
      ? multiLineSvg(runSeries.value, { height: 220, legend: true, ariaLabel: '多策略归一化净值对比' })
      : ''
  );

  function bestValue(key: string, mode: 'max' | 'min'): number | null {
    const run = runResult.value;
    if (!run) return null;
    const values = (run.results || [])
      .map((item: any) => item?.metrics?.[key])
      .filter((value: any) => typeof value === 'number');
    if (!values.length) return null;
    return mode === 'max' ? Math.max(...values) : Math.min(...values);
  }

  function isBest(item: any, key: string, mode: 'max' | 'min'): boolean {
    const value = item?.metrics?.[key];
    if (typeof value !== 'number') return false;
    const best = bestValue(key, mode);
    return best !== null && value === best;
  }

  const savedOptions = computed(() => {
    const grid = useGridStore().gridStrategies.map((strategy: any) => ({
      key: String(strategy.id),
      id: String(strategy.id),
      name: String(strategy.name || ''),
      code: String(strategy.code || ''),
      typeLabel: strategy.mode === 'trend' ? '趋势网格' : '经典网格',
      status: String(strategy.status || ''),
      lastBacktestAt: strategy.lastBacktestAt || null,
    }));
    const generic = useStrategyStore().strategies.map((strategy: any) => ({
      key: String(strategy.id),
      id: String(strategy.id),
      name: String(strategy.name || ''),
      code: String(strategy.code || ''),
      typeLabel:
        (STRATEGY_TYPES_LIST.find((item) => item.id === strategy.strategyType) || {}).label ||
        String(strategy.strategyType || ''),
      status: String(strategy.status || ''),
      lastBacktestAt: strategy.lastBacktestAt || null,
    }));
    return [...grid, ...generic];
  });

  function toggleSaved(key: string) {
    savedSelection.value = savedSelection.value.includes(key)
      ? savedSelection.value.filter((item) => item !== key)
      : savedSelection.value.length >= COMPARE_SAVED_LIMIT
        ? savedSelection.value
        : [...savedSelection.value, key];
  }

  /** 全选已保存策略（截断到对比上界 10，spec §3.2）。 */
  function selectAllSaved() {
    savedSelection.value = savedOptions.value.slice(0, COMPARE_SAVED_LIMIT).map((option) => option.key);
  }

  /** 清空已保存策略勾选。 */
  function clearSavedSelection() {
    savedSelection.value = [];
  }

  async function compareSaved(mode: CompareSavedMode) {
    if (!savedSelection.value.length) {
      workspace.showToast('至少选择一个已保存策略', 'error');
      return;
    }
    savedLoading.value = true;
    try {
      const payload = await workspace.requestJson('/api/strategy/compare-saved', {
        method: 'POST',
        body: JSON.stringify({ mode, ids: savedSelection.value }),
      });
      savedResult.value = payload;
      workspace.showToast(mode === 'rerun' ? '现跑对比完成' : '快照对比完成');
    } catch (error: any) {
      workspace.showToast(error.message || '已保存策略对比失败', 'error');
    } finally {
      savedLoading.value = false;
    }
  }

  function _metricRows(results: any[]): CompareMetricRow[] {
    return (results || [])
      .filter((item: any) => item && item.found !== false && !item.error)
      .map((item: any) => ({
        label: String(item.label || item.name || item.strategyType),
        type: String(item.strategyType || item.source || ''),
        params: summarizeConfig(item.config),
        metrics: item.metrics ?? null,
      }));
  }

  function exportRunCsv(kind: CompareExportKind) {
    const run = runResult.value;
    if (!run) return;
    if (kind === 'metrics') {
      downloadCsv(`atlas-compare-metrics-${Date.now()}.csv`, buildCompareMetricsCsv(_metricRows(run.results || [])));
    } else if (kind === 'curves') {
      downloadCsv(`atlas-compare-curves-${Date.now()}.csv`, buildCompareCurvesCsv(run));
    } else {
      downloadCsv(
        `atlas-compare-trades-${Date.now()}.csv`,
        buildCompareTradesCsv(
          (run.results || [])
            .filter((item: any) => !item.error)
            .map((item: any) => ({ label: String(item.label || item.strategyType), trades: item.trades }))
        )
      );
    }
    workspace.showToast('CSV 已导出');
  }

  function exportSavedCsv(kind: CompareExportKind) {
    const saved = savedResult.value;
    if (!saved) return;
    if (kind === 'trades' && !saved.rerun) {
      workspace.showToast('快照模式无成交明细，请先用「重新回测并对比」', 'error');
      return;
    }
    if (kind === 'metrics') {
      downloadCsv(`atlas-compare-metrics-${Date.now()}.csv`, buildCompareMetricsCsv(_metricRows(saved.results || [])));
    } else if (kind === 'trades') {
      downloadCsv(
        `atlas-compare-trades-${Date.now()}.csv`,
        buildCompareTradesCsv(
          (saved.results || [])
            .filter((item: any) => !item.error)
            .map((item: any) => ({ label: String(item.name || item.id), trades: item.trades }))
        )
      );
    }
    // saved 模式无 curves 导出（spec §5）
    workspace.showToast('CSV 已导出');
  }

  return {
    runLoading,
    runResult,
    selectedTypes,
    compareDraft,
    savedLoading,
    savedResult,
    savedSelection,
    runChartSvg,
    savedOptions,
    toggleType,
    runCompare,
    toggleSaved,
    selectAllSaved,
    clearSavedSelection,
    compareSaved,
    isBest,
    exportRunCsv,
    exportSavedCsv,
  };
});
