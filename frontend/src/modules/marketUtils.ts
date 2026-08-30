import type { Quote } from '@/types/models';

export function mergeMarketQuotes(existing: Quote[], incoming: Quote[]): Quote[] {
  const map = new Map(existing.map((q) => [q.code, q]));
  for (const q of incoming) map.set(q.code, q);
  return [...map.values()];
}
