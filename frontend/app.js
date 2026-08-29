import { STORAGE_KEY, DEFAULT_WATCHLIST, DEFAULT_FILTERS, DEFAULT_ALERTS, PRESETS, NAV_ITEMS, VIEW_META } from './modules/constants.js';
import { formatNumber, formatPct, formatTime, formatDateLabel, formatAmount, formatMoney, formatNullable, formatPctNullable, trendClass, escapeHtml, validityExpiry } from './modules/format.js';
import { chartSvg, compareChartSvg } from './modules/chart.js';

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

function loadStorage() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
  } catch (error) {
    return {};
  }
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
    const workspaceSynced = ref(false);
    const workspaceRevision = ref(Number(saved.workspaceRevision) || 0);
    const conflictVisible = ref(false);
    const conflictSnapshot = ref(null);
    const workspaceSyncTimer = ref(null);
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
    const gridDraft = reactive({
      id: '',
      code: selectedCode.value,
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
      schedule: 'daily'
    });
    const gridLoading = ref(false);
    const gridSuggestion = ref(null);
    const gridResult = ref(null);
    const gridCandidates = ref([]);
    const gridStrategies = ref([]);
    const gridSuggestedCode = ref('');
    const market = reactive({
      provider: saved.marketCache?.provider || '',
      fetchedAt: saved.marketCache?.fetchedAt || 0,
      quotes: saved.marketCache?.quotes || [],
      indices: saved.marketCache?.indices || [],
      errors: []
    });
    const filters = reactive(Object.assign({}, DEFAULT_FILTERS, saved.filters || {}));
    const settingsDraft = reactive({ workspaceName: '个人工作区', defaultCapital: 100000, monitorEnabled: true, realtimeSource: 'tencent', historySource: 'tencent', screenerSource: 'tencent', fallbackEnabled: true, refreshInterval: 15, cacheSeconds: 8, timeoutSeconds: 10, retryCount: 1 });
    const dataSources = ref([]);
    const settingsLoading = ref(false);
    if (saved.filters?.market === '沪A') {
      filters.exchange = '上交所';
      filters.market = '全部';
    } else if (saved.filters?.market === '深A') {
      filters.exchange = '深交所';
      filters.market = '全部';
    }

    const navItems = NAV_ITEMS;
    const presets = PRESETS;
    const currentViewMeta = computed(() => {
      const meta = VIEW_META[view.value] || VIEW_META.overview;
      return { title: meta[0], subtitle: meta[1] };
    });
    const hasLiveQuotes = computed(() => market.quotes.length > 0 || screenRows.value.length > 0);
    const providerLabel = computed(() => market.provider ? 'Tencent 行情' : '行情代理');
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
    const normalizedGridCode = computed(() => String(gridDraft.code || '').trim());
    const gridInstrument = computed(() => quoteFor(normalizedGridCode.value));
    const hasGridSuggestion = computed(() => Boolean(gridSuggestion.value) && gridSuggestedCode.value === normalizedGridCode.value);
    const hasGridResult = computed(() => Boolean(gridResult.value));
    const selectedIndex = computed(() => market.indices[0] || null);
    const indices = computed(() => market.indices || []);
    const watchlistQuotes = computed(() => watchlistCodes.value.map((code) => {
      const quote = quoteFor(code);
      return quote || {
        code,
        name: code,
        exchange: '未知',
        board: '未知',
        market: '未知',
        price: null,
        change: null,
        volumeRatio: null
      };
    }));
    const hasWatchTargets = computed(() => watchlistCodes.value.length > 0);
    const monitorStatusLabel = computed(() => {
      if (!hasWatchTargets.value) return '等待添加标的';
      return monitorEnabled.value ? '盯盘已开启' : '盯盘已暂停';
    });
    const monitorNextScan = computed(() => {
      if (!hasWatchTargets.value) return '尚未开始';
      return monitorEnabled.value ? `${settingsDraft.refreshInterval} 秒` : '已暂停';
    });
    const refreshIntervalLabel = computed(() => `${settingsDraft.refreshInterval} 秒`);
    const planOptions = computed(() => {
      const map = new Map();
      [...market.quotes, ...screenRows.value, ...watchlistQuotes.value].forEach((stock) => {
        if (stock?.code) map.set(stock.code, stock);
      });
      if (!map.has(selectedCode.value)) {
        map.set(selectedCode.value, {
          code: selectedCode.value,
          name: selectedCode.value,
          exchange: '未知',
          board: '未知',
          market: '未知'
        });
      }
      return [...map.values()];
    });
    const activePlans = computed(() => plans.value.filter((plan) => plan.status === '执行中' || plan.status === '已触发'));
    const unreadAlerts = computed(() => alerts.value.filter((alert) => !alert.read).length);
    const presetDescription = computed(() => {
      return presets.find((preset) => preset.name === presetName.value)?.description || '';
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
        .sort((left, right) => (right.change - left.change) || ((right.volumeRatio || 0) - (left.volumeRatio || 0)));
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
          workspaceRevision: workspaceRevision.value,
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
      scheduleWorkspaceSync();
    }

    async function requestJson(url, options = {}) {
      const response = await fetch(url, {
        cache: 'no-store',
        ...options,
        headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) }
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        const error = new Error(payload.detail?.error || payload.error || `接口返回 ${response.status}`);
        error.status = response.status;
        error.payload = payload;
        throw error;
      }
      return payload;
    }

    function workspacePayload() {
      return {
        watchlist: watchlistCodes.value,
        plans: plans.value,
        alerts: alerts.value
      };
    }

    let workspaceSyncInFlight = false;
    let workspaceSyncQueued = false;

    function scheduleWorkspaceSync() {
      if (!workspaceSynced.value) return;
      if (workspaceSyncInFlight) {
        // A sync is already running; keep the latest snapshot queued so no change is lost.
        workspaceSyncQueued = true;
        return;
      }
      clearTimeout(workspaceSyncTimer.value);
      workspaceSyncTimer.value = setTimeout(async () => {
        workspaceSyncInFlight = true;
        try {
          await requestJson(`/api/workspace?baseRevision=${encodeURIComponent(workspaceRevision.value)}`, {
            method: 'PUT',
            body: JSON.stringify(workspacePayload())
          });
        } catch (error) {
          if (error.status === 409 && error.payload?.detail?.workspace) {
            // 版本冲突不自动重试，交给用户在横幅中决策，避免覆盖任何一端数据。
            workspaceSyncQueued = false;
            showConflictBanner(error.payload.detail.workspace);
          }
          // 其余失败仍静默降级：浏览器存储兜底，等待持久化服务恢复。
        } finally {
          workspaceSyncInFlight = false;
          if (workspaceSyncQueued) {
            workspaceSyncQueued = false;
            scheduleWorkspaceSync();
          }
        }
      }, 350);
    }

    function showConflictBanner(snapshot) {
      conflictSnapshot.value = snapshot;
      conflictVisible.value = true;
      showToast('其他页面已更新工作区数据，请选择保留哪一版', 'error');
    }

    async function adoptServerWorkspace() {
      const snapshot = conflictSnapshot.value;
      conflictVisible.value = false;
      if (!snapshot) return;
      watchlistCodes.value = snapshot.watchlist || [];
      plans.value = snapshot.plans || [];
      alerts.value = snapshot.alerts || [];
      workspaceRevision.value = Number(snapshot.revision || 0);
      persist();
      showToast('已采用服务器最新数据');
    }

    async function forceSaveWorkspace() {
      conflictVisible.value = false;
      try {
        const saved = await requestJson('/api/workspace?force=true', {
          method: 'PUT',
          body: JSON.stringify(workspacePayload())
        });
        workspaceRevision.value = Number(saved.revision || 0);
        persist();
        showToast('已用本地数据覆盖服务器');
      } catch (error) {
        showToast(error.message || '覆盖失败', 'error');
      }
    }

    async function loadWorkspace() {
      try {
        const remote = await requestJson('/api/workspace');
        workspaceRevision.value = Number(remote.revision || 0);
        const hasRemoteData = (remote.watchlist || []).length || (remote.plans || []).length || (remote.alerts || []).length;
        if (hasRemoteData) {
          watchlistCodes.value = remote.watchlist || [];
          plans.value = remote.plans || [];
          alerts.value = remote.alerts || [];
        }
      } catch (error) {
        // Existing local state is intentionally retained for first-run or offline use.
      } finally {
        workspaceSynced.value = true;
        persist();
      }
    }

    async function loadSettings() {
      settingsLoading.value = true;
      try {
        const payload = await requestJson('/api/settings');
        Object.assign(settingsDraft, payload.data || {});
        dataSources.value = payload.sources || [];
      } catch (error) {
        showToast('设置读取失败，正在使用本地默认值', 'error');
      } finally {
        settingsLoading.value = false;
      }
    }

    async function saveSettings() {
      settingsLoading.value = true;
      try {
        const payload = await requestJson('/api/settings', { method: 'PUT', body: JSON.stringify(settingsDraft) });
        Object.assign(settingsDraft, payload.data || {});
        monitorEnabled.value = settingsDraft.monitorEnabled;
        armRefreshTimer();
        showToast('网站设置已保存');
        await refreshAll();
      } catch (error) {
        showToast(error.message || '设置保存失败', 'error');
      } finally {
        settingsLoading.value = false;
      }
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
      const isIndex = type === 'index';
      const payload = await requestJson(`/api/history?code=${encodeURIComponent(code)}${isIndex ? '&index=1' : ''}`);
      if (isIndex) {
        indexHistory.value = payload.history || [];
        indexHistoryFetchedAt.value = Date.now();
      } else {
        selectedHistory.value = payload.history || [];
        selectedHistoryCode.value = code;
        selectedHistoryFetchedAt.value = Date.now();
      }
    }

    let refreshInFlight = false;

    async function refreshAll(options = {}) {
      const silent = Boolean(options.silent);
      if (refreshInFlight) {
        // 已有刷新进行中：定时轮询直接跳过，避免慢网络下请求堆积。
        if (silent) return;
      }
      if (!silent) loading.value = true;
      refreshInFlight = true;
      try {
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
        expirePlans();
        if (failures.length === 0) persist();
      } finally {
        refreshInFlight = false;
        loading.value = false;
        await nextTick();
        renderIcons();
      }
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

    function expirePlans() {
      const now = Date.now();
      let expired = 0;
      plans.value.forEach((plan) => {
        if (plan.status !== '执行中') return;
        const expiresAt = validityExpiry(plan.createdAtMs, plan.validity);
        if (!expiresAt) return;
        if (now > expiresAt) {
          plan.status = '已过期';
          expired += 1;
        }
      });
      if (expired) {
        addAlert('info', '有交易计划已到期', `${expired} 份计划超过有效期，已自动归档为已过期。`);
        persist();
      }
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
        createdAtMs: Date.now(),
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

    async function previewGrid() {
      const code = normalizedGridCode.value;
      if (!/^\d{6}$/.test(code)) {
        showToast('请输入 6 位股票或 ETF 代码', 'error');
        return;
      }
      gridLoading.value = true;
      try {
        await ensureQuote(code);
        const payload = await requestJson('/api/grid/preview', {
          method: 'POST',
          body: JSON.stringify(gridDraft)
        });
        gridDraft.lower = payload.suggestion.lower;
        gridDraft.upper = payload.suggestion.upper;
        gridDraft.capital = payload.suggestion.suggestedCapital;
        gridSuggestion.value = payload.suggestion;
        gridSuggestedCode.value = code;
        gridResult.value = null;
        showToast('已根据历史波动生成网格区间');
      } catch (error) {
        showToast(error.message || '无法生成网格区间', 'error');
      } finally {
        gridLoading.value = false;
      }
    }

    async function backtestGrid(save = false) {
      if (save && !hasGridResult.value) {
        showToast('请先运行回测，再保存策略', 'error');
        return;
      }
      gridLoading.value = true;
      try {
        const payload = await requestJson('/api/grid/backtest', {
          method: 'POST',
          body: JSON.stringify({ ...gridDraft, save })
        });
        gridResult.value = payload;
        if (payload.strategy) {
          gridDraft.id = payload.strategy.id;
          await loadGridStrategies();
        }
        showToast(save ? '网格策略已保存并记录回测' : '网格回测完成');
      } catch (error) {
        showToast(error.message || '网格回测失败', 'error');
      } finally {
        gridLoading.value = false;
      }
    }

    async function optimizeGrid() {
      gridLoading.value = true;
      try {
        const payload = await requestJson('/api/grid/optimize', {
          method: 'POST',
          body: JSON.stringify(gridDraft)
        });
        gridCandidates.value = payload.candidates || [];
        const best = gridCandidates.value[0];
        if (best) {
          gridDraft.gridCount = best.gridCount;
          gridDraft.lower = best.lower;
          gridDraft.upper = best.upper;
        }
        showToast(best?.recommended ? '已选出历史回测表现最优的参数' : '已填入最优候选（暂不推荐，请查看稳健性标记）');
      } catch (error) {
        showToast(error.message || '参数优化失败', 'error');
      } finally {
        gridLoading.value = false;
      }
    }

    async function loadGridStrategies() {
      try {
        const payload = await requestJson('/api/grid/strategies');
        gridStrategies.value = payload.strategies || [];
      } catch (error) {
        gridStrategies.value = [];
      }
    }

    function loadGridStrategy(strategy) {
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
        schedule: strategy.schedule
      });
      gridSuggestion.value = null;
      gridSuggestedCode.value = '';
      gridResult.value = null;
      showToast(`已载入 ${strategy.name}`);
    }

    async function toggleGridStrategy(strategy) {
      const status = strategy.status === '启用' ? '暂停' : '启用';
      try {
        await requestJson(`/api/grid/strategies/${encodeURIComponent(strategy.id)}`, {
          method: 'PATCH',
          body: JSON.stringify({ status })
        });
        await loadGridStrategies();
      } catch (error) {
        showToast(error.message || '更新策略状态失败', 'error');
      }
    }

    async function deleteGridStrategy(strategy) {
      if (!window.confirm(`删除策略“${strategy.name}”及其回测记录？`)) return;
      try {
        await requestJson(`/api/grid/strategies/${encodeURIComponent(strategy.id)}`, { method: 'DELETE' });
        if (gridDraft.id === strategy.id) gridDraft.id = '';
        await loadGridStrategies();
        showToast('策略及其回测记录已删除');
      } catch (error) {
        showToast(error.message || '删除策略失败', 'error');
      }
    }

    async function openGridStrategy(code = selectedCode.value) {
      const normalizedCode = String(code || '').trim();
      if (/^\d{6}$/.test(normalizedCode)) {
        selectedCode.value = normalizedCode;
        gridDraft.code = normalizedCode;
        gridDraft.id = '';
        gridResult.value = null;
        gridCandidates.value = [];
        if (gridSuggestedCode.value !== normalizedCode) gridSuggestion.value = null;
      }
      view.value = 'grid';
      persist();
      await nextTick();
      renderIcons();
      if (/^\d{6}$/.test(normalizedCode) && !gridLoading.value && !hasGridSuggestion.value) {
        await previewGrid();
      }
    }

    async function restoreGridSuggestion() {
      if (view.value !== 'grid' || gridLoading.value || hasGridSuggestion.value || hasGridResult.value) return;
      if (!/^\d{6}$/.test(normalizedGridCode.value)) return;
      await previewGrid();
    }

    async function switchView(nextView) {
      if (nextView === 'grid') {
        await openGridStrategy();
        return;
      }
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
      const icon = document.createElement('i');
      icon.setAttribute('data-lucide', tone === 'error' ? 'triangle-alert' : 'check-circle-2');
      icon.setAttribute('aria-hidden', 'true');
      const text = document.createElement('span');
      text.textContent = String(message ?? '');
      toast.appendChild(icon);
      toast.appendChild(text);
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

    watch(() => [filters.exchange, filters.market], () => {
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
    watch(() => gridDraft.code, () => {
      if (gridSuggestedCode.value !== normalizedGridCode.value) {
        gridSuggestion.value = null;
        gridResult.value = null;
      }
    });
    watch(monitorEnabled, () => {
      persist();
      showToast(monitorStatusLabel.value);
    });

    function armRefreshTimer() {
      clearInterval(refreshTimer.value);
      const intervalSeconds = Math.max(5, Number(settingsDraft.refreshInterval) || 15);
      refreshTimer.value = setInterval(() => {
        if (monitorEnabled.value && hasWatchTargets.value) refreshAll({ silent: true });
      }, intervalSeconds * 1000);
    }

    onMounted(async () => {
      await loadWorkspace();
      await loadSettings();
      await loadGridStrategies();
      draftWatchSuppressed.value = false;
      hydrateDraft();
      await refreshAll();
      await restoreGridSuggestion();
      renderIcons();
      armRefreshTimer();
      document.addEventListener('keydown', (event) => {
        if (event.key === '/' && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
          event.preventDefault();
          document.querySelector('.global-search input')?.focus();
        }
        const shortcut = { '1': 'overview', '2': 'screener', '3': 'grid', '4': 'plans', '5': 'monitor' }[event.key];
        if (shortcut && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') switchView(shortcut);
      });
    });

    onBeforeUnmount(() => {
      clearInterval(refreshTimer.value);
      clearTimeout(workspaceSyncTimer.value);
    });

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
      hasWatchTargets,
      monitorStatusLabel,
      monitorNextScan,
      activePlans,
      alerts,
      unreadAlerts,
      monitorEnabled,
      conflictVisible,
      adoptServerWorkspace,
      forceSaveWorkspace,
      settingsDraft,
      dataSources,
      settingsLoading,
      draft,
      gridDraft,
      gridLoading,
      gridSuggestion,
      gridResult,
      gridInstrument,
      normalizedGridCode,
      hasGridSuggestion,
      hasGridResult,
      gridCandidates,
      gridStrategies,
      loadGridStrategy,
      toggleGridStrategy,
      deleteGridStrategy,
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
      refreshIntervalLabel,
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
      compareChartSvg,
      quoteFor,
      planFor,
      calculateRr,
      calculateShares,
      signalText,
      signalClass,
      isWatched,
      switchView,
      openGridStrategy,
      restoreGridSuggestion,
      refreshAll,
      loadSettings,
      saveSettings,
      scanNow,
      previewGrid,
      backtestGrid,
      optimizeGrid,
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
