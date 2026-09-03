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
  });
  const dataSources = ref<any[]>([]);
  const settingsLoading = ref(false);
  const settingsTab = ref('workspace');
  const appliedSettings = ref<any>(null);

  const settingsDirty = computed(
    () => Boolean(appliedSettings.value) && JSON.stringify(settingsDraft) !== JSON.stringify(appliedSettings.value)
  );

  const refreshIntervalLabel = computed(() => `${settingsDraft.refreshInterval} 秒`);

  async function loadSettings() {
    settingsLoading.value = true;
    try {
      const payload = await workspace.requestJson('/api/settings');
      Object.assign(settingsDraft, payload.data || {});
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
      const payload = await workspace.requestJson('/api/settings', {
        method: 'PUT',
        body: JSON.stringify(settingsDraft),
      });
      Object.assign(settingsDraft, payload.data || {});
      appliedSettings.value = JSON.parse(JSON.stringify(settingsDraft));
      workspace.monitorEnabled = settingsDraft.monitorEnabled;
      workspace.showToast('网站设置已保存');
    } catch (error: any) {
      workspace.showToast(error.message || '设置保存失败', 'error');
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
    loadSettings,
    saveSettings,
  };
});
