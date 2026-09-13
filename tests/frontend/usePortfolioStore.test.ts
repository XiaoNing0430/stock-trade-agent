import { describe, expect, it, vi, beforeEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

// api mock 手法照 useReviewStore.test.ts：替换 requestJson 具名导出，store 内走 @/api/client。
const requestJson = vi.fn();
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<any>()),
  requestJson: (...a: unknown[]) => requestJson(...a),
}));

import { usePortfolioStore } from '@/stores/usePortfolioStore';

// I13 fixture = spec §6 L84 顶层键逐字：nav 数组 gross（r3.2，非 values）+ feeCum/feeSum（端点并装）、
// degraded: string[]、watchIndex 顶层可 null、kpis.planCount 嵌套、concentration 可 null。
const payload = {
  kpis: {
    navNow: 105000, navNowNet: 104200, mdd: 0.12, mddNet: 0.13, exposurePct: 0.6, cashPct: 0.4,
    planCount: { active: 2, triggered: 1, closedInWindow: 3, notEntered: 1 },
    orphanSellCount: 1, pairCount: 1, scalingCount: 0,
  },
  nav: {
    dates: ['2026-09-10', '2026-09-11'],
    gross: [100000, 105000], net: [100000, 104200],
    feeCum: [0, 800], feeSum: 800,
  },
  exposure: { plannedPct: 60, capPct: 80, overCap: false, cashPct: 40, amountByEquity: 60000 },
  concentration: {
    top3: 70, hhi: 0.25,
    industries: [{ key: '电池', label: '电池', pct: 70 }, { key: '未知', label: '未知', pct: 30 }],
    unknownPct: 30, watchPool: null, hypothetical: null,
  },
  pairs: [], pairsTotal: 0,
  orphans: [], orphansTotal: 0,
  signals: { items: [], note: '口径：信号日=窗内 stop/target 任一首次触及……' }, signalsTotal: 0,
  events: [], eventsTotal: 0,
  watchIndex: null,
  degraded: [],
  meta: {
    layer: 'core', windowStart: '2026-06-14',
    industryCoverage: { known: 1, total: 2, staleCount: 0 },
    equity: 100000, feeRate: 0.0015,
  },
};

const urlOf = (i: number) => String(requestJson.mock.calls[i]?.[0]);

describe('usePortfolioStore', () => {
  beforeEach(() => { localStorage.clear(); setActivePinia(createPinia()); requestJson.mockReset(); });

  // ── 拼参（spec §6：days 默认 90；start 优先且完全忽略 days；withWatch 字面量；feeRate 非空才带）──
  it('默认拼参：/api/portfolio/risk?days=90&layer=core&withWatch=false，不带 start/feeRate', async () => {
    requestJson.mockResolvedValue(payload);
    const s = usePortfolioStore();
    await s.fetchRisk();
    expect(urlOf(0)).toBe('/api/portfolio/risk?days=90&layer=core&withWatch=false');
  });

  it('days 档按当前值拼（0=ALL 边界档）', async () => {
    requestJson.mockResolvedValue(payload);
    const s = usePortfolioStore();
    s.setParam('days', 0);
    await s.fetchRisk();
    expect(urlOf(0)).toContain('days=0&');
  });

  it('start 有值 → 带 start 且不带 days（终审 R4：start 优先、days 完全忽略）', async () => {
    requestJson.mockResolvedValue(payload);
    const s = usePortfolioStore();
    s.setParam('start', '2026-06-01');
    await s.fetchRisk();
    expect(urlOf(0)).toContain('start=2026-06-01');
    expect(urlOf(0)).not.toContain('days=');
    s.setParam('start', '');                       // 清空起始日 → 回到 days 档
    await s.fetchRisk();
    expect(urlOf(1)).toContain('days=90');
    expect(urlOf(1)).not.toContain('start=');
  });

  it('withWatch 真 → 字面 withWatch=true（非 True/1）', async () => {
    requestJson.mockResolvedValue(payload);
    const s = usePortfolioStore();
    s.setParam('withWatch', true);
    await s.fetchRisk();
    expect(urlOf(0)).toContain('withWatch=true');
    expect(urlOf(0)).not.toContain('withWatch=false');
  });

  it('feeRate 非空才带', async () => {
    requestJson.mockResolvedValue(payload);
    const s = usePortfolioStore();
    await s.fetchRisk();
    expect(urlOf(0)).not.toContain('feeRate=');
    s.setParam('feeRate', '0.002');
    await s.fetchRisk();
    expect(urlOf(1)).toContain('feeRate=0.002');
    s.setParam('feeRate', '');                     // 清空 → 回落服务端默认，参数省略
    await s.fetchRisk();
    expect(urlOf(2)).not.toContain('feeRate=');
  });

  // ── 成功/失败态与 fetchedOnce 可重试语义（红线：失败可见化，复用 review 错误模式）──
  it('fetch 失败 → error 固定文案 + payload=null + fetchedOnce 复位；重试成功清 error 落 payload', async () => {
    requestJson.mockRejectedValueOnce(new Error('502 Bad Gateway'));
    const s = usePortfolioStore();
    await s.fetchRisk();
    expect(s.error).toBe('组合风险计算失败，请稍后重试');
    expect(s.payload).toBeNull();                  // 失败即无可信数据，不保留旧面板
    expect(s.fetchedOnce).toBe(false);             // 复位 → 再入视图可重新拉取
    expect(s.loading).toBe(false);
    requestJson.mockResolvedValueOnce(payload);
    await s.fetchRisk();
    expect(s.error).toBeNull();                    // 成功清 error
    expect(s.fetchedOnce).toBe(true);
    expect(s.payload?.kpis.planCount.active).toBe(2);
  });

  it('payload 逐字透传：nav.gross/feeCum/feeSum、degraded string[]、watchIndex 与 concentration 可 null、null 起点容忍不造数', async () => {
    requestJson.mockResolvedValue(payload);
    const s = usePortfolioStore();
    await s.fetchRisk();
    expect(s.payload?.nav.gross).toEqual([100000, 105000]);
    expect(s.payload?.nav).not.toHaveProperty('values');   // r3.2：gross 命名，values 已废
    expect(s.payload?.nav.feeCum).toEqual([0, 800]);
    expect(s.payload?.nav.feeSum).toBe(800);
    expect(s.payload?.watchIndex).toBeNull();
    expect(s.payload?.degraded).toEqual([]);
    // 第二轮：withWatch 出 watchIndex 对象；gross 起点 null（轴首无值）原样保留；concentration 可 null
    requestJson.mockResolvedValueOnce({
      ...payload,
      nav: { ...payload.nav, gross: [null, 105000] },
      watchIndex: { dates: ['2026-09-10', '2026-09-11'], values: [null, 1.02], equityStart: 1, note: '自选观察组合（等权指数，非持仓）' },
      concentration: null,
      degraded: ['600519'],
    });
    await s.fetchRisk();
    expect(s.payload?.nav.gross[0]).toBeNull();            // 不造数：null 起点原样透传
    expect(s.payload?.watchIndex?.values[1]).toBe(1.02);
    expect(s.payload?.concentration).toBeNull();
    expect(s.payload?.degraded).toEqual(['600519']);
  });

  // ── 偏好持久化：仅 {days,layer,withWatch} 写 portfolio_prefs_v1；feeRate/start 一次性分析参数不落盘 ──
  it('setParam 即持久化，且 portfolio_prefs_v1 仅含 {days,layer,withWatch} 三键', () => {
    const s = usePortfolioStore();
    s.setParam('days', 30);
    s.setParam('layer', 'closed');
    s.setParam('withWatch', true);
    const raw = localStorage.getItem('portfolio_prefs_v1');
    expect(raw).not.toBeNull();
    const o = JSON.parse(raw as string);
    expect(Object.keys(o).sort()).toEqual(['days', 'layer', 'withWatch']);
    expect(o).toEqual({ days: 30, layer: 'closed', withWatch: true });
  });

  it('feeRate/start 不落 localStorage（一次性分析参数，观察 3 / spec §7）', () => {
    const s = usePortfolioStore();
    s.setParam('feeRate', '0.002');
    s.setParam('start', '2026-06-01');
    expect(localStorage.getItem('portfolio_prefs_v1')).toBeNull();
  });

  it('重启恢复：新 store 实例从 localStorage 恢复偏好；feeRate/start 不恢复', () => {
    const s = usePortfolioStore();
    s.setParam('days', 180);
    s.setParam('withWatch', true);
    s.setParam('feeRate', '0.01');
    s.setParam('start', '2026-01-05');
    setActivePinia(createPinia());                 // 模拟应用重启后重新 init
    const s2 = usePortfolioStore();
    expect(s2.days).toBe(180);
    expect(s2.withWatch).toBe(true);
    expect(s2.layer).toBe('core');
    expect(s2.feeRate).toBe('');
    expect(s2.start).toBe('');
  });

  it('clear storage 后重新 init → 恢复默认语义（days=90 / core / withWatch=false）', () => {
    const s = usePortfolioStore();
    s.setParam('days', 30);
    localStorage.clear();
    setActivePinia(createPinia());
    const s2 = usePortfolioStore();
    expect(s2.days).toBe(90);
    expect(s2.layer).toBe('core');
    expect(s2.withWatch).toBe(false);
  });

  it('脏偏好容错：坏 JSON / 越界值逐字段忽略回默认，不抛错', () => {
    localStorage.setItem('portfolio_prefs_v1', '{oops');
    setActivePinia(createPinia());
    let s = usePortfolioStore();
    expect(s.days).toBe(90);
    localStorage.setItem('portfolio_prefs_v1', JSON.stringify({ days: 45, layer: 'nope', withWatch: 'yes' }));
    setActivePinia(createPinia());
    s = usePortfolioStore();
    expect(s.days).toBe(90);
    expect(s.layer).toBe('core');
    expect(s.withWatch).toBe(false);
  });

  // ── reset：清分析态，参数与偏好不动 ──
  it('reset 清 payload/error/fetchedOnce，保留当前参数', async () => {
    requestJson.mockResolvedValue(payload);
    const s = usePortfolioStore();
    await s.fetchRisk();
    s.setParam('days', 180);
    s.reset();
    expect(s.payload).toBeNull();
    expect(s.error).toBeNull();
    expect(s.fetchedOnce).toBe(false);
    expect(s.days).toBe(180);
  });
});
