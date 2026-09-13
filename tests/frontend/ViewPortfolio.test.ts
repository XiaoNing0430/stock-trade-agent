import { describe, expect, it, vi, beforeEach } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ViewPortfolio from '@/views/ViewPortfolio.vue';
import { usePortfolioStore } from '@/stores/usePortfolioStore';
import { requestJson } from '@/api/client';

// mount 手法照 ViewPlans.test.ts：lucide/UI_ICONS no-op + @/api/client 的 requestJson 替换为 vi.fn()。
vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return { ...actual, requestJson: vi.fn() };
});

const dates = ['2026-09-08', '2026-09-09', '2026-09-10', '2026-09-11'];

function makePayload(over: Record<string, unknown> = {}) {
  return {
    kpis: {
      navNow: 105000,
      navNowNet: 104200,
      mdd: 0.12,
      mddNet: 0.13,
      exposurePct: 0.6,
      cashPct: 0.4,
      planCount: { active: 2, triggered: 1, closedInWindow: 3, notEntered: 1 },
      orphanSellCount: 1,
      pairCount: 1,
      scalingCount: 0,
    },
    nav: {
      dates,
      gross: [100000, 101000, 103000, 105000],
      net: [100000, 100500, 102300, 104200],
      feeCum: [0, 150, 450, 800],
      feeSum: 800,
    },
    exposure: { plannedPct: 60, capPct: 80, overCap: false, cashPct: 0.4, amountByEquity: 60000 },
    concentration: {
      top3: 92,
      hhi: 0.321,
      industries: [
        { key: '电池', label: '电池', pct: 46 },
        { key: '白酒', label: '白酒', pct: 32 },
        { key: '半导体', label: '半导体', pct: 14 },
        { key: '未知', label: '未知', pct: 8 },
      ],
      unknownPct: 8,
      watchPool: null,
      hypothetical: {
        industries: [
          { key: '白酒', label: '白酒', pct: 26.67 },
          { key: '电池', label: '电池', pct: 26.67 },
        ],
        unknownPct: 0,
        capPct: 80,
        note: '假想参考线：若自选按上限 80% 等权建仓（非真实持仓、不含价格模拟）',
      },
    },
    pairs: [
      {
        buyPlanId: 'b1',
        sellPlanId: 's1',
        exitMode: 'race',
        buy: { code: '600519', entry: 1700, stop: 1600, target: 1900, positionPct: 30, status: '已触发' },
        sell: { code: '600519', entry: 1900, stop: 1600, target: 2000, status: '执行中', exitMode: 'race' },
      },
    ],
    pairsTotal: 1,
    orphans: [{ planId: 's9', code: '000001', signalDate: '2026-09-09' }],
    orphansTotal: 1,
    signals: {
      items: [
        {
          planId: 's9',
          code: '000001',
          signalDate: '2026-09-09',
          basePrice: 12.3,
          chg5: 0.03,
          chg10: null,
          chg20: -0.01,
          maxRebound: 0.06,
          maxDrawdown: -0.04,
          feeEstPct: 0.003,
          paired: false,
        },
      ],
      note: '口径：信号日=窗内 stop/target 任一首次触及；费用列为双边费率折算的估算收益率。',
    },
    signalsTotal: 1,
    events: [
      {
        type: 'scaling',
        date: '2026-09-09',
        code: '300750',
        detail: { requestedNotional: 50000, allocatedNotional: 30000 },
      },
      {
        type: 'conflict',
        date: '2026-09-10',
        code: '600519',
        detail: { buyPlanId: 'b1', executed: 'stop', suppressed: [{ name: 'target' }] },
      },
    ],
    eventsTotal: 2,
    watchIndex: null,
    degraded: [],
    meta: {
      layer: 'core',
      windowStart: '2026-06-14',
      industryCoverage: { known: 3, total: 4, staleCount: 0 },
      equity: 100000,
      feeRate: 0.0015,
    },
    ...over,
  };
}

async function mountWith(payload: ReturnType<typeof makePayload>) {
  vi.mocked(requestJson).mockReset().mockResolvedValue(payload);
  const wrapper = mount(ViewPortfolio);
  await flushPromises();
  return wrapper;
}

describe('ViewPortfolio', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  // ── brief 断言 1：高级三区默认关，点「高级」后存在 ──
  it('高级三区默认关（portfolio-adv-start null），点「高级」后起始日/自选观察/假想线在', async () => {
    const wrapper = await mountWith(makePayload());
    expect(wrapper.find('[data-testid="portfolio-adv-start"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="portfolio-adv-watch"]').exists()).toBe(false);
    expect(wrapper.find('[data-testid="portfolio-adv-hypo"]').exists()).toBe(false);
    await wrapper.find('[data-testid="portfolio-adv-toggle"]').trigger('click');
    expect(wrapper.find('[data-testid="portfolio-adv-start"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="portfolio-adv-watch"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="portfolio-adv-hypo"]').exists()).toBe(true);
  });

  // ── brief 断言 2：degraded 黄条含代码 ──
  it('degraded 非空 → portfolio-degraded 黄条且含各代码', async () => {
    const wrapper = await mountWith(makePayload({ degraded: ['600519', '000001'] }));
    const bar = wrapper.find('[data-testid="portfolio-degraded"]');
    expect(bar.exists()).toBe(true);
    expect(bar.text()).toContain('600519');
    expect(bar.text()).toContain('000001');
    expect(bar.text()).toContain('本地历史兜底');
  });

  // ── brief 断言 3：预热空卡文案逐字 ──
  it('行业零识别（known=0 且有成分）→ portfolio-warming 预热整卡文案，不出未知条', async () => {
    const wrapper = await mountWith(
      makePayload({
        concentration: null,
        meta: {
          layer: 'core',
          windowStart: '2026-06-14',
          industryCoverage: { known: 0, total: 2, staleCount: 2 },
          equity: 100000,
          feeRate: 0.0015,
        },
      })
    );
    const card = wrapper.find('[data-testid="portfolio-warming"]');
    expect(card.exists()).toBe(true);
    expect(card.text()).toBe('行业数据预热中，稍后自动刷新');
    expect(wrapper.findAll('.pf-ind-row').length).toBe(0);
  });

  // ── brief 断言 4：底部红线双句逐字 ──
  it('底部红线双句逐字出现', async () => {
    const RED = '虚拟组合为设计口径模拟回放，非真实成交，不构成投资建议。孤儿平仓单仅作信号统计，不纳入 NAV。';
    const wrapper = await mountWith(makePayload());
    expect(wrapper.find('[data-testid="portfolio-disclaimer"]').text()).toBe(RED);
    expect(wrapper.text()).toContain(RED);
  });

  // ── brief 断言 5：层 chip 点击 → setParam + fetch（store 不自动 fetch，视图 handler 显式驱动） ──
  it('闭环层 chip 点击 → setParam(layer) + fetchRisk（mount 即有一次 fetch）', async () => {
    const store = usePortfolioStore();
    const setParam = vi.spyOn(store, 'setParam');
    const fetchRisk = vi.spyOn(store, 'fetchRisk');
    const wrapper = await mountWith(makePayload());
    expect(fetchRisk).toHaveBeenCalledTimes(1); // fetch 时机①：onMounted
    setParam.mockClear();
    fetchRisk.mockClear();
    await wrapper.find('[data-testid="portfolio-layer-closed"]').trigger('click');
    expect(setParam).toHaveBeenCalledWith('layer', 'closed'); // fetch 时机②：参数变更
    expect(fetchRisk).toHaveBeenCalledTimes(1);
    expect(store.layer).toBe('closed');
  });

  it('回看 chip：5 档含「全部」(0)，点击 → setParam(days) 且拼参 days=0', async () => {
    const wrapper = await mountWith(makePayload());
    const chips = wrapper.findAll('[data-testid="portfolio-day-chip"]');
    expect(chips).toHaveLength(5);
    expect(chips.map((c) => c.text())).toEqual(['近 30 天', '近 90 天', '近 180 天', '近 365 天', '全部']);
    vi.mocked(requestJson).mockClear();
    await chips[4].trigger('click');
    expect(String(vi.mocked(requestJson).mock.calls[0]?.[0])).toContain('days=0');
  });

  // ── brief 断言 6：KPI null → '--' ──
  it('KPI null → 渲染 --（不造数）', async () => {
    const wrapper = await mountWith(
      makePayload({
        kpis: {
          navNow: null,
          navNowNet: null,
          mdd: null,
          mddNet: null,
          exposurePct: null,
          cashPct: null,
          planCount: { active: 0, triggered: 0, closedInWindow: 0, notEntered: 0 },
          orphanSellCount: null,
          pairCount: null,
          scalingCount: null,
        },
        nav: {
          dates,
          gross: [100000, 101000, 103000, 105000],
          net: [null, null, null, null],
          feeCum: [],
          feeSum: null,
        },
      })
    );
    const block = wrapper.find('[data-testid="portfolio-kpis"]');
    expect(block.text()).toContain('--');
    expect(block.text()).not.toContain('¥0');
  });

  // ── brief 断言 7：折叠区 cap → 「共 N 条，已截断」（Total > len 时） ──
  it('折叠区截断披露：Total > len → 「共 N 条，已截断」，展开前不渲染', async () => {
    const wrapper = await mountWith(makePayload({ signalsTotal: 52, eventsTotal: 60 }));
    expect(wrapper.text()).not.toContain('共 52 条，已截断'); // 折叠区默认收起
    await wrapper.find('[data-testid="portfolio-signals-toggle"]').trigger('click');
    await wrapper.find('[data-testid="portfolio-events-toggle"]').trigger('click');
    expect(wrapper.find('[data-testid="portfolio-signals-more"]').text()).toBe('共 52 条，已截断');
    expect(wrapper.find('[data-testid="portfolio-events-more"]').text()).toBe('共 60 条，已截断');
  });

  it('事件折叠区：可解释性注记 + 四类型中文徽标；信号看板含 note 与费用估算列', async () => {
    const wrapper = await mountWith(makePayload());
    await wrapper.find('[data-testid="portfolio-events-toggle"]').trigger('click');
    expect(wrapper.find('[data-testid="portfolio-events-note"]').text()).toContain('事件流保证可解释，不承诺可复现');
    const badges = wrapper.findAll('[data-testid="portfolio-events"] .pf-event-type');
    expect(badges.map((b) => b.text())).toEqual(['加仓缩量', '同日双触冲突']);
    await wrapper.find('[data-testid="portfolio-signals-toggle"]').trigger('click');
    expect(wrapper.find('[data-testid="portfolio-signals-note"]').text()).toContain('信号日=窗内');
    expect(wrapper.find('[data-testid="portfolio-signals"]').text()).toContain('费用估算');
  });

  // ── multiLineSvg 挂线例：gross+net 两线；withWatch（watchIndex 非空）三线 + 注记 ──
  it('NAV 曲线默认挂 gross 实线 + net 灰虚线两线', async () => {
    const wrapper = await mountWith(makePayload());
    const chart = wrapper.find('[data-testid="portfolio-nav-chart"]');
    const html = chart.html();
    expect((html.match(/multi-line-path/g) ?? []).length).toBe(2);
    expect(chart.text()).toContain('毛净值');
    expect(chart.text()).toContain('净净值');
    expect(html).toContain('stroke-dasharray');
    expect(wrapper.find('[data-testid="portfolio-watch-note"]').exists()).toBe(false);
    // F1：现金层披露（§7 现金底线不绘 0 基线 + 费用后净值=虚线）
    const cashNote = wrapper.find('[data-testid="portfolio-cash-note"]');
    expect(cashNote.exists()).toBe(true);
    expect(cashNote.text()).toContain('现金不计入曲线');
    expect(cashNote.text()).toContain('虚线');
  });

  it('watchIndex 非空 → 三线（毛/净/自选）且出自选叠线注记', async () => {
    const wrapper = await mountWith(
      makePayload({
        watchIndex: { dates, values: [1, 1.01, 1.02, 1.03], equityStart: 1, note: '自选观察组合（等权指数，非持仓）' },
      })
    );
    const chart = wrapper.find('[data-testid="portfolio-nav-chart"]');
    expect((chart.html().match(/multi-line-path/g) ?? []).length).toBe(3);
    expect(chart.text()).toContain('自选观察指数');
    expect(wrapper.find('[data-testid="portfolio-watch-note"]').text()).toContain('自选观察组合（等权指数，非持仓）');
  });

  it('watchIndex dates 长度与 nav.dates 不一致 → 不叠自选线（仅毛/净两 path）', async () => {
    const wrapper = await mountWith(
      makePayload({
        watchIndex: {
          dates: dates.slice(0, 3),
          values: [1, 1.01, 1.02, 1.03],
          equityStart: 1,
          note: '自选观察组合（等权指数，非持仓）',
        },
      })
    );
    const chart = wrapper.find('[data-testid="portfolio-nav-chart"]');
    expect((chart.html().match(/multi-line-path/g) ?? []).length).toBe(2);
  });

  it('fetch reject → portfolio-error 红线可见且曲线区走空态不炸', async () => {
    vi.mocked(requestJson).mockReset().mockRejectedValue(new Error('500'));
    const wrapper = mount(ViewPortfolio);
    await flushPromises();
    const err = wrapper.find('[data-testid="portfolio-error"]');
    expect(err.exists()).toBe(true);
    expect(err.text()).toContain('组合风险计算失败');
    expect(wrapper.find('[data-testid="portfolio-empty"]').exists()).toBe(true);
  });

  it('无净值点 → 曲线区空态文案', async () => {
    const wrapper = await mountWith(
      makePayload({
        nav: { dates: [], gross: [], net: [], feeCum: [], feeSum: null },
      })
    );
    expect(wrapper.find('[data-testid="portfolio-empty"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="portfolio-empty"]').text()).toContain('暂无计划持仓');
  });

  // ── 集中度卡附加钉：overCap 红 + 假想线注记（默认不展示，勾「假想线」后出且含逐字注记） ──
  it('overCap → 敞口卡红态；假想线勾选后出「假想参考，非真实持仓」注记', async () => {
    const wrapper = await mountWith(
      makePayload({
        exposure: { plannedPct: 92, capPct: 80, overCap: true, cashPct: 0.08, amountByEquity: 92000 },
      })
    );
    expect(wrapper.find('[data-testid="portfolio-exposure"]').classes()).toContain('pf-over');
    expect(wrapper.find('[data-testid="portfolio-overcap"]').text()).toContain('已超上限');
    expect(wrapper.find('[data-testid="portfolio-hypo"]').exists()).toBe(false); // 假想线区默认关
    await wrapper.find('[data-testid="portfolio-adv-toggle"]').trigger('click');
    await wrapper.find('[data-testid="portfolio-adv-hypo"] input').setValue(true);
    const hypo = wrapper.find('[data-testid="portfolio-hypo"]');
    expect(hypo.exists()).toBe(true);
    expect(hypo.text()).toContain('假想参考，非真实持仓');
  });
});
