<template>
  <div v-cloak class="app-shell">
    <div v-if="conflictVisible" class="conflict-banner" role="alert">
      <i data-lucide="triangle-alert" aria-hidden="true"></i>
      <span>检测到其他页面更新了工作区数据</span>
      <button class="button button-secondary" type="button" @click="adoptServerWorkspace">采用服务器版本</button>
      <button class="button button-primary" type="button" @click="forceSaveWorkspace">用本地覆盖</button>
      <button class="icon-button" type="button" aria-label="忽略冲突提示" @click="conflictVisible = false">
        <i data-lucide="x" aria-hidden="true"></i>
      </button>
    </div>
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark" aria-hidden="true">A</div>
        <div class="brand-copy">
          <strong>Atlas</strong>
          <span>交易工作台</span>
        </div>
      </div>

      <nav class="primary-nav" aria-label="主导航">
        <template v-for="section in navSections" :key="section.key">
          <div v-if="section.group" class="sidebar-section-label">{{ section.group.label }}</div>
          <button
            v-for="item in section.items"
            :key="item.id"
            class="nav-item"
            :class="{ 'is-active': view === item.id }"
            type="button"
            :aria-label="item.label"
            @click="switchView(item.id)"
          >
            <i :data-lucide="item.icon" aria-hidden="true"></i>
            <span>{{ item.label }}</span>
            <em v-if="item.id === 'settings' && unreadTotalCount" class="nav-count">{{
              unreadTotalCount > 99 ? '99+' : unreadTotalCount
            }}</em>
          </button>
        </template>
      </nav>

      <div class="sidebar-spacer"></div>

      <button
        :key="currentTheme"
        class="sidebar-theme-toggle"
        type="button"
        :aria-label="currentTheme === 'dark' ? '切换到浅色主题' : '切换到深色主题'"
        @click="onToggleTheme"
      >
        <i :data-lucide="currentTheme === 'dark' ? 'sun' : 'moon'" aria-hidden="true"></i>
        <span>{{ currentTheme === 'dark' ? '浅色模式' : '深色模式' }}</span>
      </button>

      <span class="sidebar-version">v{{ APP_VERSION }}</span>
    </aside>

    <main class="main-area">
      <header class="topbar">
        <div class="topbar-context">
          <span class="topbar-eyebrow">A-SHARE / REAL QUOTES</span>
          <div class="topbar-title-row">
            <h1>{{ currentViewMeta.title }}</h1>
          </div>
          <p>{{ currentViewMeta.subtitle }}</p>
        </div>

        <div class="topbar-actions">
          <div class="global-search">
            <i data-lucide="search" aria-hidden="true"></i>
            <input
              v-model.trim="globalSearch"
              type="search"
              placeholder="搜索股票代码或名称"
              aria-label="搜索股票代码或名称"
              @keydown.enter="searchSymbol"
            />
            <kbd>/</kbd>
          </div>
          <div class="notif-wrap">
            <button
              class="icon-button"
              type="button"
              aria-label="通知中心"
              data-tooltip="通知中心"
              @click="toggleNotifCenter"
            >
              <i data-lucide="bell" aria-hidden="true"></i>
              <span v-if="unreadTotalCount" class="notif-badge">{{
                unreadTotalCount > 99 ? '99+' : unreadTotalCount
              }}</span>
            </button>
            <div v-if="notifOpen" class="notif-backdrop" @click="notifOpen = false"></div>
            <div v-if="notifOpen" class="notif-panel" role="dialog" aria-label="通知中心">
              <div class="notif-head">
                <strong>通知中心</strong
                ><button class="text-button" type="button" @click="clearReadAlerts">清空已读</button>
              </div>
              <div class="alert-filters" role="tablist" aria-label="通知分类">
                <button
                  v-for="option in [
                    { id: 'all', label: '全部' },
                    { id: 'trade', label: '盯盘' },
                    { id: 'system', label: '系统' },
                  ]"
                  :key="option.id"
                  type="button"
                  role="tab"
                  :class="['alert-filter-chip', { 'is-active': alertFilter === option.id }]"
                  :aria-selected="alertFilter === option.id"
                  @click="alertFilter = option.id"
                >
                  {{ option.label }}
                </button>
              </div>
              <div class="notif-list">
                <div
                  v-for="alert in recentNotifs"
                  :key="alert.id"
                  class="alert-item"
                  :class="{ unread: isItemUnread(alert) }"
                >
                  <div
                    :class="[
                      'alert-icon',
                      alert.kind === 'success'
                        ? 'success'
                        : alert.kind === 'info' || alert.kind === 'system'
                          ? 'info'
                          : '',
                    ]"
                  >
                    <i
                      :data-lucide="
                        alert.kind === 'success'
                          ? 'check-circle-2'
                          : alert.kind === 'alert'
                            ? 'triangle-alert'
                            : alert.kind === 'system'
                              ? 'wrench'
                              : 'bell-ring'
                      "
                      aria-hidden="true"
                    ></i>
                  </div>
                  <div class="alert-copy">
                    <strong>{{ alert.title }}</strong
                    ><span>{{ alert.message }}</span>
                    <button
                      v-if="alert.code && alert.strategyId"
                      class="text-button"
                      type="button"
                      data-testid="alert-code-chip"
                      @click="openScanDraft(alert)"
                    >
                      {{ alert.code }} 生成草案
                    </button>
                    <div class="alert-meta">
                      <span>{{ alert.time || formatTime(alert.createdAtMs) }}</span
                      ><!-- 扫描项已读走 markScanSeen（面板打开即批量标记），workspace.alerts.find 必然落空 → 隐藏失效按钮 -->
                      <button
                        v-if="!alert.read && !(alert.code && alert.strategyId)"
                        class="text-button"
                        type="button"
                        @click="markAlertRead(alert.id)"
                      >
                        标记已读
                      </button>
                    </div>
                  </div>
                </div>
                <div v-if="!recentNotifs.length" class="empty-state">
                  <i data-lucide="bell-off" aria-hidden="true"></i><strong>暂无提醒</strong
                  ><span>切换分类查看其他提醒。</span>
                </div>
              </div>
              <div class="notif-foot">
                <button class="text-button" type="button" @click="goAlertCenter">
                  <i data-lucide="arrow-right" aria-hidden="true"></i>前往提醒中心
                </button>
                <button
                  v-if="notificationPermission !== 'granted'"
                  class="text-button"
                  type="button"
                  @click="requestNotifications"
                >
                  <i data-lucide="bell-plus" aria-hidden="true"></i>开启桌面通知
                </button>
              </div>
            </div>
          </div>
          <button
            class="topbar-date market-status-control"
            type="button"
            :data-state="dataState"
            data-testid="market-status-control"
            data-tooltip="刷新行情"
            :title="`${providerLabel} · ${dataStatusText}`"
            :aria-label="`${marketStatusLabel}，${marketStatusTimeLabel}，点击刷新行情`"
            @click="refreshAll()"
          >
            <span class="status-dot" :class="dataState"></span>
            <span class="market-status-label">{{ marketStatusLabel }}</span>
            <span class="market-status-time">{{ marketStatusTimeLabel }}</span>
            <i data-lucide="refresh-cw" aria-hidden="true" :class="{ spinning: loading }"></i>
          </button>
        </div>
      </header>

      <div class="content-area">
        <view-overview v-if="view === 'overview'"></view-overview>
        <view-screener v-else-if="view === 'screener'"></view-screener>
        <view-stock-detail v-else-if="view === 'stock-detail'"></view-stock-detail>
        <view-grid v-else-if="view === 'grid'"></view-grid>
        <section v-else-if="view === 'exec'" class="mobile-exec-tabs" role="tablist" aria-label="执行分组">
          <button
            type="button"
            role="tab"
            :class="['mobile-exec-tab', { 'is-active': mobileExecTab === 'plans' }]"
            :aria-selected="mobileExecTab === 'plans'"
            @click="mobileExecTab = 'plans'"
          >
            交易计划
          </button>
          <button
            type="button"
            role="tab"
            :class="['mobile-exec-tab', { 'is-active': mobileExecTab === 'alerts' }]"
            :aria-selected="mobileExecTab === 'alerts'"
            @click="mobileExecTab = 'alerts'"
          >
            盯盘
          </button>
        </section>

        <view-plans v-else-if="view === 'plans' || execShowsPlans"></view-plans>
        <view-monitor v-else-if="view === 'monitor' || execShowsAlerts"></view-monitor>
        <view-portfolio v-else-if="view === 'portfolio'"></view-portfolio>
        <view-settings v-else-if="view === 'settings'"></view-settings>

        <footer class="app-footer">
          <span>Atlas Trading Desk · A 股真实行情工作台</span>
          <span>研究工具不构成投资建议</span>
        </footer>
      </div>
    </main>

    <plan-draft-dialog></plan-draft-dialog>

    <nav class="bottom-nav" aria-label="手机端主导航">
      <button
        v-for="slot in mobileBarItems"
        :key="slot.id"
        type="button"
        :class="{ 'is-active': view === slot.id }"
        @click="switchView(slot.id)"
      >
        <i :data-lucide="slot.icon" aria-hidden="true"></i><span>{{ slot.shortLabel }}</span>
      </button>
      <button
        type="button"
        :class="{ 'is-active': moreSheetOpen || isMoreView }"
        aria-label="更多"
        @click="openMoreSheet"
      >
        <i data-lucide="more-horizontal" aria-hidden="true"></i><span>更多</span
        ><em v-if="unreadTotalCount" class="nav-count">{{ unreadTotalCount > 99 ? '99+' : unreadTotalCount }}</em>
      </button>
    </nav>

    <div v-if="moreSheetOpen" class="more-sheet-backdrop" @click.self="moreSheetOpen = false">
      <section class="more-sheet" role="dialog" aria-modal="true" aria-label="更多导航">
        <template v-for="section in moreSections" :key="section.key">
          <div class="more-sheet-group">{{ section.group?.label }}</div>
          <button
            v-for="item in section.items"
            :key="item.id"
            class="more-sheet-item"
            type="button"
            @click="goFromMoreSheet(item.id)"
          >
            <i :data-lucide="item.icon" aria-hidden="true"></i><span>{{ item.label }}</span
            ><em v-if="item.id === 'settings' && unreadTotalCount" class="nav-count">{{
              unreadTotalCount > 99 ? '99+' : unreadTotalCount
            }}</em>
          </button>
        </template>
      </section>
    </div>
  </div>
  <div class="toast-region" id="toast-region" aria-live="polite" aria-atomic="true"></div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue';
import { storeToRefs } from 'pinia';
import { appOptions } from '@/app';
import { APP_VERSION, NAV_GROUPS, NAV_ITEMS } from '@/modules/constants';
import { formatTime } from '@/modules/format';
import { effectiveTheme, toggleTheme } from '@/modules/theme';
import type { Alert } from '@/types/models';
import PlanDraftDialog from '@/components/PlanDraftDialog.vue';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { useAlertsStore } from '@/stores/useAlertsStore';
import { useAssistStore } from '@/stores/useAssistStore';
import { useScanStore, type ScanAlertItem } from '@/stores/useScanStore';

// 安装跨 store 协调逻辑（watch / 生命周期），返回值为空
appOptions.setup();

const workspace = useWorkspaceStore();
const quotes = useQuotesStore();
const alerts = useAlertsStore();
const assist = useAssistStore();
const scan = useScanStore();

const { conflictVisible, adoptServerWorkspace, forceSaveWorkspace, refreshAll, renderIcons } = workspace;
const {
  view,
  dataState,
  providerLabel,
  dataStatusText,
  currentViewMeta,
  globalSearch,
  marketStatusLabel,
  marketStatusTimeLabel,
  loading,
  mobileExecTab,
  execShowsPlans,
  execShowsAlerts,
} = storeToRefs(quotes);
const { switchView, searchSymbol } = quotes;
const { unreadTotalCount, notifOpen, alertFilter, recentNotifs, notificationPermission } = storeToRefs(alerts);
const { toggleNotifCenter, clearReadAlerts, markAlertRead, markScanSeen, goAlertCenter, requestNotifications } = alerts;

/** 侧栏分区：置顶项（group === null）在前，随后按 NAV_GROUPS 顺序展开。 */
const navSections = computed(() => [
  {
    key: 'top',
    group: null as { id: string; label: string } | null,
    items: NAV_ITEMS.filter((item) => item.group === null),
  },
  ...NAV_GROUPS.map((group) => ({
    key: group.id,
    group: group as { id: string; label: string } | null,
    items: NAV_ITEMS.filter((item) => item.group === group.id),
  })),
]);

/** 手机底部栏 4 个直达格（其余进「更多」抽屉）。短标签取自 NAV_ITEMS.shortLabel。 */
const MOBILE_BAR_IDS = ['overview', 'screener', 'plans', 'monitor'] as const;
const mobileBarItems = NAV_ITEMS.filter((item) => (MOBILE_BAR_IDS as readonly string[]).includes(item.id));

const moreSheetOpen = ref(false);

/** 抽屉分区：与桌面同一套分组，只保留未出现在底部栏的项。 */
const moreSections = computed(() =>
  NAV_GROUPS.map((group) => ({
    key: group.id,
    group,
    items: NAV_ITEMS.filter(
      (item) => item.group === group.id && !(MOBILE_BAR_IDS as readonly string[]).includes(item.id)
    ),
  })).filter((section) => section.items.length > 0)
);

const isMoreView = computed(() =>
  moreSections.value.some((section) => section.items.some((item) => item.id === view.value))
);

/** 抽屉内图标同样需要 createIcons 渲染（lucide 按需注册表）。 */
function openMoreSheet(): void {
  moreSheetOpen.value = true;
  nextTick(renderIcons);
}

function goFromMoreSheet(id: string): void {
  moreSheetOpen.value = false;
  switchView(id);
}

// 侧栏主题快捷开关：effectiveTheme 为 theme 模块级 computed，模板引用自动解包（useWorkspaceStore 复用既有 workspace 实例）
const currentTheme = effectiveTheme;

/** 切换主题后等 Vue 完成补丁，再重渲染 lucide 图标（sun/moon 随主题互换）。 */
function onToggleTheme(): void {
  toggleTheme();
  nextTick(() => renderIcons());
}

/** 面板行未读态：工作区提醒看 read 标志；扫描项 read 恒 false（静态占位），已读语义走 scan 的 seen 时间戳。 */
function isItemUnread(item: Alert): boolean {
  return item.code && item.strategyId ? scan.isUnseen(item as ScanAlertItem) : !item.read;
}

/** 扫描命中项代码片：名称从 message 提取不可靠 → 只传 code，让对话框走实时行情路径拿全量（spec FR-9）。 */
function openScanDraft(item: Alert): void {
  if (!item.code) return;
  // openFor 自吞错误（内部 catch + toast），此处无需 await
  assist.openFor({ code: item.code, source: `scan:${item.strategyId}` });
  markScanSeen(item.strategyId || '');
}

// 打开通知面板即批量标记可见扫描策略已读（拉取新命中后打开面板 → 徽标归零）
watch(notifOpen, (open) => {
  if (!open) return;
  scan.hits.forEach((hit) => markScanSeen(hit.strategyId));
});

// 视图切换（含底部栏直达格）即关闭「更多」抽屉，避免抽屉残留遮挡新视图
watch(view, () => {
  moreSheetOpen.value = false;
});

onMounted(() => renderIcons());
</script>
