import { describe, expect, it, vi, beforeEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const requestJson = vi.fn();
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<any>()),
  requestJson: (...a: unknown[]) => requestJson(...a),
}));

import { useReviewStore } from '@/stores/useReviewStore';

const payload = {
  kpis: { total: 2, decided: 1, flatCount: 0, winRate: 1, avgWinR: 1.97, avgLossR: null,
          payoffRatio: null, expectancyR: 1.97, notEnteredRate: 0, openCount: 1, invalidCount: 0 },
  groups: { source: [{ key: 'manual', label: '手动新建', decided: 1, flatCount: 0, wins: 1,
                       winRate: 1, expectancyR: 1.97, smallSample: true }] },
  items: [{ planId: 'p1', code: '300750', source: 'manual', direction: 'buy', entry: 10,
            stop: 9.5, target: 11, validity: '本月内', status: '执行中', outcome: 'win',
            rValue: 2, netR: 1.97, costR: 0.03, entryDate: '2026-09-14', exitDate: '2026-09-15',
            ambiguous: false, gapFill: false, limitDeferred: false }],
};

describe('useReviewStore', () => {
  beforeEach(() => { setActivePinia(createPinia()); requestJson.mockReset(); });

  it('fetchReview 请求 /api/plans/review 并存 review', async () => {
    requestJson.mockResolvedValue(payload);
    const s = useReviewStore();
    await s.fetchReview(90);
    expect(requestJson.mock.calls[0]?.[0]).toContain('/api/plans/review?days=90');
    expect(s.review?.kpis.total).toBe(2);
  });

  it('null 指标渲染占位 --（payoffRatio null 不造数）', async () => {
    requestJson.mockResolvedValue(payload);
    const s = useReviewStore();
    await s.fetchReview(90);
    expect(s.formatRatio(s.review?.kpis.payoffRatio)).toBe('--');
  });

  it('来源分组含 scan: 行时自动拉取留痕（评审 B5）', async () => {
    const withScan = { ...payload,
      groups: { ...payload.groups,
        source: [{ key: 'scan:trend_breakout', label: '扫描·趋势突破', decided: 1, flatCount: 0,
                   wins: 1, winRate: 1, expectancyR: 1.97, smallSample: true }] } };
    requestJson.mockImplementation((url: string) => {
      if (String(url).includes('/api/plans/review')) return Promise.resolve(withScan);
      if (String(url).includes('/api/screener/scan/history')) {
        return Promise.resolve({ history: [{ strategyId: 'trend_breakout', runAtMs: 1_789_000_000_000,
          status: 'ok', hitCount: 3, newCount: 1, elapsedMs: 1200, traceId: 't1' }] });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    const s = useReviewStore();
    await s.fetchReview(90);
    expect(s.trace?.[0]?.hitCount).toBe(3);        // fetchReview → syncTrace → fetchTrace 自动触发
    expect(requestJson.mock.calls.some((c) => String(c[0]).includes('/api/screener/scan/history?strategyId=trend_breakout'))).toBe(true);
    await s.setGroup('direction');                  // 切走 → trace 清空
    expect(s.trace).toBeNull();
  });
});
