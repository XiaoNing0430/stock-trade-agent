import { defineStore } from 'pinia';
import { computed, ref, reactive } from 'vue';
import { useWorkspaceStore } from './useWorkspaceStore';

/**
 * 设置 store：设置草稿 / 数据源 / 加载保存。
 * 行为与重构前 app.ts setup() 对应域一致（字段名逐字保持）。
 */
export const useSettingsStore = defineStore('settings', () => {
  const workspace = useWorkspaceStore();
  const settingsDraft = reactive({
    workspaceName: '个人工作区',
    defaultCapital: 100000,
    monitorEnabled: true,
    realtimeSource: 'tencent',
    historySource: 'tencent',
    screenerSource: 'tencent',
    fundamentalSource: 'eastmoney',
    fallbackEnabled: true,
    refreshInterval: 15,
    cacheSeconds: 8,
    timeoutSeconds: 10,
    retryCount: 1,
    conflictPolicy: 'server',
    notifyDesktopAlert: true,
    notifyDesktopSystem: false,
    // 交易辅助 4 键（与后端 storage 默认一致，见 backend/storage.py DEFAULT_SETTINGS）
    riskPerTradePct: 1.0,
    rrRatio: 2.0,
    stopMode: 'atr',
    positionCapPct: 25,
    // 跨源校验三态开关（None=跟随环境 CROSS_CHECK_ENABLED）；token 不进 draft（掩码不回显，防全量保存误清除）
    crossCheckEnabled: null as boolean | null,
  });
  const tushareTokenInput = ref('');
  const dataSources = ref<any[]>([]);
  const settingsLoading = ref(false);
  const settingsTab = ref('workspace');
  const appliedSettings = ref<any>(null);

  // GET/PUT 响应 data 中 tushareToken 恒为掩码空串——绝不并入 draft（防全量保存误清除）
  function mergeSettingsData(data: Record<string, unknown> | undefined) {
    const { tushareToken: _masked, ...rest } = data || {};
    Object.assign(settingsDraft, rest);
  }

  const settingsDirty = computed(
    () =>
      tushareTokenInput.value !== '' ||
      (Boolean(appliedSettings.value) && JSON.stringify(settingsDraft) !== JSON.stringify(appliedSettings.value))
  );

  const refreshIntervalLabel = computed(() => `${settingsDraft.refreshInterval} 秒`);

  async function loadSettings() {
    settingsLoading.value = true;
    try {
      const payload = await workspace.requestJson('/api/settings');
      mergeSettingsData(payload.data);
      dataSources.value = payload.sources || [];
      appliedSettings.value = JSON.parse(JSON.stringify(settingsDraft));
    } catch {
      workspace.showToast('设置读取失败，正在使用本地默认值', 'error');
    } finally {
      settingsLoading.value = false;
    }
  }

  async function saveSettings() {
    settingsLoading.value = true;
    try {
      const body: Record<string, unknown> = { ...settingsDraft };
      if (tushareTokenInput.value) body.tushareToken = tushareTokenInput.value;
      const payload = await workspace.requestJson('/api/settings', {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      mergeSettingsData(payload.data);
      tushareTokenInput.value = '';
      appliedSettings.value = JSON.parse(JSON.stringify(settingsDraft));
      workspace.monitorEnabled = settingsDraft.monitorEnabled;
      workspace.showToast('网站设置已保存');
    } catch (error: any) {
      workspace.showToast(error.message || '设置保存失败', 'error');
    } finally {
      settingsLoading.value = false;
    }
  }

  async function clearTushareToken() {
    settingsLoading.value = true;
    try {
      const payload = await workspace.requestJson('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ tushareToken: '' }),
      });
      mergeSettingsData(payload.data);
      tushareTokenInput.value = '';
      workspace.showToast('Tushare Token 已清除');
    } catch (error: any) {
      workspace.showToast(error.message || '清除失败', 'error');
    } finally {
      settingsLoading.value = false;
    }
  }

  return {
    settingsDraft,
    dataSources,
    settingsLoading,
    settingsTab,
    appliedSettings,
    settingsDirty,
    refreshIntervalLabel,
    tushareTokenInput,
    loadSettings,
    saveSettings,
    clearTushareToken,
  };
});
