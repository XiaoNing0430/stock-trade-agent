import { nextTick, onBeforeUnmount, watch, type Ref } from 'vue';

/**
 * 浮层无障碍行为：Esc 关闭（仅栈顶）、Tab 焦点陷阱、滚动锁（计数幂等）、焦点归还。
 * 模块级栈与锁计数是刻意的：多个浮层各自接一行即可共享同一套规则。
 */
const stack: string[] = [];
let lockCount = 0;

export function isAnyOverlayOpen(): boolean {
  return stack.length > 0;
}

export function isOverlayOpen(id: string): boolean {
  return stack.includes(id);
}

export function topOverlayId(): string | null {
  return stack.length ? stack[stack.length - 1] : null;
}

/** 测试/异常收尾用：清空栈、锁与 body 类（不负责恢复已改动的 DOM 属性）。 */
export function resetOverlayStack(): void {
  stack.length = 0;
  lockCount = 0;
  document.body.classList.remove('overlay-open');
}

const FOCUSABLE_SELECTOR = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

function isVisible(el: HTMLElement): boolean {
  if (el.hasAttribute('inert')) return false;
  const style = window.getComputedStyle(el);
  return style.display !== 'none' && style.visibility !== 'hidden';
}

export function focusableWithin(root: HTMLElement): HTMLElement[] {
  return Array.from(root.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR)).filter(
    (el) => el.tabIndex !== -1 && isVisible(el)
  );
}

export function nextFocusTarget(elements: HTMLElement[], active: Element | null, shift: boolean): HTMLElement | null {
  if (!elements.length) return null;
  const index = elements.findIndex((el) => el === active);
  if (index === -1) return shift ? elements[elements.length - 1] : elements[0];
  const next = shift ? index - 1 : index + 1;
  return elements[(next + elements.length) % elements.length];
}

export interface OverlayA11yOptions {
  id: string;
  isOpen: () => boolean;
  panelRef: Ref<HTMLElement | null>;
  onClose: () => void;
  /** 默认 true；帮助浮层同样用 Esc 关闭。 */
  closeOnEsc?: boolean;
}

export function useOverlayA11y(options: OverlayA11yOptions): void {
  const { id, panelRef, onClose, closeOnEsc = true } = options;
  let restoreTarget: HTMLElement | null = null;
  let panelTabIndexAdded = false;

  function onKeydown(event: KeyboardEvent): void {
    if (topOverlayId() !== id) return; // 只有最上层浮层响应键盘
    if (event.key === 'Escape') {
      if (!closeOnEsc) return;
      event.preventDefault();
      onClose();
      return;
    }
    if (event.key !== 'Tab') return;
    const panel = panelRef.value;
    if (!panel) return;
    const focusables = focusableWithin(panel);
    event.preventDefault();
    if (!focusables.length) return;
    const active = document.activeElement as HTMLElement | null;
    if (!active || !panel.contains(active)) {
      (event.shiftKey ? focusables[focusables.length - 1] : focusables[0]).focus();
      return;
    }
    nextFocusTarget(focusables, active, event.shiftKey)?.focus();
  }

  function open(): void {
    if (!stack.includes(id)) stack.push(id);
    lockCount += 1;
    if (lockCount === 1) document.body.classList.add('overlay-open');
    restoreTarget = (document.activeElement as HTMLElement | null) ?? null;
    void nextTick(() => {
      const panel = panelRef.value;
      if (!panel) return;
      const preferred = panel.querySelector<HTMLElement>('[data-autofocus]');
      if (preferred) {
        preferred.focus();
        return;
      }
      const first = focusableWithin(panel)[0];
      if (first) {
        first.focus();
        return;
      }
      if (!panel.hasAttribute('tabindex')) {
        panel.setAttribute('tabindex', '-1');
        panelTabIndexAdded = true;
      }
      panel.focus();
    });
  }

  function close(): void {
    const index = stack.indexOf(id);
    if (index !== -1) stack.splice(index, 1);
    lockCount = Math.max(0, lockCount - 1);
    if (lockCount === 0) document.body.classList.remove('overlay-open');
    if (panelTabIndexAdded && panelRef.value) {
      panelRef.value.removeAttribute('tabindex');
      panelTabIndexAdded = false;
    }
    const target = restoreTarget;
    restoreTarget = null;
    if (!target) return;
    void nextTick(() => {
      if (target.isConnected && !(target as HTMLButtonElement).disabled) target.focus();
    });
  }

  watch(
    () => options.isOpen(),
    (openNow) => (openNow ? open() : close()),
    { immediate: true, flush: 'sync' }
  );
  window.addEventListener('keydown', onKeydown);
  onBeforeUnmount(() => {
    window.removeEventListener('keydown', onKeydown);
    if (options.isOpen()) close();
  });
}
