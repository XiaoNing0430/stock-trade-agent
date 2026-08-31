import type { Alert } from '@/types/models';

export function dedupeSystemAlert(
  alerts: Alert[],
  kind: string,
  title: string,
  message: string,
  now: number
): { alerts: Alert[]; count: number } {
  const list = [...alerts];
  if (kind === 'system') {
    const existing = list.find((item) => item.kind === 'system' && item.title === title);
    if (existing && now - (existing.createdAtMs || 0) < 10 * 60 * 1000) {
      const count = (existing.count || 1) + 1;
      list.splice(list.indexOf(existing), 1, {
        ...existing,
        count,
        message: count > 1 ? `${message}（10 分钟内第 ${count} 次）` : message,
        createdAtMs: now,
      });
      return { alerts: list, count };
    }
  }
  list.unshift({
    id: `alert-${now}-${Math.random().toString(16).slice(2)}`,
    kind: kind as Alert['kind'],
    title,
    message,
    read: false,
    createdAtMs: now,
  });
  return { alerts: list.slice(0, 24), count: 1 };
}
