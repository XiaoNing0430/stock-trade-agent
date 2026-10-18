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

  // 上限按 DOM 子节点数计（spec §8.2）：remove() 会立刻让条目出队，但节点要淡出 120ms
  // 才真正摘除；若按 entries 长度淘汰，淡出窗口内的突发入队会让子节点数冲到 4–5。
  // 故按子节点数逐个摘掉最旧的：有对应条目走既有 remove() 语义（出队/清计时器/挂 .toast-leaving），
  // 已在淡出的孤儿（条目早已出队）直接摘除、不再二次淡出。两种情况都立即摘除节点以守住上限。
  while (host.children.length > TOAST_CAP) {
    const oldest = host.firstElementChild as HTMLElement | null;
    if (!oldest) break;
    const entry = entries.find((candidate) => candidate.el === oldest);
    if (entry) remove(entry);
    oldest.remove();
  }
}

export function resetToasts(): void {
  entries.splice(0).forEach((entry) => {
    if (entry.timer) clearTimeout(entry.timer);
    entry.el.remove();
  });
}
