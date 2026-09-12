import { describe, expect, it, vi, beforeEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { flushPromises, mount } from '@vue/test-utils';

const requestJson = vi.fn();
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<any>()),
  requestJson: (...a: unknown[]) => requestJson(...a),
}));
// 明细排序断言需挂载 ViewPlans（sortedDetail 是组件 computed，非 store 导出）；lucide mock 照抄 ViewPlans.test.ts 模式。
vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));

import { useReviewStore } from '@/stores/useReviewStore';
import ViewPlans from '@/views/ViewPlans.vue';

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
  beforeEach(() => { localStorage.clear(); setActivePinia(createPinia()); requestJson.mockReset(); });

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

  it('toggleSort 排序语义：同键翻转 desc→asc / 新键重置 desc / netR null 按 ?? -Infinity 沉底（T8 评审 Minor 2）', async () => {
    // items 后端原序故意乱放：p2(-1.0) / p3(null) / p1(2.0)，使 desc 断言可证明排序真的发生
    const sortable = { ...payload, items: [
      { planId: 'p2', code: '600002', source: 'manual', direction: 'buy', entry: 10, stop: 9.5,
        target: 11, validity: '本月内', status: '已过期', outcome: 'loss', rValue: -1, netR: -1.0,
        costR: 0.03, entryDate: '2026-09-14', exitDate: '2026-09-15', ambiguous: false, gapFill: false, limitDeferred: false },
      { planId: 'p3', code: '600003', source: 'screener', direction: 'buy', entry: 10, stop: 9.5,
        target: 11, validity: '本月内', status: '已过期', outcome: 'open', rValue: null, netR: null,
        costR: null, entryDate: '2026-09-14', exitDate: null, ambiguous: false, gapFill: false, limitDeferred: false },
      { planId: 'p1', code: '600001', source: 'manual', direction: 'buy', entry: 10, stop: 9.5,
        target: 11, validity: '本月内', status: '已过期', outcome: 'win', rValue: 2, netR: 2.0,
        costR: 0.03, entryDate: '2026-09-14', exitDate: '2026-09-15', ambiguous: false, gapFill: false, limitDeferred: false },
    ] };
    requestJson.mockResolvedValue(sortable);
    const wrapper = mount(ViewPlans);
    await wrapper.find('[data-testid="review-toggle"]').trigger('click');
    await flushPromises();
    const s = useReviewStore();
    const codes = () => wrapper.findAll('[data-testid="review-items-detail"] tbody tr').map((r) => r.find('td').text());
    const sortBtns = () => wrapper.findAll('[data-testid="review-items-detail"] th button');
    expect(codes()).toEqual(['600002', '600003', '600001']);   // 未选排序键 → 保持后端原序
    await sortBtns()[1].trigger('click');                      // netR → desc：2.0 / -1.0 / null 沉底
    expect(s.sortKey).toBe('netR'); expect(s.sortDir).toBe('desc');
    expect(codes()).toEqual(['600001', '600002', '600003']);
    await sortBtns()[1].trigger('click');                      // 同键翻转 → asc：null(-Inf) 置顶
    expect(s.sortDir).toBe('asc');
    expect(codes()).toEqual(['600003', '600002', '600001']);
    await sortBtns()[0].trigger('click');                      // 新键 outcome → 重置 desc：win/open/loss
    expect(s.sortKey).toBe('outcome'); expect(s.sortDir).toBe('desc');
    expect(codes()).toEqual(['600001', '600003', '600002']);
  });
});
