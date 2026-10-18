// 迁移期策略：此文件自 frontend/app.js 机械迁移（函数体零改动），
// Phase 3（eng-refactor）将把 monolith setup()
// 拆解为 8 个 Pinia store 时正式补全类型并移除本注释。
import { watch, onMounted, onBeforeUnmount, nextTick } from 'vue';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { useScreenerStore } from '@/stores/useScreenerStore';
import { usePlansStore } from '@/stores/usePlansStore';
import { useSettingsStore } from '@/stores/useSettingsStore';
import { useGridStore } from '@/stores/useGridStore';
import { useStrategyStore } from '@/stores/useStrategyStore';
import { helpOpen, shortcutFor, toggleHelp } from '@/modules/shortcuts';
import { isAnyOverlayOpen } from '@/modules/overlayA11y';

/**
 * 全局快捷键派发器依赖。除 switchView 外均有默认值：默认接真实的浮层栈 / 帮助态 / 模块 toggleHelp，
 * 使生产接线保持零样板，同时让测试能注入桩或只覆盖单点。
 */
export interface ShortcutHandlerDeps {
  switchView: (view: string) => void;
  isOverlayOpen?: () => boolean;
  isHelpOpen?: () => boolean;
  toggleHelp?: () => void;
}

/**
 * 快捷键派发器工厂：把 shortcutFor 的判定落到副作用上。
 * 与 shortcutFor 分离是为了让「按键 → 动作」纯判定与「动作 → 副作用」各自可测；
 * 行为与提取前 onShortcutKeydown 逐字一致（含 search 无输入框时不吞键）。
 */
export function createShortcutHandler(deps: ShortcutHandlerDeps): (event: KeyboardEvent) => void {
  const isOverlayOpen = deps.isOverlayOpen ?? isAnyOverlayOpen;
  const isHelpOpen = deps.isHelpOpen ?? (() => helpOpen.value);
  const toggle = deps.toggleHelp ?? toggleHelp;
  return (event: KeyboardEvent): void => {
    const action = shortcutFor(event, { overlayOpen: isOverlayOpen(), helpOpen: isHelpOpen() });
    if (!action) return;
    if (action.type === 'view') {
      deps.switchView(action.view);
      return;
    }
    if (action.type === 'search') {
      const input = document.querySelector('.global-search input') as HTMLInputElement | null;
      if (!input) return; // 无搜索框可聚焦时不吞掉按键（原实现无条件 preventDefault）
      event.preventDefault();
      input.focus();
      return;
    }
    event.preventDefault();
    toggle();
  };
}

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

    let keydownDisposer: (() => void) | null = null;
    let disposed = false;

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
      const onShortcutKeydown = createShortcutHandler({ switchView: (view) => quotes.switchView(view) });
      document.addEventListener('keydown', onShortcutKeydown);
      keydownDisposer = () => document.removeEventListener('keydown', onShortcutKeydown);
      // 监听器与刷新计时器都在 onMounted 异步链的末尾才建立：若组件在链跑完前就卸载，
      // onBeforeUnmount 早已执行过，keydownDisposer 当时为 null、workspace.refreshTimer 当时也还是旧值，
      // 于是链尾刚新建的这两项副作用都无人再清。此处各补一次即可闭合本文件在链尾建立的两项；
      // 其余 store 自建的计时器不在此窗口（也不由本文件负责），初始化顺序不变。
      if (disposed) {
        keydownDisposer();
        keydownDisposer = null;
        clearInterval(workspace.refreshTimer);
      }
    });

    onBeforeUnmount(() => {
      disposed = true;
      keydownDisposer?.();
      keydownDisposer = null;
      clearInterval(workspace.refreshTimer);
      clearTimeout(workspace.workspaceSyncTimer);
    });

    return {};
  },
};
