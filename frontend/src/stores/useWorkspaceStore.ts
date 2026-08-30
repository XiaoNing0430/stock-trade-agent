import { defineStore } from 'pinia';
import { computed, nextTick, ref } from 'vue';
import { createIcons } from 'lucide';
import type { Alert, Plan } from '@/types/models';
import { DEFAULT_ALERTS, DEFAULT_WATCHLIST, STORAGE_KEY } from '@/modules/constants';
import { useQuotesStore } from './useQuotesStore';
import { useScreenerStore } from './useScreenerStore';
import { useSettingsStore } from './useSettingsStore';
import { useAlertsStore } from './useAlertsStore';
import { usePlansStore } from './usePlansStore';

/**
 * 工作区 store：自选列表 / 计划 / 提醒 / 服务端同步 / 409 冲突策略 / 本地持久化，
 * 同时承载共享 UI 能力（requestJson / showToast / renderIcons）供其他 store 调用。
 * 行为与重构前 app.ts setup() 对应域一致（字段名逐字保持）。
 */
export const useWorkspaceStore = defineStore('workspace', () => {
  function loadStorage() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    } catch {
      return {};
    }
  }

  const saved = loadStorage();
  const watchlistCodes = ref<string[]>(Array.isArray(saved.watchlist) ? saved.watchlist : DEFAULT_WATCHLIST);
  const plans = ref<Plan[]>(Array.isArray(saved.plans) ? saved.plans : []);
  const alerts = ref<Alert[]>(Array.isArray(saved.alerts) ? saved.alerts : DEFAULT_ALERTS);
  const workspaceSynced = ref(false);
  const workspaceRevision = ref(Number(saved.workspaceRevision) || 0);
  const conflictVisible = ref(false);
  const conflictSnapshot = ref<any>(null);
  const draftDirty = ref(false);
  const draftWatchSuppressed = ref(true);
  const monitorEnabled = ref(saved.monitorEnabled !== false);
  const workspaceSyncTimer = ref<any>(null);
  const serverStaleAge = ref<any>(null);

  async function requestJson(url: string, options: Record<string, any> = {}): Promise<any> {
    const response = await fetch(url, {
      cache: 'no-store',
      ...options,
      headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...(options.headers || {}) },
    });
    const staleHeader = response.headers.get('x-atlas-stale');
    if (staleHeader !== null) {
      serverStaleAge.value = Number(staleHeader);
    }
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(payload.detail?.error || payload.error || `接口返回 ${response.status}`) as Error & {
        status?: number;
        code?: string;
        payload?: unknown;
      };
      error.status = response.status;
      error.code = payload.detail?.code || payload.code || 'UNKNOWN';
      error.payload = payload;
      throw error;
    }
    return payload;
  }

  function renderIcons() {
    if (createIcons) {
      createIcons({ attrs: { width: 16, height: 16, 'stroke-width': 1.8 } });
    }
  }

  function showToast(message: string, tone = 'success') {
    const region = document.getElementById('toast-region');
    if (!region) return;
    const messageText = String(message ?? '');
    const toast = document.createElement('div');
    toast.className = `toast ${tone === 'error' ? 'error' : ''}`;
    const icon = document.createElement('i');
    icon.setAttribute('data-lucide', tone === 'error' ? 'triangle-alert' : 'check-circle-2');
    icon.setAttribute('aria-hidden', 'true');
    const text = document.createElement('span');
    text.textContent = messageText;
    toast.appendChild(icon);
    toast.appendChild(text);
    region.appendChild(toast);
    renderIcons();
    setTimeout(() => {
      toast.remove();
    }, 3200);
  }

  function persistLocal() {
    try {
      const quotes = useQuotesStore();
      const screener = useScreenerStore();
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({
          view: quotes.view.value,
          selectedCode: quotes.selectedCode.value,
          presetName: screener.presetName.value,
          watchlist: watchlistCodes.value,
          plans: plans.value,
          alerts: alerts.value,
          monitorEnabled: monitorEnabled.value,
          workspaceRevision: workspaceRevision.value,
          filters: { ...screener.filters },
          marketCache: {
            provider: quotes.market.provider,
            fetchedAt: quotes.market.fetchedAt,
            quotes: quotes.market.quotes,
            indices: quotes.market.indices,
          },
        })
      );
    } catch {
      // Storage is optional; real quotes continue to work without it.
    }
  }

  function persist() {
    persistLocal();
    scheduleWorkspaceSync();
  }

  function workspacePayload() {
    return {
      watchlist: watchlistCodes.value,
      plans: plans.value,
      alerts: alerts.value,
    };
  }

  let workspaceSyncInFlight = false;
  let workspaceSyncQueued = false;

  function scheduleWorkspaceSync() {
    if (!workspaceSynced.value) return;
    if (workspaceSyncInFlight) {
      workspaceSyncQueued = true;
      return;
    }
    clearTimeout(workspaceSyncTimer.value);
    workspaceSyncTimer.value = setTimeout(async () => {
      workspaceSyncInFlight = true;
      try {
        await requestJson(`/api/workspace?baseRevision=${encodeURIComponent(workspaceRevision.value)}`, {
          method: 'PUT',
          body: JSON.stringify(workspacePayload()),
        });
      } catch (error: any) {
        if (error.status === 409) {
          workspaceSyncQueued = false;
          const snapshot = error.payload?.detail?.workspace;
          const policy = useSettingsStore().settingsDraft.conflictPolicy;
          if (policy === 'ask' || !snapshot) {
            showConflictBanner(snapshot);
          } else if (policy === 'local') {
            await pushLocalWorkspace('检测到冲突，已自动用本地版本覆盖服务器');
          } else {
            adoptServerSnapshot(snapshot, true);
          }
        } else {
          addAlert('system', '工作区同步失败', error.message || '持久化服务暂不可用，浏览器存储兜底。', {
            deferPersist: true,
          });
        }
      } finally {
        workspaceSyncInFlight = false;
        if (workspaceSyncQueued) {
          workspaceSyncQueued = false;
          scheduleWorkspaceSync();
        }
      }
    }, 350);
  }

  function showConflictBanner(snapshot: any) {
    conflictSnapshot.value = snapshot;
    conflictVisible.value = true;
    showToast('其他页面已更新工作区数据，请选择保留哪一版', 'error');
  }

  function adoptServerSnapshot(snapshot: any, auto = false) {
    const localReadIds = new Set(alerts.value.filter((alert) => alert.read).map((alert) => alert.id));
    watchlistCodes.value = snapshot.watchlist || [];
    plans.value = snapshot.plans || [];
    alerts.value = (snapshot.alerts || []).map((alert: Alert) =>
      localReadIds.has(alert.id) ? { ...alert, read: true } : alert
    );
    workspaceRevision.value = Number(snapshot.revision || 0);
    addAlert(
      'system',
      '工作区冲突已自动处理',
      auto ? '检测到其他页面更新，已自动采用服务器版本。' : '已手动采用服务器最新数据。',
      { deferPersist: true }
    );
    persistLocal();
    showToast(auto ? '检测到其他页面更新，已自动采用服务器版本' : '已采用服务器最新数据');
  }

  async function adoptServerWorkspace() {
    const snapshot = conflictSnapshot.value;
    conflictVisible.value = false;
    if (!snapshot) return;
    adoptServerSnapshot(snapshot, false);
  }

  async function pushLocalWorkspace(successMessage: string) {
    try {
      const result = await requestJson('/api/workspace?force=true', {
        method: 'PUT',
        body: JSON.stringify(workspacePayload()),
      });
      workspaceRevision.value = Number(result.revision || 0);
      addAlert('system', '工作区已用本地版本覆盖', successMessage);
      persist();
      showToast(successMessage);
    } catch (error: any) {
      showToast(error.message || '覆盖失败', 'error');
    }
  }

  async function forceSaveWorkspace() {
    conflictVisible.value = false;
    await pushLocalWorkspace('已用本地数据覆盖服务器');
  }

  async function loadWorkspace() {
    try {
      const remote = await requestJson('/api/workspace');
      workspaceRevision.value = Number(remote.revision || 0);
      const hasRemoteData =
        (remote.watchlist || []).length || (remote.plans || []).length || (remote.alerts || []).length;
      if (hasRemoteData) {
        watchlistCodes.value = remote.watchlist || [];
        plans.value = remote.plans || [];
        alerts.value = remote.alerts || [];
      }
    } catch {
      // Existing local state is intentionally retained for first-run or offline use.
    } finally {
      workspaceSynced.value = true;
      persist();
    }
  }

  function addAlert(kind: string, title: string, message: string, options: { deferPersist?: boolean } = {}) {
    return useAlertsStore().addAlert(kind, title, message, options);
  }

  const refreshTimer = ref<any>(null);
  let refreshInFlight = false;
  let lastRecordedDataState = '';

  async function refreshAll(options: { silent?: boolean } = {}) {
    const silent = Boolean(options.silent);
    const quotes = useQuotesStore();
    const screener = useScreenerStore();
    const plans = usePlansStore();
    if (refreshInFlight) {
      // 已有刷新进行中：定时轮询直接跳过，避免慢网络下请求堆积。
      if (silent) return;
    }
    if (!silent) quotes.loading = true;
    refreshInFlight = true;
    try {
      quotes.errorMessage = '';
      const tasks = [quotes.fetchMarket(), screener.fetchScreener()];
      const now = Date.now();
      if (!quotes.indexHistory.length || now - quotes.indexHistoryFetchedAt > 60000) {
        tasks.push(quotes.fetchHistory('000001', 'index'));
      }
      if (
        !quotes.selectedHistory.length ||
        quotes.selectedHistoryCode !== quotes.selectedCode ||
        now - quotes.selectedHistoryFetchedAt > 60000
      ) {
        tasks.push(quotes.fetchHistory(quotes.selectedCode, 'selected'));
      }
      const results = await Promise.allSettled(tasks);
      serverStaleAge.value = null; // 每轮刷新重置服务端陈旧标记
      const failures = results.filter((result) => result.status === 'rejected');
      if (failures.length && !quotes.market.quotes.length && !screener.screenRows.length && !serverStaleAge.value) {
        quotes.dataState = 'error';
        quotes.errorMessage = (failures[0] as any).reason?.message || '真实行情暂时不可用';
      } else if (failures.length && !serverStaleAge.value) {
        quotes.dataState = 'stale';
        quotes.errorMessage = '行情接口部分失败，当前页面保留最近一次成功数据。';
      } else if (serverStaleAge.value !== null) {
        quotes.dataState = 'stale';
        const ageSeconds = serverStaleAge.value;
        quotes.errorMessage = `行情源暂时不可用，展示服务器缓存的真实行情（约 ${
          ageSeconds >= 60 ? Math.round(ageSeconds / 60) + ' 分钟前' : '刚获取'
        }）。`;
      } else {
        quotes.dataState = 'live';
      }
      if (quotes.dataState !== lastRecordedDataState) {
        if (quotes.dataState === 'stale') {
          addAlert('system', '行情数据降级', '部分接口失败，当前页面保留最近一次成功数据，来源可能已切换。');
        } else if (quotes.dataState === 'error') {
          addAlert('system', '行情获取失败', quotes.errorMessage || '真实行情暂时不可用。');
        } else if (quotes.dataState === 'live' && lastRecordedDataState && lastRecordedDataState !== 'live') {
          addAlert('system', '行情已恢复', '实时行情接口恢复正常。');
        }
        lastRecordedDataState = quotes.dataState;
      }
      if (quotes.market.errors.length && !quotes.errorMessage) {
        quotes.errorMessage = '部分股票报价暂时不可用，已保留其他实时结果。';
      }
      plans.expirePlans();
      if (failures.length === 0) persist();
    } finally {
      refreshInFlight = false;
      quotes.loading = false;
      await nextTick();
      renderIcons();
    }
  }

  function armRefreshTimer() {
    clearInterval(refreshTimer.value);
    const settings = useSettingsStore();
    const intervalSeconds = Math.max(5, Number(settings.settingsDraft.refreshInterval) || 15);
    refreshTimer.value = setInterval(() => {
      const quotes = useQuotesStore();
      if (monitorEnabled.value && quotes.hasWatchTargets) refreshAll({ silent: true });
    }, intervalSeconds * 1000);
  }

  const activePlans = computed(() =>
    plans.value.filter((plan) => plan.status === '执行中' || plan.status === '已触发')
  );

  const unreadAlerts = computed(() => alerts.value.filter((alert) => !alert.read && alert.kind !== 'system').length);

  return {
    watchlistCodes,
    plans,
    alerts,
    workspaceSynced,
    workspaceRevision,
    conflictVisible,
    conflictSnapshot,
    draftDirty,
    draftWatchSuppressed,
    monitorEnabled,
    workspaceSyncTimer,
    serverStaleAge,
    refreshTimer,
    loadStorage,
    requestJson,
    renderIcons,
    showToast,
    persistLocal,
    persist,
    workspacePayload,
    scheduleWorkspaceSync,
    showConflictBanner,
    adoptServerSnapshot,
    adoptServerWorkspace,
    pushLocalWorkspace,
    forceSaveWorkspace,
    loadWorkspace,
    refreshAll,
    armRefreshTimer,
    activePlans,
    unreadAlerts,
  };
});
