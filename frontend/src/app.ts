// @ts-nocheck — 迁移期策略：此文件自 frontend/app.js 机械迁移（函数体零改动），
// strict TS 对其产生大量隐式 any 报错。Phase 3（eng-refactor）将把 monolith setup()
// 拆解为 8 个 Pinia store 时正式补全类型并移除本注释。
import { watch, onMounted, onBeforeUnmount, nextTick } from 'vue';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { useScreenerStore } from '@/stores/useScreenerStore';
import { usePlansStore } from '@/stores/usePlansStore';
import { useSettingsStore } from '@/stores/useSettingsStore';
import { useGridStore } from '@/stores/useGridStore';
import { useStrategyStore } from '@/stores/useStrategyStore';

/**
 * 应用协调层 — 安装跨 store 响应式副作用（watch）与生命周期钩子。
 * App.vue 的 script setup 调用此函数以注册这些协调逻辑，视图与 App.vue 模板直接组合 8 个 Pinia store。
 */
export const appOptions = {
  setup() {
    const workspace = useWorkspaceStore();
    const quotes = useQuotesStore();
    const screener = useScreenerStore();
    const plans = usePlansStore();
    const settings = useSettingsStore();
    const grid = useGridStore();

    // 筛选条件变更 → 持久化 + 重新扫描
    watch(
      () => [screener.filters.exchange, screener.filters.market],
      () => {
        workspace.persist();
        if (!quotes.loading) screener.scanNow();
      }
    );
    // 计划草稿代码变更 → 报价 + 计算
    watch(
      () => plans.draft.code,
      async () => {
        if (!workspace.draftWatchSuppressed && !workspace.draftDirty) {
          quotes.selectedCode = plans.draft.code;
          await quotes.ensureQuote(plans.draft.code);
          plans.hydrateDraft();
        }
      }
    );
    // 计划草稿内容变更 → 标记脏
    watch(
      () => plans.draft,
      () => {
        if (!workspace.draftWatchSuppressed) workspace.draftDirty = true;
      },
      { deep: true }
    );
    // 视图切换 → 刷新图标
    watch(
      () => quotes.view,
      () => nextTick(workspace.renderIcons)
    );
    // 网格草稿代码变更 → 清空建议/结果
    watch(
      () => grid.gridDraft.code,
      () => {
        if (grid.gridSuggestedCode !== grid.normalizedGridCode) {
          grid.gridSuggestion = null;
          grid.gridResult = null;
        }
      }
    );
    // 盯盘开关 → 持久化 + 提示
    watch(
      () => workspace.monitorEnabled,
      () => {
        workspace.persist();
        workspace.showToast(quotes.monitorStatusLabel);
      }
    );

    onMounted(async () => {
      await workspace.loadWorkspace();
      await settings.loadSettings();
      await grid.loadGridStrategies();
      await useStrategyStore().loadStrategies();
      workspace.draftWatchSuppressed = false;
      plans.hydrateDraft();
      await workspace.refreshAll();
      await grid.restoreGridSuggestion();
      workspace.renderIcons();
      workspace.armRefreshTimer();
      document.addEventListener('keydown', (event) => {
        if (
          event.key === '/' &&
          document.activeElement?.tagName !== 'INPUT' &&
          document.activeElement?.tagName !== 'TEXTAREA'
        ) {
          event.preventDefault();
          document.querySelector('.global-search input')?.focus();
        }
        const shortcut = { 1: 'overview', 2: 'screener', 3: 'grid', 4: 'plans', 5: 'monitor' }[event.key];
        if (shortcut && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA')
          quotes.switchView(shortcut);
      });
    });

    onBeforeUnmount(() => {
      clearInterval(workspace.refreshTimer);
      clearTimeout(workspace.workspaceSyncTimer);
    });

    return {};
  },
};
