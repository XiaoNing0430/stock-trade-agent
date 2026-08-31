import { defineStore } from 'pinia';
import { computed, nextTick, ref, reactive } from 'vue';
import { DEFAULT_FILTERS, PRESETS } from '@/modules/constants';
import { useWorkspaceStore } from './useWorkspaceStore';
import { useQuotesStore } from './useQuotesStore';

/**
 * 选股器 store：筛选结果 / 排序分页 / 预设 / 扫描。
 * 行为与重构前 app.ts setup() 对应域一致（字段名逐字保持）。
 */
export const useScreenerStore = defineStore('screener', () => {
  const workspace = useWorkspaceStore();
  const saved = workspace.loadStorage();
  const screenRows = ref<any[]>([]);
  const screenTotal = ref(0);
  const screenerUpdatedAt = ref(0);
  const screenerMode = ref('featured');
  const screenerAllRows = ref<any[]>([]);
  const screenerAllTotal = ref(0);
  const screenerPage = ref(1);
  const screenerSortBy = ref('changePct');
  const screenerSortDir = ref('desc');
  const screenerLoading = ref(false);
  const presetName = ref(saved.presetName || '趋势突破');
  const filters = reactive(Object.assign({}, DEFAULT_FILTERS, saved.filters || {}));

  if (saved.filters?.market === '沪A') {
    filters.exchange = '上交所';
    filters.market = '全部';
  } else if (saved.filters?.market === '深A') {
    filters.exchange = '深交所';
    filters.market = '全部';
  }

  const presets = ref(PRESETS);

  const presetHits = computed(() =>
    presets.value.map((preset) => ({
      name: preset.name,
      icon: preset.icon,
      iconClass: preset.iconClass,
      filters: preset.filters,
      count: screenRows.value.filter(
        (row) =>
          row.pe !== null &&
          row.pe <= preset.filters.peMax &&
          row.pb !== null &&
          row.pb <= preset.filters.pbMax &&
          row.volumeRatio !== null &&
          row.volumeRatio >= preset.filters.volumeMin &&
          row.change !== null &&
          row.change >= preset.filters.changeMin
      ).length,
    }))
  );

  const presetDescription = computed(() => {
    return presets.value.find((preset) => preset.name === presetName.value)?.description || '';
  });

  const filteredRows = computed(() => {
    const query = String(filters.search || '').toLowerCase();
    return screenRows.value
      .filter((row) => filters.exchange === '全部' || row.exchange === filters.exchange)
      .filter((row) => filters.market === '全部' || row.market === filters.market)
      .filter((row) => !query || `${row.code}${row.name}`.toLowerCase().includes(query))
      .filter((row) => row.pe !== null && row.pe <= Number(filters.peMax))
      .filter((row) => row.pb !== null && row.pb <= Number(filters.pbMax))
      .filter((row) => row.volumeRatio !== null && row.volumeRatio >= Number(filters.volumeMin))
      .filter((row) => row.change !== null && row.change >= Number(filters.changeMin))
      .sort((left, right) => right.change - left.change || (right.volumeRatio || 0) - (left.volumeRatio || 0));
  });

  const breadth = computed(() => {
    const rows = screenRows.value.filter((row) => row.change !== null);
    const up = rows.filter((row) => row.change > 0.1).length;
    const down = rows.filter((row) => row.change < -0.1).length;
    const flat = Math.max(0, rows.length - up - down);
    const total = Math.max(1, rows.length);
    return {
      up,
      down,
      flat,
      upRatio: Math.round((up / total) * 100),
      flatRatio: Math.round((flat / total) * 100),
      downRatio: Math.max(0, 100 - Math.round((up / total) * 100) - Math.round((flat / total) * 100)),
    };
  });

  const screenerUpdatedLabel = computed(() => formatDateShortForScreener(screenerUpdatedAt.value));

  function formatDateShortForScreener(ms: number) {
    return ms ? new Date(ms).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) : '--';
  }

  async function fetchScreener() {
    const payload = await workspace.requestJson(
      `/api/screener?market=${encodeURIComponent(filters.market)}&pageSize=300`
    );
    screenRows.value = payload.rows || [];
    screenTotal.value = Number(payload.total || screenRows.value.length);
    screenerUpdatedAt.value = payload.fetchedAt || Date.now();
  }

  async function fetchScreenerAll() {
    screenerLoading.value = true;
    try {
      const payload = await workspace.requestJson(
        `/api/screener/v2?page=${screenerPage.value}&pageSize=50&sortBy=${encodeURIComponent(screenerSortBy.value)}&sortDir=${screenerSortDir.value}`
      );
      screenerAllRows.value = payload.rows || [];
      screenerAllTotal.value = Number(payload.total || 0);
      screenerUpdatedAt.value = payload.fetchedAt || Date.now();
    } finally {
      screenerLoading.value = false;
    }
  }

  function switchScreenerMode(mode: string) {
    if (screenerMode.value === mode) return;
    screenerMode.value = mode;
    if (mode === 'all') {
      screenerPage.value = 1;
      fetchScreenerAll();
    } else {
      scanNow();
    }
  }

  function screenerSort(column: string) {
    if (screenerSortBy.value === column) {
      screenerSortDir.value = screenerSortDir.value === 'desc' ? 'asc' : 'desc';
    } else {
      screenerSortBy.value = column;
      screenerSortDir.value = 'desc';
    }
    screenerPage.value = 1;
    fetchScreenerAll();
  }

  function screenerPageUp() {
    const maxPage = Math.max(1, Math.ceil(screenerAllTotal.value / 50));
    if (screenerPage.value < maxPage) {
      screenerPage.value += 1;
      fetchScreenerAll();
    }
  }

  function screenerPageDown() {
    if (screenerPage.value > 1) {
      screenerPage.value -= 1;
      fetchScreenerAll();
    }
  }

  function screenerSortIcon(column: string) {
    if (screenerSortBy.value !== column) return '';
    return screenerSortDir.value === 'desc' ? '↓' : '↑';
  }

  async function scanNow() {
    if (screenerMode.value === 'all') {
      await fetchScreenerAll();
      workspace.showToast(`已刷新全市场排名，共 ${screenerAllTotal.value.toLocaleString()} 只`);
      return;
    }
    const quotes = useQuotesStore();
    quotes.loading = true;
    try {
      await fetchScreener();
      workspace.showToast(`扫描完成，共 ${filteredRows.value.length} 只结果`);
    } catch (error: any) {
      quotes.errorMessage = error.message;
      workspace.showToast('筛选接口暂时不可用', 'error');
    } finally {
      quotes.loading = false;
      await nextTick();
      workspace.renderIcons();
    }
  }

  function applyPreset(preset: any) {
    presetName.value = preset.name;
    Object.assign(filters, preset.filters);
    workspace.persist();
    scanNow();
  }

  function resetFilters() {
    presetName.value = '趋势突破';
    Object.assign(filters, DEFAULT_FILTERS);
    workspace.persist();
    scanNow();
  }

  function exportResults() {
    const header = ['代码', '名称', '市场', '现价', '涨跌幅', 'PE', 'PB', '量比', '换手率'];
    const rows = filteredRows.value.map((stock: any) => [
      stock.code,
      stock.name,
      stock.market,
      stock.price ?? '',
      stock.change ?? '',
      stock.pe ?? '',
      stock.pb ?? '',
      stock.volumeRatio ?? '',
      stock.turnoverRate ?? '',
    ]);
    const csv = [header, ...rows].map((row) => row.join(',')).join('\n');
    const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `atlas-screen-${Date.now()}.csv`;
    link.click();
    URL.revokeObjectURL(url);
    workspace.showToast('筛选结果已导出');
  }

  return {
    screenRows,
    screenTotal,
    screenerUpdatedAt,
    screenerMode,
    screenerAllRows,
    screenerAllTotal,
    screenerPage,
    screenerSortBy,
    screenerSortDir,
    screenerLoading,
    presetName,
    filters,
    presets,
    presetHits,
    presetDescription,
    filteredRows,
    breadth,
    screenerUpdatedLabel,
    fetchScreener,
    fetchScreenerAll,
    switchScreenerMode,
    screenerSort,
    screenerPageUp,
    screenerPageDown,
    screenerSortIcon,
    scanNow,
    applyPreset,
    resetFilters,
    exportResults,
  };
});
