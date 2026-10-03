import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { dedupeSystemAlert } from '@/modules/alertUtils';
import type { Alert } from '@/types/models';
import { useWorkspaceStore } from './useWorkspaceStore';
import { useSettingsStore } from './useSettingsStore';
import { useScanStore } from './useScanStore';

/**
 * 提醒 store：提醒增删改 / 过滤 / 通知面板 / 桌面通知。
 * alerts 数据所有权在 useWorkspaceStore（持久化/同步），此 store 通过跨 store 引用操作。
 * 行为与重构前 app.ts setup() 对应域一致（字段名逐字保持）。
 * 例外：扫描命中（scan.scanAlerts）归 useScanStore 本地，这里只做合成只读视图（spec Task 6）。
 */
export const useAlertsStore = defineStore('alerts', () => {
  const workspace = useWorkspaceStore();
  const scan = useScanStore();
  const alertFilter = ref('all');
  const notifOpen = ref(false);
  const hubTab = ref('alerts');
  const notificationPermission = ref(typeof Notification !== 'undefined' ? Notification.permission : 'denied');

  // 全量提醒 = 扫描命中 + 工作区提醒（brief 组合顺序：扫描在前）。扫描项 kind 恒为 'alert'，
  // 永不落入 'system' 过滤；工作区提醒不受影响。ScanAlertItem 结构兼容 Alert（code/strategyId/
  // firstSeen 已并入 Alert 可选字段），统一以 Alert[] 流向模板。
  const allAlerts = computed<Alert[]>(() => [...scan.scanAlerts, ...workspace.alerts]);

  const filteredAlerts = computed(() => {
    if (alertFilter.value === 'trade') return allAlerts.value.filter((alert) => alert.kind !== 'system');
    if (alertFilter.value === 'system') return allAlerts.value.filter((alert) => alert.kind === 'system');
    return allAlerts.value;
  });

  // 未读计数 = 原计数（workspace 未读）+ scan.unreadScanCount。
  // 不能把 allAlerts 直接套进 !read 过滤再叠加 scan.unreadScanCount：扫描项恒 read:false
  //（markSeen 只写 seen 时间戳不改 read），会把已读扫描项重复计数（brief 片段与自身 Step 1 测试矛盾，以测试为准）。
  const unreadAlerts = computed(
    () => workspace.alerts.filter((alert) => !alert.read && alert.kind !== 'system').length + scan.unreadScanCount
  );

  const unreadSystemCount = computed(
    () => allAlerts.value.filter((alert) => alert.kind === 'system' && !alert.read).length
  );

  const unreadTotalCount = computed(
    () => workspace.alerts.filter((alert) => !alert.read).length + scan.unreadScanCount
  );

  const recentNotifs = computed(() => filteredAlerts.value.slice(0, 8));

  function addAlert(kind: string, title: string, message: string, options: { deferPersist?: boolean } = {}) {
    const now = Date.now();
    const result = dedupeSystemAlert(workspace.alerts, kind, title, message, now);
    workspace.alerts = result.alerts;
    if (result.count === 1 && workspace.alerts.length) {
      workspace.alerts[0].time = '刚刚';
    }
    if (!options.deferPersist) workspace.persist();
    if (result.count === 1) {
      const settings = useSettingsStore();
      const desktopAllowed =
        kind === 'system' ? settings.settingsDraft.notifyDesktopSystem : settings.settingsDraft.notifyDesktopAlert;
      if (desktopAllowed && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
        new Notification(title, { body: message });
      }
    }
  }

  function toggleNotifCenter() {
    notifOpen.value = !notifOpen.value;
    if (notifOpen.value) workspace.renderIcons();
  }

  function goAlertCenter() {
    notifOpen.value = false;
    hubTab.value = 'alerts';
    // switchView('settings') — 由 app.ts 协调
  }

  function markAlertRead(id: string) {
    const alert = workspace.alerts.find((item) => item.id === id);
    if (!alert) return;
    alert.read = true;
    workspace.persist();
  }

  function clearReadAlerts() {
    workspace.alerts = workspace.alerts.filter((alert) => !alert.read);
    workspace.persist();
    workspace.showToast('已清空已读提醒');
  }

  /** 扫描命中已读（薄封装）：透传 scan store 的 seen 时间戳；扫描项不走 workspace.alerts.read。 */
  function markScanSeen(strategyId: string): void {
    scan.markSeen(strategyId);
  }

  function requestNotifications() {
    notifOpen.value = false;
    if (!('Notification' in window)) {
      workspace.showToast('当前浏览器不支持桌面提醒', 'error');
      return;
    }
    if (Notification.permission === 'granted') {
      new Notification('Atlas 盯盘提醒已开启', { body: '价格触发交易计划时会提醒你。' });
      workspace.showToast('桌面提醒已开启');
      return;
    }
    Notification.requestPermission().then((permission) => {
      notificationPermission.value = permission;
      if (permission === 'granted') {
        new Notification('Atlas 盯盘提醒已开启', { body: '价格触发交易计划时会提醒你。' });
        workspace.showToast('桌面提醒已开启');
      } else {
        workspace.showToast('未获得桌面提醒权限', 'error');
      }
    });
  }

  return {
    alertFilter,
    notifOpen,
    hubTab,
    notificationPermission,
    filteredAlerts,
    unreadAlerts,
    unreadSystemCount,
    unreadTotalCount,
    recentNotifs,
    addAlert,
    toggleNotifCenter,
    goAlertCenter,
    markAlertRead,
    markScanSeen,
    clearReadAlerts,
    requestNotifications,
  };
});
