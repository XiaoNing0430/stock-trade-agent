/** Toast 队列策略：同文案去重、堆叠上限、可关闭、悬停暂停、按 tone 分时长。 */
export const TOAST_CAP = 3;
const DURATION_MS: Record<string, number> = { error: 6000 };
const DEFAULT_DURATION_MS = 3200;
const LEAVE_MS = 120;

export function durationFor(tone: string): number {
  return DURATION_MS[tone] ?? DEFAULT_DURATION_MS;
}

export function toastKey(tone: string, message: string): string {
  return `${tone}\u0000${message}`;
}

interface Entry {
  key: string;
  el: HTMLElement;
  timer: ReturnType<typeof setTimeout> | null;
  tone: string;
}

const entries: Entry[] = [];

function region(): HTMLElement | null {
  return document.getElementById('toast-region');
}

function remove(entry: Entry): void {
  const index = entries.indexOf(entry);
  if (index !== -1) entries.splice(index, 1);
  if (entry.timer) clearTimeout(entry.timer);
  entry.el.classList.add('toast-leaving');
  setTimeout(() => entry.el.remove(), LEAVE_MS);
}

function arm(entry: Entry): void {
  if (entry.timer) clearTimeout(entry.timer);
  entry.timer = setTimeout(() => remove(entry), durationFor(entry.tone));
}

export function showToast(message: string, tone = 'success', deps: { renderIcons?: () => void } = {}): void {
  const host = region();
  if (!host) return;
  const text = String(message ?? '');
  const key = toastKey(tone, text);

  const existing = entries.find((entry) => entry.key === key);
  if (existing) {
    existing.el.classList.remove('toast-pulse');
    void existing.el.offsetWidth; // 触发重排以便重放高亮动画
    existing.el.classList.add('toast-pulse');
    arm(existing);
    return;
  }

  const el = document.createElement('div');
  el.className = tone === 'error' ? 'toast error' : 'toast';
  const icon = document.createElement('i');
  icon.setAttribute('data-lucide', tone === 'error' ? 'triangle-alert' : 'check-circle-2');
  icon.setAttribute('aria-hidden', 'true');
  const span = document.createElement('span');
  span.textContent = text;
  const close = document.createElement('button');
  close.className = 'toast-close';
  close.type = 'button';
  close.setAttribute('aria-label', '关闭提示');
  const closeIcon = document.createElement('i');
  closeIcon.setAttribute('data-lucide', 'x');
  closeIcon.setAttribute('aria-hidden', 'true');
  close.appendChild(closeIcon);
  el.append(icon, span, close);
  host.appendChild(el);

  const entry: Entry = { key, el, timer: null, tone };
  entries.push(entry);
  el.addEventListener('click', () => remove(entry));
  el.addEventListener('mouseenter', () => {
    if (entry.timer) clearTimeout(entry.timer);
    entry.timer = null;
  });
  el.addEventListener('focusin', () => {
    if (entry.timer) clearTimeout(entry.timer);
    entry.timer = null;
  });
  el.addEventListener('mouseleave', () => arm(entry));
  el.addEventListener('focusout', () => arm(entry));
  deps.renderIcons?.();
  arm(entry);

  // 上限按「存活条数」计（spec §8.2 及其 2026-10-18 说明）：remove() 立刻让条目出队，但被淘汰的节点要先淡出
  // 120ms 才真正摘除。判断依据只能是存活条目（entries）——正因规格要求了淡出，淡出窗内区域会有超出上限的
  // 子节点，且**可能多条同时在淡出**（连续突发时瞬时子节点数并无固定上界）；淡出结束后自然回落至 ≤3。
  // 被淘汰的最旧条目照常走完整淡出。
  while (entries.length > TOAST_CAP) remove(entries[0]);
}

export function resetToasts(): void {
  entries.splice(0).forEach((entry) => {
    if (entry.timer) clearTimeout(entry.timer);
    entry.el.remove();
  });
}
