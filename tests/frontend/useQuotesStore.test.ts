import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return { ...actual, requestJson: vi.fn() };
});

import { useQuotesStore } from '@/stores/useQuotesStore';
import { useScreenerStore } from '@/stores/useScreenerStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';

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

describe('view 白名单归一（spec §10）', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('localStorage 中的已移除视图 exec 归一到 overview', () => {
    localStorage.setItem('atlas-stock-desk-v2', JSON.stringify({ view: 'exec' }));
    setActivePinia(createPinia());
    const quotes = useQuotesStore();
    expect(quotes.view).toBe('overview');
  });

  it('未知视图与 switchView("exec") 同样归一到 overview', () => {
    setActivePinia(createPinia());
    const quotes = useQuotesStore();
    quotes.switchView('exec');
    expect(quotes.view).toBe('overview');
    quotes.switchView('nowhere');
    expect(quotes.view).toBe('overview');
    quotes.switchView('portfolio');
    expect(quotes.view).toBe('portfolio');
  });

  it('exec 三件套已从 store 移除', () => {
    setActivePinia(createPinia());
    const quotes = useQuotesStore() as unknown as Record<string, unknown>;
    for (const key of ['mobileExecTab', 'execShowsPlans', 'execShowsAlerts']) {
      expect(key in quotes).toBe(false);
    }
  });

  it('switchView 落盘的是归一后的真实视图（Pinia 解包口径）', () => {
    setActivePinia(createPinia());
    const quotes = useQuotesStore();
    quotes.switchView('plans');
    const persisted = JSON.parse(localStorage.getItem('atlas-stock-desk-v2') || '{}');
    expect(persisted.view).toBe('plans');
    quotes.switchView('exec');
    const normalized = JSON.parse(localStorage.getItem('atlas-stock-desk-v2') || '{}');
    expect(normalized.view).toBe('overview');
  });

  it('落盘保留选中标的与选股预设，且新 store 能据存储恢复选中标的', () => {
    setActivePinia(createPinia());
    const quotes = useQuotesStore();
    const screener = useScreenerStore();
    quotes.selectedCode = '000858';
    screener.presetName = '低估修复';
    useWorkspaceStore().persistLocal();

    const persisted = JSON.parse(localStorage.getItem('atlas-stock-desk-v2') || '{}');
    expect(persisted.selectedCode).toBe('000858');
    expect(persisted.presetName).toBe('低估修复');

    // 全新 pinia → 全新 store 实例 → selectedCode 只能来自 localStorage
    setActivePinia(createPinia());
    const restored = useQuotesStore();
    expect(restored.selectedCode).toBe('000858');
  });
});
