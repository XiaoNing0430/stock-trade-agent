import { defineStore } from 'pinia';
import { computed, nextTick, ref, reactive } from 'vue';
import { DEFAULT_WATCHLIST, VIEW_META } from '@/modules/constants';
import { mergeMarketQuotes } from '@/modules/marketUtils';
import { useWorkspaceStore } from './useWorkspaceStore';
import { useScreenerStore } from './useScreenerStore';
import { usePlansStore } from './usePlansStore';
import { useSettingsStore } from './useSettingsStore';

/**
 * 行情 store：market 快照 / 选中股票 / 日线历史 / 行情抓取与合并。
 * 行为与重构前 app.ts setup() 对应域一致（字段名逐字保持）。
 */
export const useQuotesStore = defineStore('quotes', () => {
  const workspace = useWorkspaceStore();
  const saved = workspace.loadStorage();
  const view = ref(saved.view || 'overview');
  const loading = ref(false);
  const globalSearch = ref('');
  const dataState = ref('connecting');
  const chartDataSource = ref('live');
  const errorMessage = ref('');
  const selectedCode = ref(saved.selectedCode || DEFAULT_WATCHLIST[0]);
  const detailReturnView = ref('screener');
  const selectedHistory = ref<any[]>([]);
  const selectedHistoryCode = ref('');
  const selectedHistoryFetchedAt = ref(0);
  const indexHistory = ref<any[]>([]);
  const indexHistoryFetchedAt = ref(0);
  const market = reactive({
    provider: saved.marketCache?.provider || '',
    fetchedAt: saved.marketCache?.fetchedAt || 0,
    quotes: (saved.marketCache?.quotes || []) as any[],
    indices: (saved.marketCache?.indices || []) as any[],
    errors: [] as any[],
  });

  const hasLiveQuotes = computed(() => market.quotes.length > 0 || useScreenerStore().screenRows.length > 0);
  const providerLabel = computed(() => market.provider || '行情代理');
  const marketStatus = computed(() => {
    if (dataState.value === 'live' && hasLiveQuotes.value) return '已连接';
    if (dataState.value === 'stale') return '缓存';
    if (dataState.value === 'error') return '断开';
    return '连接中';
  });
  const dataStatusText = computed(() => {
    if (dataState.value === 'live' && hasLiveQuotes.value) return '实时数据已同步';
    if (dataState.value === 'stale') return '接口异常，显示缓存';
    if (dataState.value === 'error') return '等待行情接口恢复';
    return '正在连接行情代理';
  });
  const lastUpdatedLabel = computed(() => formatTimeShort(market.fetchedAt));
  const fetchedLabel = computed(() => formatDateShort(market.fetchedAt));
  const todayLabel = computed(() => new Date().toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }));

  const selectedStock = computed(() => quoteFor(selectedCode.value));
  const selectedIndex = computed(() => market.indices[0] || null);
  const indices = computed(() => market.indices || []);
  const watchlistQuotes = computed(() =>
    workspace.watchlistCodes.map((code: string) => {
      const quote = quoteFor(code);
      return (
        quote || {
          code,
          name: code,
          exchange: '未知',
          board: '未知',
          market: '未知',
          price: null,
          change: null,
          volumeRatio: null,
        }
      );
    })
  );
  const hasWatchTargets = computed(() => workspace.watchlistCodes.length > 0);
  const monitorStatusLabel = computed(() => {
    if (!hasWatchTargets.value) return '等待添加标的';
    return workspace.monitorEnabled ? '盯盘已开启' : '盯盘已暂停';
  });
  const monitorNextScan = computed(() => {
    if (!hasWatchTargets.value) return '尚未开始';
    return workspace.monitorEnabled ? `${useSettingsStore().settingsDraft.refreshInterval} 秒` : '已暂停';
  });

  function formatTimeShort(ms: number) {
    return ms ? new Date(ms).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '--';
  }
  function formatDateShort(ms: number) {
    return ms ? new Date(ms).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) : '--';
  }

  function quoteFor(code: string | undefined | null) {
    if (!code) return null;
    return (
      market.quotes.find((quote) => quote.code === code) ||
      useScreenerStore().screenRows.find((row) => row.code === code) ||
      null
    );
  }

  function mergeMarket(payload: any) {
    market.quotes = mergeMarketQuotes(market.quotes, payload.quotes || []);
    market.indices = payload.indices || market.indices;
    market.provider = payload.provider || market.provider;
    market.fetchedAt = payload.fetchedAt || Date.now();
    market.errors = payload.errors || [];
  }

  async function fetchMarket() {
    const codes = [
      ...new Set([...workspace.watchlistCodes, selectedCode.value, ...workspace.activePlans.map((plan) => plan.code)]),
    ];
    const payload = await workspace.requestJson(`/api/market?codes=${encodeURIComponent(codes.join(','))}`);
    mergeMarket(payload);
    usePlansStore().checkPlanTriggers();
    workspace.persist();
  }

  async function fetchHistory(code: string, type = 'selected') {
    const isIndex = type === 'index';
    const payload = await workspace.requestJson(
      `/api/history?code=${encodeURIComponent(code)}${isIndex ? '&index=1' : ''}`
    );
    if (isIndex) {
      indexHistory.value = payload.history || [];
      indexHistoryFetchedAt.value = Date.now();
    } else {
      selectedHistory.value = payload.history || [];
      selectedHistoryCode.value = code;
      selectedHistoryFetchedAt.value = Date.now();
    }
    chartDataSource.value = payload.dataSource === 'local' ? 'local' : 'live';
  }

  async function ensureQuote(code: string) {
    if (market.quotes.some((quote) => quote.code === code)) return;
    try {
      const payload = await workspace.requestJson(`/api/market?codes=${encodeURIComponent(code)}`);
      mergeMarket(payload);
      workspace.persist();
    } catch {
      errorMessage.value = `无法读取 ${code} 的实时报价。`;
    }
  }

  async function selectStock(code: string, fromView?: string) {
    if (!code) return;
    detailReturnView.value = fromView || view.value || 'screener';
    selectedCode.value = code;
    workspace.persist();
    view.value = 'stock-detail';
    await ensureQuote(code);
    try {
      await fetchHistory(code, 'selected');
    } catch {
      errorMessage.value = '该股票的历史日线暂时不可用。';
    }
    await nextTick();
    workspace.renderIcons();
  }

  function backFromDetail() {
    view.value = detailReturnView.value;
    workspace.persist();
    nextTick(workspace.renderIcons);
  }

  function isWatched(code: string) {
    return workspace.watchlistCodes.includes(code);
  }

  function toggleWatch(code: string) {
    if (!code) return;
    const quote = quoteFor(code);
    if (isWatched(code)) {
      workspace.watchlistCodes = workspace.watchlistCodes.filter((item: string) => item !== code);
      workspace.showToast(`${quote?.name || code} 已移出自选`);
    } else {
      workspace.watchlistCodes.push(code);
      workspace.showToast(`${quote?.name || code} 已加入自选`);
      ensureQuote(code);
    }
    workspace.persist();
  }

  function searchSymbol() {
    const query = globalSearch.value.trim().toLowerCase();
    if (!query) return;
    const match = [...market.quotes, ...useScreenerStore().screenRows].find((stock) =>
      `${stock.code}${stock.name}`.toLowerCase().includes(query)
    );
    if (match) {
      selectStock(match.code);
      workspace.showToast(`已定位到 ${match.name}`);
      return;
    }
    if (/^\d{6}$/.test(query)) {
      selectStock(query);
      return;
    }
    workspace.showToast('没有找到对应股票', 'error');
  }

  const currentViewMeta = computed(() => {
    const meta = (VIEW_META as Record<string, string[]>)[view.value] || VIEW_META.overview;
    return { title: meta[0], subtitle: meta[1] };
  });

  const mobileExecTab = ref('plans');
  const execShowsPlans = computed(() => view.value === 'exec' && mobileExecTab.value === 'plans');
  const execShowsAlerts = computed(() => view.value === 'exec' && mobileExecTab.value === 'alerts');

  function switchView(name: string) {
    view.value = name;
    workspace.persist();
    nextTick(workspace.renderIcons);
  }

  return {
    view,
    loading,
    globalSearch,
    dataState,
    chartDataSource,
    errorMessage,
    selectedCode,
    detailReturnView,
    selectedHistory,
    selectedHistoryCode,
    selectedHistoryFetchedAt,
    indexHistory,
    indexHistoryFetchedAt,
    market,
    hasLiveQuotes,
    providerLabel,
    marketStatus,
    dataStatusText,
    lastUpdatedLabel,
    fetchedLabel,
    todayLabel,
    selectedStock,
    selectedIndex,
    indices,
    watchlistQuotes,
    hasWatchTargets,
    monitorStatusLabel,
    monitorNextScan,
    quoteFor,
    mergeMarket,
    fetchMarket,
    fetchHistory,
    ensureQuote,
    selectStock,
    backFromDetail,
    isWatched,
    toggleWatch,
    searchSymbol,
    currentViewMeta,
    mobileExecTab,
    execShowsPlans,
    execShowsAlerts,
    switchView,
  };
});
