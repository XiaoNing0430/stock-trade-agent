import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const requestJsonMock = vi.fn();
vi.mock('@/api/client', () => ({
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}));

import { useAlertsStore } from '@/stores/useAlertsStore';
import { useScanStore } from '@/stores/useScanStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';

describe('alerts + scan 合成', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    requestJsonMock.mockReset();
    localStorage.clear();
  });

  it('scanAlerts 并入未读计数与全部列表', () => {
    const workspace = useWorkspaceStore();
    const scan = useScanStore();
    const alerts = useAlertsStore();
    // 整组赋值而非 push：DEFAULT_ALERTS 是模块级共享数组（constants.ts:13），push 会跨测试污染。
    workspace.alerts = [
      { id: 'a1', kind: 'alert', title: '价格提醒', message: '600519 到价', read: false, createdAtMs: 1 },
    ];
    scan.hits.push({
      strategyId: 'trend_breakout', strategyName: '趋势突破', scannedAt: null, status: 'ok',
      codes: [{ code: '300750', name: '宁德时代', score: 77, firstSeen: '2026-09-07' }],
    });
    expect(alerts.filteredAlerts.length).toBe(2);      // 1 workspace + 1 scan
    expect(alerts.unreadAlerts).toBe(2);               // 两边各 1 条未读
    expect(alerts.unreadTotalCount).toBe(2);           // 铃铛徽标同样计入扫描未读
    alerts.markScanSeen('trend_breakout');
    expect(alerts.unreadAlerts).toBe(1);
    expect(alerts.unreadTotalCount).toBe(1);
  });

  it('盯盘过滤包含扫描项且排除系统提醒，系统过滤不含扫描项', () => {
    const workspace = useWorkspaceStore();
    const scan = useScanStore();
    const alerts = useAlertsStore();
    workspace.alerts = [
      { id: 'a1', kind: 'alert', title: '价格提醒', message: '600519 到价', read: false, createdAtMs: 1 },
      { id: 's1', kind: 'system', title: '行情降级', message: '部分接口失败', read: false, createdAtMs: 2 },
    ];
    scan.hits.push({
      strategyId: 'trend_breakout', strategyName: '趋势突破', scannedAt: null, status: 'ok',
      codes: [{ code: '300750', name: '宁德时代', score: 77, firstSeen: '2026-09-07' }],
    });
    alerts.alertFilter = 'trade';
    // 合成顺序：扫描项在前（brief allAlerts 组合式），系统提醒被盯盘过滤排除
    expect(alerts.filteredAlerts.map((item) => item.id)).toEqual([
      'scan:trend_breakout:300750:2026-09-07',
      'a1',
    ]);
    alerts.alertFilter = 'system';
    expect(alerts.filteredAlerts.map((item) => item.id)).toEqual(['s1']);
  });
});
