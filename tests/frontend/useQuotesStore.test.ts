import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return { ...actual, requestJson: vi.fn() };
});

import { useQuotesStore } from '@/stores/useQuotesStore';

describe('行情状态标签', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it('三态标签与跨日时间', () => {
    const quotes = useQuotesStore();
    quotes.dataState = 'live';
    expect(quotes.marketStatusLabel).toBe('真实行情');
    quotes.dataState = 'stale';
    expect(quotes.marketStatusLabel).toBe('缓存行情');
    quotes.dataState = 'connecting';
    expect(quotes.marketStatusLabel).toBe('行情连接中');

    // 今天 → 仅时刻
    quotes.market.fetchedAt = Date.now();
    const today = quotes.marketStatusTimeLabel;
    expect(today).toMatch(/^\d{2}:\d{2}$/);

    // 跨日 → 带日期（解析不可用的时间戳退回 '--'）
    quotes.market.fetchedAt = new Date('2026-01-05T09:30:00').getTime();
    expect(quotes.marketStatusTimeLabel).not.toMatch(/^\d{2}:\d{2}$/);
    quotes.market.fetchedAt = 0;
    expect(quotes.marketStatusTimeLabel).toBe('--');
  });
});
