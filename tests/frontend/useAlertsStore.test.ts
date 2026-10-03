import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

const requestJsonMock = vi.fn();
vi.mock('@/api/client', () => ({
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}));
// App.vue 挂载所需的最小 mock（同 ViewScreener.test.ts 模式）：图标渲染 + 关闭全局协调副作用（app.ts setup 的
// onMounted 会拉起 loadWorkspace/refreshAll/轮询定时器，与提醒面板无关）。
vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));
vi.mock('@/app', () => ({ appOptions: { setup: vi.fn() } }));

import App from '@/App.vue';
import { useAlertsStore } from '@/stores/useAlertsStore';
import { useAssistStore } from '@/stores/useAssistStore';
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
      strategyId: 'trend_breakout',
      strategyName: '趋势突破',
      scannedAt: null,
      status: 'ok',
      codes: [{ code: '300750', name: '宁德时代', score: 77, firstSeen: '2026-09-07' }],
    });
    expect(alerts.filteredAlerts.length).toBe(2); // 1 workspace + 1 scan
    expect(alerts.unreadAlerts).toBe(2); // 两边各 1 条未读
    expect(alerts.unreadTotalCount).toBe(2); // 铃铛徽标同样计入扫描未读
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
      strategyId: 'trend_breakout',
      strategyName: '趋势突破',
      scannedAt: null,
      status: 'ok',
      codes: [{ code: '300750', name: '宁德时代', score: 77, firstSeen: '2026-09-07' }],
    });
    alerts.alertFilter = 'trade';
    // 合成顺序：扫描项在前（brief allAlerts 组合式），系统提醒被盯盘过滤排除
    expect(alerts.filteredAlerts.map((item) => item.id)).toEqual(['scan:trend_breakout:300750:2026-09-07', 'a1']);
    alerts.alertFilter = 'system';
    expect(alerts.filteredAlerts.map((item) => item.id)).toEqual(['s1']);
  });
});

describe('App.vue 扫描项代码片（spec §8）', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    requestJsonMock.mockReset();
    localStorage.clear();
  });

  it('扫描命中项（firstSeen 已过 → createdAtMs < now）渲染代码片；点击 → openFor 携带 code + markSeen 落盘', async () => {
    const scan = useScanStore();
    const firstSeen = new Date(Date.now() - 2 * 86_400_000).toISOString().slice(0, 10); // createdAtMs < now
    scan.hits.push({
      strategyId: 'trend_breakout',
      strategyName: '趋势突破',
      scannedAt: null,
      status: 'ok',
      codes: [{ code: '300750', name: '宁德时代', score: 77, firstSeen }],
    });
    expect(scan.unreadScanCount).toBe(1);

    const assist = useAssistStore();
    const openForSpy = vi.spyOn(assist, 'openFor').mockResolvedValue(undefined);
    // 视图标签在 main.ts 里全局注册（kebab-case），测试内等价注册为最小 stub：本测试只针对通知面板代码片
    const stubView = { template: '<div />' };
    const wrapper = mount(App, {
      global: {
        components: {
          'view-overview': stubView,
          'view-screener': stubView,
          'view-stock-detail': stubView,
          'view-grid': stubView,
          'view-plans': stubView,
          'view-monitor': stubView,
          'view-portfolio': stubView,
          'view-settings': stubView,
        },
      },
    });
    await wrapper.find('button[aria-label="通知中心"]').trigger('click'); // 打开通知面板渲染 recentNotifs
    const chip = wrapper.find('button[data-testid="alert-code-chip"]');
    expect(chip.exists()).toBe(true);

    await chip.trigger('click');
    expect(openForSpy).toHaveBeenCalledTimes(1);
    expect(openForSpy).toHaveBeenCalledWith(expect.objectContaining({ code: '300750', source: 'scan:trend_breakout' }));
    // markSeen 效果落盘：atlas.scan.seen.{strategyId} 写入毫秒时间戳 → 扫描项视为已读
    expect(Number(localStorage.getItem('atlas.scan.seen.trend_breakout'))).toBeGreaterThan(0);
    expect(scan.unreadScanCount).toBe(0);
    wrapper.unmount();
  });
});
