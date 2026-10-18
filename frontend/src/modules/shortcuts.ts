import { ref } from 'vue';

/** 数字键 → 视图。顺序与 NAV_ITEMS 一致；'7' 是 ③b 新增（个人中心）。 */
export const VIEW_SHORTCUTS: Record<string, string> = {
  '1': 'overview',
  '2': 'screener',
  '3': 'grid',
  '4': 'plans',
  '5': 'monitor',
  '6': 'portfolio',
  '7': 'settings',
};

export function shortcutForView(viewId: string): string | null {
  const hit = Object.entries(VIEW_SHORTCUTS).find(([, view]) => view === viewId);
  return hit ? hit[0] : null;
}

/** 帮助浮层开关：模块级状态（先例：modules/theme.ts）。 */
export const helpOpen = ref(false);

export function toggleHelp(): void {
  helpOpen.value = !helpOpen.value;
}

export type ShortcutAction = { type: 'view'; view: string } | { type: 'search' } | { type: 'toggle-help' };

export interface ShortcutContext {
  overlayOpen: boolean;
  helpOpen: boolean;
}

export function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  const tag = target.tagName;
  // jsdom 未实现 isContentEditable（恒为 undefined），故回落到 contentEditable 属性；
  // 真实浏览器 isContentEditable 已实现（布尔），?? 不会走到右侧。
  const editable = target.isContentEditable ?? target.contentEditable === 'true';
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || editable === true;
}

export function shortcutFor(event: KeyboardEvent, ctx: ShortcutContext): ShortcutAction | null {
  if (event.ctrlKey || event.metaKey || event.altKey) return null;
  if (event.isComposing) return null;
  if (isTypingTarget(event.target)) return null;

  if (event.key === '?' || event.key === '？') {
    if (ctx.overlayOpen && !ctx.helpOpen) return null;
    return { type: 'toggle-help' };
  }
  if (ctx.overlayOpen) return null; // 浮层打开时其余键不穿透（Esc 由浮层栈独占处理）

  if (event.key === '/') return { type: 'search' };
  const view = VIEW_SHORTCUTS[event.key];
  return view ? { type: 'view', view } : null;
}
