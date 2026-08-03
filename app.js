const {
  createApp,
  ref,
  reactive,
  computed,
  watch,
  onMounted,
  onBeforeUnmount,
  nextTick
} = Vue;

const STORAGE_KEY = 'atlas-stock-desk-v2';
const DEFAULT_WATCHLIST = ['600519', '300750', '601318', '600036', '000858', '002594'];
const DEFAULT_FILTERS = {
  market: '全部',
  search: '',
  peMax: 80,
  pbMax: 12,
  volumeMin: 1.2,
  changeMin: 1
};
const DEFAULT_ALERTS = [
  {
    id: 'alert-connection',
    kind: 'info',
    title: '真实行情连接已就绪',
    message: '报价、指数和日线由本地行情代理实时拉取。',
    time: '刚刚',
    read: false
  }
];

const PRESETS = [
  {
    name: '趋势突破',
    icon: 'trending-up',
    iconClass: 'preset-icon-coral',
    description: '放量、强势、价格向上',
    filters: { peMax: 80, pbMax: 12, volumeMin: 1.2, changeMin: 1 }
  },
  {
    name: '质量成长',
    icon: 'gem',
    iconClass: 'preset-icon-blue',
    description: '估值适中、量能稳定',
    filters: { peMax: 55, pbMax: 8, volumeMin: 0.8, changeMin: -2 }
  },
  {
    name: '低估修复',
    icon: 'scale',
    iconClass: 'preset-icon-gold',
    description: '低 PE、低 PB、等待修复',
    filters: { peMax: 22, pbMax: 3, volumeMin: 0.5, changeMin: -3 }
  }
];

const NAV_ITEMS = [
  { id: 'overview', label: '总览', icon: 'layout-dashboard' },
  { id: 'screener', label: '选股器', icon: 'scan-search' },
  { id: 'plans', label: '交易计划', icon: 'clipboard-pen-line' },
  { id: 'monitor', label: '盯盘中心', icon: 'radar' }
];

const VIEW_META = {
  overview: ['交易总览', '把真实行情、计划与提醒放在同一张桌面上'],
  screener: ['选股器', '从实时市场数据里筛出值得研究的标的'],
  plans: ['交易计划', '把想法写成可以执行的规则'],
  monitor: ['盯盘中心', '真实报价触发计划条件时，提醒会出现在这里']
};

function loadStorage() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
  } catch (error) {
    return {};
  }
}

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  return Number(value).toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
}

function formatPct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  return `${value >= 0 ? '+' : ''}${Number(value).toFixed(2)}%`;
}

function formatTime(timestamp) {
  if (!timestamp) return '--:--:--';
  return new Date(timestamp).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  });
}

function formatDateLabel(timestamp) {
  if (!timestamp) return '尚未更新';
  return `更新于 ${formatTime(timestamp)}`;
}

function formatAmount(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '--';
  const amount = Number(value);
  if (amount >= 100000000) return `${(amount / 100000000).toFixed(2)} 亿`;
  if (amount >= 10000) return `${(amount / 10000).toFixed(2)} 万`;
  return `${Math.round(amount).toLocaleString()} 元`;
}

function trendClass(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return 'trend-flat';
  return Number(value) >= 0 ? 'trend-up' : 'trend-down';
}

function chartSvg(points, accent, label) {
  if (!Array.isArray(points) || points.length < 2) {
    return '<div class="chart-empty">暂无足够的日线数据</div>';
  }
  const width = 640;
  const height = 150;
  const pad = { top: 12, right: 12, bottom: 24, left: 12 };
  const innerWidth = width - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const coords = points.map((value, index) => {
    const x = pad.left + (index / (points.length - 1)) * innerWidth;
    const y = pad.top + (1 - (value - min) / range) * innerHeight;
    return [x, y];
  });
  const linePath = coords
    .map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(' ');
  const areaPath = `${linePath} L ${coords[coords.length - 1][0].toFixed(1)} ${height - pad.bottom} L ${coords[0][0].toFixed(1)} ${height - pad.bottom} Z`;
  const grid = [0.22, 0.5, 0.78]
    .map((ratio) => {
      const y = pad.top + innerHeight * ratio;
      return `<line class="chart-grid-line" x1="${pad.left}" y1="${y.toFixed(1)}" x2="${width - pad.right}" y2="${y.toFixed(1)}"></line>`;
    })
    .join('');
  const labels = ['较早', '中段', '最新'];
  const labelMarkup = labels
    .map((text, index) => {
      const x = pad.left + (index / (labels.length - 1)) * innerWidth;
      const anchor = index === 0 ? 'start' : index === labels.length - 1 ? 'end' : 'middle';
      return `<text class="chart-axis-label" x="${x.toFixed(1)}" y="${height - 5}" text-anchor="${anchor}">${text}</text>`;
    })
    .join('');
  const last = coords[coords.length - 1];
  return `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${label}">
      <title>${label}</title>
      ${grid}
      <path class="chart-area" style="fill:${accent}16" d="${areaPath}"></path>
      <path class="chart-line" style="stroke:${accent}" d="${linePath}"></path>
      <circle class="chart-dot" style="stroke:${accent}" cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="4"></circle>
      ${labelMarkup}
    </svg>
  `;
}

createApp({
  setup() {
    const saved = loadStorage();
    const view = ref(saved.view || 'overview');
    const loading = ref(false);
    const globalSearch = ref('');
    const dataState = ref('connecting');
    const errorMessage = ref('');
    const selectedCode = ref(saved.selectedCode || DEFAULT_WATCHLIST[0]);
    const selectedHistory = ref([]);
    const selectedHistoryCode = ref('');
    const selectedHistoryFetchedAt = ref(0);
    const indexHistory = ref([]);
    const indexHistoryFetchedAt = ref(0);
    const screenRows = ref([]);
    const screenTotal = ref(0);
    const screenerUpdatedAt = ref(0);
    const presetName = ref(saved.presetName || '趋势突破');
    const watchlistCodes = ref(Array.isArray(saved.watchlist) ? saved.watchlist : DEFAULT_WATCHLIST);
    const plans = ref(Array.isArray(saved.plans) ? saved.plans : []);
    const alerts = ref(Array.isArray(saved.alerts) ? saved.alerts : DEFAULT_ALERTS);
    const monitorEnabled = ref(saved.monitorEnabled !== false);
    const draftDirty = ref(false);
    const draftWatchSuppressed = ref(true);
    const refreshTimer = ref(null);
    const lastToastTimer = ref(null);
    const draft = reactive({
      code: selectedCode.value,
      direction: 'buy',
      validity: '本周内',
      entry: 0,
      stop: 0,
      target: 0,
      capital: 100000,
      position: 30,
      note: ''
    });
    const market = reactive({
      provider: saved.marketCache?.provider || '',
      fetchedAt: saved.marketCache?.fetchedAt || 0,
      quotes: saved.marketCache?.quotes || [],
      indices: saved.marketCache?.indices || [],
      errors: []
    });
    const filters = reactive(Object.assign({}, DEFAULT_FILTERS, saved.filters || {}));

    const navItems = NAV_ITEMS;
    const presets = PRESETS;
    const currentViewMeta = computed(() => {
      const meta = VIEW_META[view.value] || VIEW_META.overview;
      return { title: meta[0], subtitle: meta[1] };
    });
    const providerLabel = computed(() => market.provider ? 'Tencent 行情' : '行情代理');
    const marketStatus = computed(() => {
      if (dataState.value === 'live') return '已连接';
      if (dataState.value === 'stale') return '缓存';
      if (dataState.value === 'error') return '断开';
      return '连接中';
    });
    const dataStatusText = computed(() => {
      if (dataState.value === 'live') return '实时数据已同步';
      if (dataState.value === 'stale') return '接口异常，显示缓存';
      if (dataState.value === 'error') return '等待行情接口恢复';
      return '正在连接行情代理';
    });
    const lastUpdatedLabel = computed(() => formatTime(market.fetchedAt));
    const fetchedLabel = computed(() => formatDateLabel(market.fetchedAt));
    const screenerUpdatedLabel = computed(() => formatDateLabel(screenerUpdatedAt.value));
    const todayLabel = computed(() => new Date().toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' }));

    const quoteFor = (code) => {
      if (!code) return null;
      return market.quotes.find((quote) => quote.code === code)
        || screenRows.value.find((row) => row.code === code)
        || null;
    };
    const quoteMap = computed(() => Object.fromEntries(market.quotes.map((quote) => [quote.code, quote])));
    const selectedStock = computed(() => quoteFor(selectedCode.value));
    const selectedIndex = computed(() => market.indices[0] || null);
    const indices = computed(() => market.indices || []);
    const watchlistQuotes = computed(() => watchlistCodes.value.map((code) => {
      const quote = quoteFor(code);
      return quote || {
        code,
        name: code,
        market: 'A股',
        price: null,
        change: null,
        volumeRatio: null
      };
    }));
    const planOptions = computed(() => {
      const map = new Map();
      [...market.quotes, ...screenRows.value, ...watchlistQuotes.value].forEach((stock) => {
        if (stock?.code) map.set(stock.code, stock);
      });
      if (!map.has(selectedCode.value)) {
        map.set(selectedCode.value, { code: selectedCode.value, name: selectedCode.value, market: 'A股' });
      }
      return [...map.values()];
    });
    const activePlans = computed(() => plans.value.filter((plan) => plan.status !== '已归档'));
    const unreadAlerts = computed(() => alerts.value.filter((alert) => !alert.read).length);
    const presetDescription = computed(() => {
      return presets.find((preset) => preset.name === presetName.value)?.description || '';
    });
    const filteredRows = computed(() => {
      const query = String(filters.search || '').toLowerCase();
      return screenRows.value
        .filter((row) => filters.market === '全部' || row.market === filters.market)
        .filter((row) => !query || `${row.code}${row.name}`.toLowerCase().includes(query))
        .filter((row) => row.pe !== null && row.pe <= Number(filters.peMax))
        .filter((row) => row.pb !== null && row.pb <= Number(filters.pbMax))
        .filter((row) => row.volumeRatio !== null && row.volumeRatio >= Number(filters.volumeMin))
        .filter((row) => row.change !== null && row.change >= Number(filters.changeMin))
        .sort((left, right) => (right.change + (right.volumeRatio || 0)) - (left.change + (left.volumeRatio || 0)));
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
        downRatio: Math.max(0, 100 - Math.round((up / total) * 100) - Math.round((flat / total) * 100))
      };
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

    function persist() {
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
          view: view.value,
          selectedCode: selectedCode.value,
          presetName: presetName.value,
          watchlist: watchlistCodes.value,
          plans: plans.value,
          alerts: alerts.value,
          monitorEnabled: monitorEnabled.value,
          filters: { ...filters },
          marketCache: {
            provider: market.provider,
            fetchedAt: market.fetchedAt,
            quotes: market.quotes,
            indices: market.indices
          }
        }));
      } catch (error) {
        // Storage is optional; real quotes continue to work without it.
      }
    }

    async function requestJson(url) {
      const response = await fetch(url, { cache: 'no-store' });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.error || `行情接口返回 ${response.status}`);
      }
      return payload;
    }

    function mergeMarket(payload) {
      const existing = new Map(market.quotes.map((quote) => [quote.code, quote]));
      (payload.quotes || []).forEach((quote) => existing.set(quote.code, quote));
      market.quotes = [...existing.values()];
      market.indices = payload.indices || market.indices;
      market.provider = payload.provider || market.provider;
      market.fetchedAt = payload.fetchedAt || Date.now();
      market.errors = payload.errors || [];
    }

    async function fetchMarket() {
      const codes = [...new Set([
        ...watchlistCodes.value,
        selectedCode.value,
        ...activePlans.value.map((plan) => plan.code)
      ])];
      const payload = await requestJson(`/api/market?codes=${encodeURIComponent(codes.join(','))}`);
      mergeMarket(payload);
      checkPlanTriggers();
      persist();
    }

    async function fetchScreener() {
      const payload = await requestJson(`/api/screener?market=${encodeURIComponent(filters.market)}&pageSize=300`);
      screenRows.value = payload.rows || [];
      screenTotal.value = Number(payload.total || screenRows.value.length);
      screenerUpdatedAt.value = payload.fetchedAt || Date.now();
    }

    async function fetchHistory(code, type = 'selected') {
      const payload = await requestJson(`/api/history?code=${encodeURIComponent(code)}`);
      if (type === 'index') {
        indexHistory.value = payload.history || [];
        indexHistoryFetchedAt.value = Date.now();
      } else {
        selectedHistory.value = payload.history || [];
        selectedHistoryCode.value = code;
        selectedHistoryFetchedAt.value = Date.now();
      }
    }

    async function refreshAll(options = {}) {
      const silent = Boolean(options.silent);
      if (!silent) loading.value = true;
      errorMessage.value = '';
      const tasks = [fetchMarket(), fetchScreener()];
      const now = Date.now();
      if (!indexHistory.value.length || now - indexHistoryFetchedAt.value > 60000) {
        tasks.push(fetchHistory('000001', 'index'));
      }
      if (!selectedHistory.value.length || selectedHistoryCode.value !== selectedCode.value || now - selectedHistoryFetchedAt.value > 60000) {
        tasks.push(fetchHistory(selectedCode.value, 'selected'));
      }
      const results = await Promise.allSettled(tasks);
      const failures = results.filter((result) => result.status === 'rejected');
      if (failures.length && !market.quotes.length && !screenRows.value.length) {
        dataState.value = 'error';
        errorMessage.value = failures[0].reason?.message || '真实行情暂时不可用';
      } else if (failures.length) {
        dataState.value = 'stale';
        errorMessage.value = '行情接口部分失败，当前页面保留最近一次成功数据。';
      } else {
        dataState.value = 'live';
      }
      if (market.errors.length && !errorMessage.value) {
        errorMessage.value = '部分股票报价暂时不可用，已保留其他实时结果。';
      }
      if (failures.length === 0) persist();
      loading.value = false;
      await nextTick();
      renderIcons();
    }

    async function ensureQuote(code) {
      if (market.quotes.some((quote) => quote.code === code)) return;
      try {
        const payload = await requestJson(`/api/market?codes=${encodeURIComponent(code)}`);
        mergeMarket(payload);
        persist();
      } catch (error) {
        errorMessage.value = `无法读取 ${code} 的实时报价。`;
      }
    }

    async function selectStock(code) {
      if (!code) return;
      selectedCode.value = code;
      persist();
      switchView('screener');
      await ensureQuote(code);
      try {
        await fetchHistory(code, 'selected');
      } catch (error) {
        errorMessage.value = '该股票的历史日线暂时不可用。';
      }
      await nextTick();
      renderIcons();
    }

    function isWatched(code) {
      return watchlistCodes.value.includes(code);
    }

    function toggleWatch(code) {
      if (!code) return;
      const quote = quoteFor(code);
      if (isWatched(code)) {
        watchlistCodes.value = watchlistCodes.value.filter((item) => item !== code);
        showToast(`${quote?.name || code} 已移出自选`);
      } else {
        watchlistCodes.value.push(code);
        showToast(`${quote?.name || code} 已加入自选`);
        ensureQuote(code);
      }
      persist();
    }

    function createPlan(code) {
      selectedCode.value = code || selectedCode.value;
      draft.code = selectedCode.value;
      hydrateDraft();
      draftDirty.value = false;
      view.value = 'plans';
      persist();
      nextTick(renderIcons);
    }

    function hydrateDraft() {
      const stock = quoteFor(draft.code) || quoteFor(selectedCode.value);
      if (!stock?.price) return;
      draftWatchSuppressed.value = true;
      draft.entry = Number(stock.price.toFixed(2));
      draft.stop = Number((stock.price * 0.95).toFixed(2));
      draft.target = Number((stock.price * 1.08).toFixed(2));
      nextTick(() => {
        draftWatchSuppressed.value = false;
      });
    }

    function planFor(code) {
      return activePlans.value.find((plan) => plan.code === code) || null;
    }

    function calculateShares(plan) {
      const budget = Number(plan.capital || 0) * (Number(plan.position || 0) / 100);
      return plan.entry > 0 ? Math.max(0, Math.floor(budget / plan.entry / 100) * 100) : 0;
    }

    function calculateRr(plan) {
      const risk = Math.max(0.01, Number(plan.entry) - Number(plan.stop));
      const reward = Math.max(0, Number(plan.target) - Number(plan.entry));
      return reward / risk;
    }

    function signalText(stock) {
      const plan = planFor(stock?.code);
      if (plan && stock?.price !== null && stock?.price !== undefined) {
        if (stock.price <= plan.stop) return '触及止损';
        if (stock.price >= plan.target) return '触及目标';
        if (stock.price <= plan.entry) return '触及计划价';
      }
      if (stock?.change === null || stock?.change === undefined) return '等待报价';
      if (stock.change >= 3 && Number(stock.volumeRatio || 0) >= 1.5) return '放量突破';
      if (stock.change <= -3) return '弱势观察';
      if (Number(stock.volumeRatio || 0) >= 1.5) return '量能放大';
      return '跟踪中';
    }

    function signalClass(stock) {
      const text = signalText(stock);
      if (text === '触及止损') return 'signal-chip-risk';
      if (text === '触及目标' || text === '触及计划价' || text === '放量突破') return 'signal-chip-buy';
      if (text === '等待报价') return 'signal-chip-neutral';
      return 'signal-chip-watch';
    }

    function checkPlanTriggers() {
      activePlans.value.forEach((plan) => {
        const quote = quoteFor(plan.code);
        if (!quote || quote.price === null || quote.price === undefined) return;
        plan.triggered = plan.triggered || {};
        if (quote.price <= plan.stop && !plan.triggered.stop) {
          plan.triggered.stop = true;
          plan.status = '已触发';
          addAlert('alert', `${quote.name}触及止损线`, `最新价 ${formatNumber(quote.price)}，请确认是否执行止损规则。`);
        } else if (quote.price >= plan.target && !plan.triggered.target) {
          plan.triggered.target = true;
          plan.status = '已触发';
          addAlert('success', `${quote.name}触及目标价`, `最新价 ${formatNumber(quote.price)}，请确认是否分批止盈。`);
        } else if (quote.price <= plan.entry && !plan.triggered.entry) {
          plan.triggered.entry = true;
          addAlert('success', `${quote.name}触及计划买入价`, `最新价 ${formatNumber(quote.price)}，已进入计划价附近。`);
        }
      });
    }

    function addAlert(kind, title, message) {
      const item = {
        id: `alert-${Date.now()}-${Math.random().toString(16).slice(2)}`,
        kind,
        title,
        message,
        time: '刚刚',
        read: false
      };
      alerts.value.unshift(item);
      alerts.value = alerts.value.slice(0, 24);
      persist();
      if (typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification(title, { body: message });
      }
    }

    function savePlan() {
      if (!draft.code || !draft.entry || !draft.stop || !draft.target || draft.stop >= draft.entry || draft.target <= draft.entry) {
        showToast('请检查计划价、止损价和目标价的关系', 'error');
        return;
      }
      const stock = quoteFor(draft.code);
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
        createdAt: formatTime(Date.now()).slice(0, 5),
        triggered: {}
      };
      plans.value.unshift(plan);
      if (!isWatched(plan.code)) watchlistCodes.value.push(plan.code);
      addAlert('success', `${stock?.name || plan.code} 交易计划已保存`, `计划价 ${formatNumber(plan.entry)}，止损 ${formatNumber(plan.stop)}，目标 ${formatNumber(plan.target)}。`);
      draftDirty.value = false;
      persist();
      showToast('交易计划已保存');
    }

    function archivePlan(id) {
      const plan = plans.value.find((item) => item.id === id);
      if (!plan) return;
      plan.status = '已归档';
      persist();
      showToast('计划已归档');
    }

    function monitorPlan(plan) {
      selectedCode.value = plan.code;
      view.value = 'monitor';
      persist();
      nextTick(renderIcons);
    }

    function markAlertRead(id) {
      const alert = alerts.value.find((item) => item.id === id);
      if (!alert) return;
      alert.read = true;
      persist();
    }

    function clearReadAlerts() {
      alerts.value = alerts.value.filter((alert) => !alert.read);
      persist();
      showToast('已清空已读提醒');
    }

    function applyPreset(preset) {
      presetName.value = preset.name;
      Object.assign(filters, preset.filters);
      persist();
      scanNow();
    }

    function resetFilters() {
      presetName.value = '趋势突破';
      Object.assign(filters, DEFAULT_FILTERS);
      persist();
      scanNow();
    }

    async function scanNow() {
      loading.value = true;
      try {
        await fetchScreener();
        showToast(`扫描完成，共 ${filteredRows.value.length} 只结果`);
      } catch (error) {
        errorMessage.value = error.message;
        showToast('筛选接口暂时不可用', 'error');
      } finally {
        loading.value = false;
        await nextTick();
        renderIcons();
      }
    }

    function switchView(nextView) {
      view.value = nextView;
      persist();
      nextTick(renderIcons);
    }

    function searchSymbol() {
      const query = globalSearch.value.trim().toLowerCase();
      if (!query) return;
      const match = [
        ...market.quotes,
        ...screenRows.value
      ].find((stock) => `${stock.code}${stock.name}`.toLowerCase().includes(query));
      if (match) {
        selectStock(match.code);
        showToast(`已定位到 ${match.name}`);
        return;
      }
      if (/^\d{6}$/.test(query)) {
        selectStock(query);
        return;
      }
      showToast('没有找到对应股票', 'error');
    }

    function exportResults() {
      const header = ['代码', '名称', '市场', '现价', '涨跌幅', 'PE', 'PB', '量比', '换手率'];
      const rows = filteredRows.value.map((stock) => [
        stock.code,
        stock.name,
        stock.market,
        stock.price ?? '',
        stock.change ?? '',
        stock.pe ?? '',
        stock.pb ?? '',
        stock.volumeRatio ?? '',
        stock.turnoverRate ?? ''
      ]);
      const csv = [header, ...rows].map((row) => row.join(',')).join('\n');
      const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `atlas-screen-${Date.now()}.csv`;
      link.click();
      URL.revokeObjectURL(url);
      showToast('筛选结果已导出');
    }

    function requestNotifications() {
      if (!('Notification' in window)) {
        showToast('当前浏览器不支持桌面提醒', 'error');
        return;
      }
      if (Notification.permission === 'granted') {
        new Notification('Atlas 盯盘提醒已开启', { body: '价格触发交易计划时会提醒你。' });
        showToast('桌面提醒已开启');
        return;
      }
      Notification.requestPermission().then((permission) => {
        if (permission === 'granted') {
          new Notification('Atlas 盯盘提醒已开启', { body: '价格触发交易计划时会提醒你。' });
          showToast('桌面提醒已开启');
        } else {
          showToast('未获得桌面提醒权限', 'error');
        }
      });
    }

    function showToast(message, tone = 'success') {
      const region = document.getElementById('toast-region');
      if (!region) return;
      const toast = document.createElement('div');
      toast.className = `toast ${tone === 'error' ? 'error' : ''}`;
      toast.innerHTML = `<i data-lucide="${tone === 'error' ? 'triangle-alert' : 'check-circle-2'}" aria-hidden="true"></i><span>${message}</span>`;
      region.appendChild(toast);
      renderIcons();
      clearTimeout(lastToastTimer.value);
      lastToastTimer.value = setTimeout(() => toast.remove(), 3200);
    }

    function renderIcons() {
      if (window.lucide) {
        window.lucide.createIcons({ attrs: { width: 16, height: 16, 'stroke-width': 1.8 } });
      }
    }

    function formatNullable(value, digits = 2) {
      return formatNumber(value, digits);
    }

    function formatPctNullable(value) {
      return formatPct(value);
    }

    function formatMoney(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return '¥0';
      return `¥${Number(value).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`;
    }

    watch(() => filters.market, () => {
      persist();
      if (!loading.value) scanNow();
    });
    watch(() => draft.code, async () => {
      if (!draftWatchSuppressed.value && !draftDirty.value) {
        selectedCode.value = draft.code;
        await ensureQuote(draft.code);
        hydrateDraft();
      }
    });
    watch(draft, () => {
      if (!draftWatchSuppressed.value) draftDirty.value = true;
    }, { deep: true });
    watch(view, () => nextTick(renderIcons));
    watch(monitorEnabled, () => {
      persist();
      showToast(monitorEnabled.value ? '盯盘已开启' : '盯盘已暂停');
    });

    onMounted(async () => {
      draftWatchSuppressed.value = false;
      hydrateDraft();
      await refreshAll();
      renderIcons();
      refreshTimer.value = setInterval(() => {
        if (monitorEnabled.value) refreshAll({ silent: true });
      }, 15000);
      document.addEventListener('keydown', (event) => {
        if (event.key === '/' && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
          event.preventDefault();
          document.querySelector('.global-search input')?.focus();
        }
        const shortcut = { '1': 'overview', '2': 'screener', '3': 'plans', '4': 'monitor' }[event.key];
        if (shortcut && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') switchView(shortcut);
      });
    });

    onBeforeUnmount(() => clearInterval(refreshTimer.value));

    return {
      navItems,
      presets,
      view,
      loading,
      globalSearch,
      dataState,
      errorMessage,
      selectedCode,
      selectedStock,
      selectedIndex,
      selectedHistory,
      indexHistory,
      indices,
      watchlistCodes,
      watchlistQuotes,
      activePlans,
      alerts,
      unreadAlerts,
      monitorEnabled,
      draft,
      draftDirty,
      filters,
      screenTotal,
      filteredRows,
      presetName,
      presetDescription,
      currentViewMeta,
      providerLabel,
      marketStatus,
      dataStatusText,
      lastUpdatedLabel,
      fetchedLabel,
      screenerUpdatedLabel,
      todayLabel,
      breadth,
      planOptions,
      planMetrics,
      formatNumber,
      formatPct,
      formatAmount,
      formatNullable,
      formatPctNullable,
      formatMoney,
      formatDateLabel,
      trendClass,
      chartSvg,
      quoteFor,
      planFor,
      calculateRr,
      calculateShares,
      signalText,
      signalClass,
      isWatched,
      switchView,
      refreshAll,
      scanNow,
      selectStock,
      toggleWatch,
      createPlan,
      savePlan,
      archivePlan,
      monitorPlan,
      markAlertRead,
      clearReadAlerts,
      requestNotifications,
      resetFilters,
      applyPreset,
      exportResults,
      searchSymbol
    };
  }
}).mount('#app');
