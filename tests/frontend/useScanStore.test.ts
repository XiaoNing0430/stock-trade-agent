import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const requestJsonMock = vi.fn();
vi.mock('@/api/client', () => ({
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}));

import { useScanStore } from '@/stores/useScanStore';

const HITS_PAYLOAD = {
  hits: [
    {
      strategyId: 'trend_breakout',
      strategyName: '趋势突破',
      scannedAt: '2026-09-05T07:40:00+00:00',
      status: 'ok',
      codes: [
        { code: '600519', name: '贵州茅台', score: 82.5, firstSeen: '2026-09-05' },
        { code: '510300', name: '沪深300ETF', score: 71.2, firstSeen: '2026-09-07' },
      ],
    },
  ],
};

describe('useScanStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    requestJsonMock.mockReset();
    localStorage.clear();
  });

  it('fetchHits 解析命中并按 firstSeen 合成提醒项', async () => {
    requestJsonMock.mockResolvedValueOnce(HITS_PAYLOAD);
    const scan = useScanStore();
    await scan.fetchHits();
    expect(scan.hits.length).toBe(1);
    const alerts = scan.scanAlerts;
    expect(alerts.length).toBe(2);
    expect(alerts[0]).toMatchObject({
      id: 'scan:trend_breakout:600519:2026-09-05',
      kind: 'alert',
      code: '600519',
      strategyId: 'trend_breakout',
    });
    // createdAtMs = firstSeen 当日 15:40 Asia/Shanghai
    expect(alerts[0].createdAtMs).toBe(new Date('2026-09-05T15:40:00+08:00').getTime());
  });

  it('未读计数随 markSeen 归零并持久化 localStorage', async () => {
    requestJsonMock.mockResolvedValueOnce(HITS_PAYLOAD);
    const scan = useScanStore();
    await scan.fetchHits();
    expect(scan.unreadScanCount).toBe(2);
    scan.markSeen('trend_breakout');
    expect(scan.unreadScanCount).toBe(0);
    expect(Number(localStorage.getItem('atlas.scan.seen.trend_breakout'))).toBeGreaterThan(0);
    // 重新实例化（模拟刷新页面）后 seen 仍在 → 仍 0
    setActivePinia(createPinia());
    const scan2 = useScanStore();
    requestJsonMock.mockResolvedValueOnce(HITS_PAYLOAD);
    await scan2.fetchHits();
    expect(scan2.unreadScanCount).toBe(0);
  });

  it('saveConfig 成功返回 true、422 返回 false 并 toast', async () => {
    const scan = useScanStore();
    requestJsonMock.mockResolvedValueOnce({ config: { strategyId: 'trend_breakout', enabled: true, mode: 'quick' } });
    expect(await scan.saveConfig('trend_breakout', true, 'quick')).toBe(true);
    expect(requestJsonMock).toHaveBeenCalledWith(
      '/api/screener/scan/configs',
      expect.objectContaining({ method: 'PUT' })
    );
    requestJsonMock.mockRejectedValueOnce({ status: 422 });
    expect(await scan.saveConfig('trend_breakout', true, 'macd')).toBe(false);
  });

  it('runScanNow 返回 alerted 并刷新 hits', async () => {
    const scan = useScanStore();
    requestJsonMock.mockResolvedValueOnce({ config: { strategyId: 'trend_breakout' }, alerted: 3 });
    requestJsonMock.mockResolvedValueOnce(HITS_PAYLOAD);
    const result = await scan.runScanNow('trend_breakout');
    expect(result?.alerted).toBe(3);
    expect(requestJsonMock).toHaveBeenCalledTimes(2);
    expect(scan.hits.length).toBe(1);
  });
});
