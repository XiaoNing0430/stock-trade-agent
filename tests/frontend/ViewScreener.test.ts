import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount, flushPromises } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ViewScreener from '@/views/ViewScreener.vue';
import { useScreenerStore } from '@/stores/useScreenerStore';
import { useAssistStore } from '@/stores/useAssistStore';
import { useStrategyStore } from '@/stores/useStrategyStore';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { requestJson } from '@/api/client';

vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return { ...actual, requestJson: vi.fn() };
});

const makeRow = (overrides: Partial<Record<string, unknown>> = {}) => ({
  code: '600519',
  name: '贵州茅台',
  exchange: '上交所',
  board: '主板',
  market: '沪市主板',
  price: 1700,
  change: 2.5,
  pe: 30,
  pb: 8,
  volumeRatio: 1.8,
  turnoverRate: 0.5,
  ...overrides,
});

describe('ViewScreener', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it('渲染筛选结果行（代码/名称/涨跌幅/行数统计）', () => {
    const screener = useScreenerStore();
    screener.screenRows = [makeRow()];
    screener.screenTotal = 50;
    const wrapper = mount(ViewScreener);
    expect(wrapper.text()).toContain('贵州茅台');
    expect(wrapper.text()).toContain('600519');
    expect(wrapper.text()).toContain('2.50%');
    expect(wrapper.text()).toContain('1 只股票符合条件');
    expect(wrapper.text()).toContain('候选池 50 只');
  });

  it('无筛选结果时显示空状态', () => {
    const wrapper = mount(ViewScreener);
    expect(wrapper.text()).toContain('没有找到符合条件的股票');
  });

  it('筛选条件排除不达标的股票并正确统计行数', () => {
    const screener = useScreenerStore();
    // 贵州茅台符合默认筛选条件；平安银行涨跌幅 0.2% < changeMin(1) 被排除
    screener.screenRows = [makeRow(), makeRow({ code: '000001', name: '平安银行', change: 0.2 })];
    const wrapper = mount(ViewScreener);
    expect(wrapper.text()).toContain('贵州茅台');
    expect(wrapper.text()).not.toContain('平安银行');
    expect(wrapper.text()).toContain('1 只股票符合条件');
  });

  it('结果洞察显示当前预设名称与描述，筛选面板字段完整', () => {
    const wrapper = mount(ViewScreener);
    // result-insight 显示当前预设（不受 storeToRefs 跳过 plain array 影响）
    expect(wrapper.text()).toContain('趋势突破');
    expect(wrapper.text()).toContain('放量、强势、价格向上');
    // 筛选字段
    expect(wrapper.text()).toContain('交易所');
    expect(wrapper.text()).toContain('板块');
    expect(wrapper.text()).toContain('搜索');
    expect(wrapper.text()).toContain('PE');
    expect(wrapper.text()).toContain('PB');
  });

  it('预设按钮列表渲染（storeToRefs 可解包 presets ref）', () => {
    const wrapper = mount(ViewScreener);
    const presetButtons = wrapper.findAll('.preset-item');
    expect(presetButtons.length).toBeGreaterThanOrEqual(3);
    expect(presetButtons[0].text()).toContain('趋势突破');
    expect(wrapper.text()).toContain('低估修复');
  });

  it('策略 tab：默认隐藏，点击后显示策略面板并加载策略列表', async () => {
    const { useWorkspaceStore } = await import('@/stores/useWorkspaceStore');
    const ws = useWorkspaceStore();
    const fetchSpy = vi.fn().mockResolvedValue({
      strategies: [
        { id: 'oversold_bounce', name: '超跌反弹', description: 'RSI 超卖', topN: 10, deepCap: 200, factorCount: 3 },
        { id: 'trend_breakout', name: '趋势突破', description: '多头排列', topN: 10, deepCap: 200, factorCount: 3 },
      ],
    });
    vi.spyOn(ws, 'requestJson').mockImplementation(fetchSpy);

    const wrapper = mount(ViewScreener);
    expect(wrapper.text()).not.toContain('策略选股');
    const tabs = wrapper.findAll('.screener-tab');
    const strategyTab = tabs.find((t) => t.text() === '策略');
    expect(strategyTab).toBeTruthy();
    await strategyTab!.trigger('click');
    expect(wrapper.text()).toContain('策略选股');
    expect(fetchSpy).toHaveBeenCalledWith('/api/screener/strategies');
    expect(wrapper.text()).toContain('超跌反弹');
  });

  it('策略 tab：默认极速模式，切换深度与运行调用 POST /api/screener/strategy', async () => {
    const { useWorkspaceStore } = await import('@/stores/useWorkspaceStore');
    const ws = useWorkspaceStore();
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        strategies: [
          { id: 'oversold_bounce', name: '超跌反弹', description: 'RSI 超卖', topN: 10, deepCap: 200, factorCount: 3 },
        ],
      })
      .mockResolvedValueOnce({
        strategy: 'oversold_bounce',
        name: '超跌反弹',
        mode: 'deep',
        referenceDate: '2026-08-28',
        provider: 'Tencent public quote API',
        rows: [
          {
            code: '600001',
            name: '测试股',
            price: 10.0,
            changePct: 1.5,
            pe: 12.0,
            pb: 1.5,
            roe: 15.0,
            score: 3,
            factors: { rsi: { value: 25.1, met: true, weight: 2 } },
          },
        ],
        total: 1,
        cached: false,
        stale: false,
        elapsedMs: 123,
      });
    vi.spyOn(ws, 'requestJson').mockImplementation(fetchSpy);

    const wrapper = mount(ViewScreener);
    const tabs = wrapper.findAll('.screener-tab');
    await tabs.find((t) => t.text() === '策略')!.trigger('click');
    await wrapper
      .findAll('.screener-tab')
      .find((t) => t.text() === '深度')!
      .trigger('click');
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('运行策略'))!
      .trigger('click');
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(fetchSpy).toHaveBeenLastCalledWith('/api/screener/strategy', {
      method: 'POST',
      body: expect.stringContaining('"mode":"deep"'),
    });
    expect(wrapper.text()).toContain('测试股');
    expect(wrapper.text()).toContain('2026-08-28');
    expect(wrapper.text()).toContain('rsi 25.1');
  });

  it('策略 stale 降级显示警告横幅', async () => {
    const { useWorkspaceStore } = await import('@/stores/useWorkspaceStore');
    const ws = useWorkspaceStore();
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce({
        strategies: [
          { id: 'oversold_bounce', name: '超跌反弹', description: 'x', topN: 10, deepCap: 200, factorCount: 1 },
        ],
      })
      .mockResolvedValueOnce({
        strategy: 'oversold_bounce',
        name: '超跌反弹',
        mode: 'quick',
        referenceDate: '2026-08-28',
        provider: 'p',
        rows: [],
        total: 0,
        cached: true,
        stale: true,
        elapsedMs: 5,
      });
    vi.spyOn(ws, 'requestJson').mockImplementation(fetchSpy);

    const wrapper = mount(ViewScreener);
    const tabs = wrapper.findAll('.screener-tab');
    await tabs.find((t) => t.text() === '策略')!.trigger('click');
    await wrapper
      .findAll('button')
      .find((b) => b.text().includes('运行策略'))!
      .trigger('click');
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(wrapper.text()).toContain('数据可能滞后');
  });

  it('策略命中行：草案按钮 → openFor 携带代码/名称/快照价（无 updatedAt 传 null）', async () => {
    const screener = useScreenerStore();
    screener.screenerMode = 'strategy';
    screener.strategyRows = [
      { code: '600519', name: '贵州茅台', price: 1700, changePct: 2.5, pe: 30, pb: 8, roe: 30, score: 3, factors: {} },
    ];
    const assist = useAssistStore();
    const spy = vi.spyOn(assist, 'openFor').mockResolvedValue(undefined);
    const wrapper = mount(ViewScreener);
    await wrapper.find('button[data-testid="draft-600519"]').trigger('click');
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith(
      expect.objectContaining({ code: '600519', name: '贵州茅台', price: 1700, asOfMs: null })
    );
  });

  it('策略命中行：行价缺失时 openFor 携带 null（绝不造数）', async () => {
    const screener = useScreenerStore();
    screener.screenerMode = 'strategy';
    screener.strategyRows = [
      { code: '000001', name: '平安银行', price: null, changePct: 1.2, pe: 6, pb: 0.6, roe: 11, score: 2, factors: {} },
    ];
    const assist = useAssistStore();
    const spy = vi.spyOn(assist, 'openFor').mockResolvedValue(undefined);
    const wrapper = mount(ViewScreener);
    await wrapper.find('button[data-testid="draft-000001"]').trigger('click');
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ code: '000001', name: '平安银行', price: null }));
  });

  it('策略命中行：回测按钮 → 预填代码并切到策略实验室', async () => {
    const screener = useScreenerStore();
    screener.screenerMode = 'strategy';
    screener.strategyRows = [
      { code: '600519', name: '贵州茅台', price: 1700, changePct: 2.5, pe: 30, pb: 8, roe: 30, score: 3, factors: {} },
    ];
    const strategy = useStrategyStore();
    const quotes = useQuotesStore();
    const wrapper = mount(ViewScreener);
    await wrapper.find('button[data-testid="backtest-600519"]').trigger('click');
    expect(strategy.strategyDraft.code).toBe('600519');
    expect(quotes.view).toBe('grid');
  });

  it('定时扫描开关保存失败时回滚并提示', async () => {
    const { useWorkspaceStore } = await import('@/stores/useWorkspaceStore');
    const ws = useWorkspaceStore();
    vi.spyOn(ws, 'requestJson').mockResolvedValue({
      strategies: [
        { id: 'oversold_bounce', name: '超跌反弹', description: 'RSI 超卖', topN: 10, deepCap: 200, factorCount: 3 },
      ],
    });
    const toastSpy = vi.spyOn(ws, 'showToast');
    vi.mocked(requestJson)
      .mockResolvedValueOnce({
        configs: [
          {
            strategyId: 'oversold_bounce',
            strategyName: '超跌反弹',
            enabled: false,
            mode: 'quick',
            lastRunAt: null,
            lastStatus: null,
            hitCount: 0,
            newCount: 0,
          },
        ],
      })
      .mockRejectedValueOnce(new Error('save failed'));

    const wrapper = mount(ViewScreener);
    const tabs = wrapper.findAll('.screener-tab');
    await tabs.find((t) => t.text() === '策略')!.trigger('click');
    await new Promise((resolve) => setTimeout(resolve, 0));

    await wrapper.find('[data-testid="scan-toggle"]').setValue(true);
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect((wrapper.find('[data-testid="scan-toggle"]').element as HTMLInputElement).checked).toBe(false);
    expect(toastSpy).toHaveBeenCalledWith('扫描配置保存失败，稍后重试', 'error');
  });

  it('立即扫描调用扫描端点并显示命中', async () => {
    const { useWorkspaceStore } = await import('@/stores/useWorkspaceStore');
    const ws = useWorkspaceStore();
    const fetchSpy = vi.fn().mockResolvedValue({
      strategies: [
        { id: 'oversold_bounce', name: '超跌反弹', description: 'RSI 超卖', topN: 10, deepCap: 200, factorCount: 3 },
      ],
    });
    vi.spyOn(ws, 'requestJson').mockImplementation(fetchSpy);
    vi.mocked(requestJson)
      .mockResolvedValueOnce({
        configs: [
          {
            strategyId: 'oversold_bounce',
            strategyName: '超跌反弹',
            enabled: false,
            mode: 'quick',
            lastRunAt: null,
            lastStatus: null,
            hitCount: 0,
            newCount: 0,
          },
        ],
      })
      .mockResolvedValueOnce({
        config: { strategyId: 'oversold_bounce', strategyName: '超跌反弹', enabled: true, mode: 'quick' },
        alerted: 2,
      })
      .mockResolvedValueOnce({ hits: [] })
      .mockResolvedValueOnce({
        configs: [
          {
            strategyId: 'oversold_bounce',
            strategyName: '超跌反弹',
            enabled: true,
            mode: 'quick',
            lastRunAt: '2026-09-07T07:40:00+00:00',
            lastStatus: 'ok',
            hitCount: 3,
            newCount: 2,
          },
        ],
      });

    const wrapper = mount(ViewScreener);
    const tabs = wrapper.findAll('.screener-tab');
    await tabs.find((t) => t.text() === '策略')!.trigger('click');
    await new Promise((resolve) => setTimeout(resolve, 0));

    await wrapper.find('[data-testid="scan-now"]').trigger('click');
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(requestJson).toHaveBeenCalledWith('/api/screener/scan/now', expect.objectContaining({ method: 'POST' }));
    expect(wrapper.find('[data-testid="scan-status"]').text()).toContain('命中 3');
  });
});

describe('ViewScreener 自定义策略编辑器', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
    setActivePinia(createPinia());
  });

  function builtinRow() {
    return {
      id: 'oversold_bounce',
      name: '超跌反弹',
      description: '内置',
      sortBy: 'changePct',
      topN: 10,
      deepCap: 200,
      factorCount: 1,
      quickFilters: { pe: [0, 25] },
      advancedFactors: [{ name: 'rsi', period: 14, operator: '<', threshold: 30, weight: 2 }],
    };
  }

  async function openEditor() {
    const screener = useScreenerStore();
    screener.screenerMode = 'strategy';
    screener.strategies = [builtinRow()];
    const wrapper = mount(ViewScreener);
    await wrapper.find('[data-testid="new-custom-strategy"]').trigger('click');
    await flushPromises();
    return { screener, wrapper };
  }

  it('新建模式渲染编辑器表单与 fork 下拉', async () => {
    const { wrapper } = await openEditor();
    expect(wrapper.find('.custom-strategy-panel').exists()).toBe(true);
    expect(wrapper.find('input[aria-label="策略名称"]').exists()).toBe(true);
    expect(wrapper.find('select[aria-label="从内置策略复制"]').exists()).toBe(true);
    expect(wrapper.text()).toContain('粗筛区间');
  });

  it('从内置策略复制预填表单（名称加副本后缀）', async () => {
    const { wrapper } = await openEditor();
    await wrapper.find('select[aria-label="从内置策略复制"]').setValue('oversold_bounce');
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '预填')!
      .trigger('click');
    const nameInput = wrapper.find('input[aria-label="策略名称"]');
    expect((nameInput.element as HTMLInputElement).value).toBe('超跌反弹（副本）');
    expect(wrapper.findAll('.factor-row').length).toBe(1);
  });

  it('保存组装 POST payload（空粗筛区间被过滤）', async () => {
    const { wrapper } = await openEditor();
    // workspace.requestJson 走原生 fetch——这里 stub 全局 fetch（响应形状 = workspace 契约）
    const fetchMock = vi.fn(async (_url: string | URL, _options?: RequestInit) => ({
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: async () => ({ strategies: [], total: 0 }),
    }));
    vi.stubGlobal('fetch', fetchMock);
    await wrapper.find('input[aria-label="策略名称"]').setValue('我的动量');
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '添加因子')!
      .trigger('click');
    await wrapper.find('select[aria-label="因子1"]').setValue('momentum');
    await wrapper.find('input[aria-label="权重"]').setValue('1.5');
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '保存')!
      .trigger('click');
    await flushPromises();
    vi.unstubAllGlobals();
    const post = fetchMock.mock.calls.find(
      (c) => String(c[0]) === '/api/screener/custom-strategies' && c[1]?.method === 'POST'
    );
    expect(post).toBeTruthy();
    const body = JSON.parse(post![1]!.body as string);
    expect(body.name).toBe('我的动量');
    expect(body.quickFilters).toEqual({});
    expect(body.advancedFactors).toEqual([{ name: 'momentum', period: 14, operator: '<', threshold: 30, weight: 1.5 }]);
  });

  it('乐观锁 409：显示冲突横幅并回显服务器版本', async () => {
    const { wrapper } = await openEditor();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 409,
        headers: { get: () => null },
        json: async () => ({
          detail: {
            error: '策略已被其他页面更新，请刷新后重试',
            code: 'SCREENER_STRATEGY_CONFLICT',
            server: { version: 7, name: '服务器名', config: { quick_filters: {}, advanced_factors: [] } },
          },
        }),
      }))
    );
    await wrapper.find('input[aria-label="策略名称"]').setValue('本地输入');
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '保存')!
      .trigger('click');
    await flushPromises();
    vi.unstubAllGlobals();
    expect(wrapper.find('[data-testid="conflict-banner"]').text()).toContain('已被其他页面更新');
  });

  // ---- 硬化：2026-10-03 审计发现的缺口 ----

  it('清空数字输入框不再提交空字符串（回落未填语义）', async () => {
    const { wrapper } = await openEditor();
    const fetchMock = vi.fn(async (_url: string | URL, _options?: RequestInit) => ({
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: async () => ({ strategies: [], total: 0 }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    await wrapper.find('input[aria-label="策略名称"]').setValue('归一');
    const peMin = wrapper.find('input[aria-label="市盈率最小值"]');
    await peMin.setValue('10');
    await peMin.setValue(''); // 清空 → Vue .number 会写回 ''
    await wrapper.find('input[aria-label="Top N"]').setValue('');
    await wrapper.find('input[aria-label="精筛上限"]').setValue('');
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '保存')!
      .trigger('click');
    await flushPromises();
    vi.unstubAllGlobals();

    const post = fetchMock.mock.calls.find(
      (c) => String(c[0]) === '/api/screener/custom-strategies' && (c[1] as RequestInit)?.method === 'POST'
    );
    expect(post).toBeTruthy();
    const body = JSON.parse((post![1] as RequestInit).body as string);
    expect(body.quickFilters).toEqual({});
    expect('topN' in body).toBe(false);
    expect('deepCap' in body).toBe(false);
  });

  it('因子阈值留空：中文内联提示且不提交', async () => {
    const { wrapper } = await openEditor();
    const fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: async () => ({ strategies: [], total: 0 }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    await wrapper.find('input[aria-label="策略名称"]').setValue('阈值空');
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '添加因子')!
      .trigger('click');
    await wrapper.find('input[aria-label="阈值"]').setValue('');
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '保存')!
      .trigger('click');
    await flushPromises();
    vi.unstubAllGlobals();

    expect(fetchMock).not.toHaveBeenCalled();
    const error = wrapper.find('.custom-strategy-error');
    expect(error.exists()).toBe(true);
    expect(error.text()).toContain('阈值');
    expect(error.text()).toContain('第 1 条');
  });

  it('409 冲突：保留本地编辑，仅刷新版本以便重试', async () => {
    const screener = useScreenerStore();
    screener.screenerMode = 'strategy';
    screener.strategies = [{ ...builtinRow(), id: 'custom_abc', custom: true, version: 7 }];
    screener.strategyName = 'custom_abc';

    const row = (overrides: Record<string, unknown> = {}) => ({
      id: 'custom_abc',
      name: '服务器名',
      description: '',
      version: 7,
      sourceBuiltin: null,
      config: { quick_filters: {}, advanced_factors: [], sort_by: 'changePct', top_n: 10, deep_cap: 200 },
      scanReferences: [],
      strategies: [],
      total: 0,
      ...overrides,
    });
    let putCount = 0;
    const fetchMock = vi.fn(async (_url: string | URL, options?: RequestInit) => {
      if ((options?.method || 'GET') === 'GET') {
        return { ok: true, status: 200, headers: { get: () => null }, json: async () => row() };
      }
      putCount += 1;
      if (putCount === 1) {
        return {
          ok: false,
          status: 409,
          headers: { get: () => null },
          json: async () => ({
            detail: {
              error: '策略已被其他页面更新，请刷新后重试',
              code: 'SCREENER_STRATEGY_CONFLICT',
              server: row({ name: '服务器名2', version: 8 }),
            },
          }),
        };
      }
      return { ok: true, status: 200, headers: { get: () => null }, json: async () => row({ version: 9 }) };
    });
    vi.stubGlobal('fetch', fetchMock);

    const wrapper = mount(ViewScreener);
    await wrapper.find('[data-testid="edit-custom-strategy"]').trigger('click');
    await flushPromises();

    await wrapper.find('input[aria-label="策略名称"]').setValue('本地输入');
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '保存')!
      .trigger('click');
    await flushPromises();

    // 本地输入不得被服务器行覆盖
    expect((wrapper.find('input[aria-label="策略名称"]').element as HTMLInputElement).value).toBe('本地输入');
    expect(wrapper.find('[data-testid="conflict-banner"]').text()).toContain('已被其他页面更新');

    // 版本已刷新 → 再次保存携带服务器最新 version
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '保存')!
      .trigger('click');
    await flushPromises();
    vi.unstubAllGlobals();

    const puts = fetchMock.mock.calls.filter((c) => (c[1] as RequestInit)?.method === 'PUT');
    expect(puts.length).toBe(2);
    expect(JSON.parse((puts[1]![1] as RequestInit).body as string).version).toBe(8);
  });

  it('422 原样展示后端中文 detail', async () => {
    const { wrapper } = await openEditor();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 422,
        headers: { get: () => null },
        json: async () => ({ detail: { error: '名称：长度不能超过 64 个字符', code: 'VALIDATION_ERROR' } }),
      }))
    );
    await wrapper.find('input[aria-label="策略名称"]').setValue('超长');
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '保存')!
      .trigger('click');
    await flushPromises();
    vi.unstubAllGlobals();

    const error = wrapper.find('.custom-strategy-error');
    expect(error.exists()).toBe(true);
    expect(error.text()).toContain('名称：长度不能超过 64 个字符');
  });

  it('自定义策略名以文本插值渲染（无 v-html 注入）', () => {
    const screener = useScreenerStore();
    screener.screenerMode = 'strategy';
    screener.strategies = [{ ...builtinRow(), id: 'custom_x', name: '<img src=x onerror=alert(1)>', custom: true }];
    const wrapper = mount(ViewScreener);

    expect(wrapper.find('img').exists()).toBe(false);
    // 自定义行带角标前缀，名称本体仍是原样文本（Vue 文本插值自动转义）
    expect(wrapper.find('select option[value="custom_x"]').text()).toBe('自定义 · <img src=x onerror=alert(1)>');
  });

  it('策略下拉：自定义行带「自定义」角标，内置行不变', () => {
    const screener = useScreenerStore();
    screener.screenerMode = 'strategy';
    screener.strategies = [
      builtinRow(),
      { ...builtinRow(), id: 'custom_y', name: '我的动量', custom: true, version: 2 },
    ];
    const wrapper = mount(ViewScreener);

    const customOption = wrapper.find('select option[value="custom_y"]');
    expect(customOption.text()).toContain('自定义');
    expect(customOption.text()).toContain('我的动量');
    expect(wrapper.find('select option[value="oversold_bounce"]').text()).not.toContain('自定义');
  });

  it('从内置复制：提交 sourceBuiltin 来源', async () => {
    const { wrapper } = await openEditor();
    const fetchMock = vi.fn(async (_url: string | URL, _options?: RequestInit) => ({
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: async () => ({ strategies: [], total: 0 }),
    }));
    vi.stubGlobal('fetch', fetchMock);

    await wrapper.find('select[aria-label="从内置策略复制"]').setValue('oversold_bounce');
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '预填')!
      .trigger('click');
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '保存')!
      .trigger('click');
    await flushPromises();
    vi.unstubAllGlobals();

    const post = fetchMock.mock.calls.find(
      (c) => String(c[0]) === '/api/screener/custom-strategies' && (c[1] as RequestInit)?.method === 'POST'
    );
    expect(post).toBeTruthy();
    expect(JSON.parse((post![1] as RequestInit).body as string).sourceBuiltin).toBe('oversold_bounce');
  });

  it('编辑自定义策略：保留 fork 来源 sourceBuiltin', async () => {
    const screener = useScreenerStore();
    screener.screenerMode = 'strategy';
    screener.strategies = [{ ...builtinRow(), id: 'custom_abc', custom: true, version: 3 }];
    screener.strategyName = 'custom_abc';

    const row = {
      id: 'custom_abc',
      name: '趋势副本',
      description: '',
      version: 3,
      sourceBuiltin: 'trend_breakout',
      config: { quick_filters: {}, advanced_factors: [], sort_by: 'changePct', top_n: 10, deep_cap: 200 },
      scanReferences: [],
      strategies: [],
      total: 0,
    };
    const fetchMock = vi.fn(async (_url: string | URL, options?: RequestInit) => ({
      ok: true,
      status: 200,
      headers: { get: () => null },
      json: async () => (options?.method === 'PUT' ? { ...row, version: 4 } : row),
    }));
    vi.stubGlobal('fetch', fetchMock);

    const wrapper = mount(ViewScreener);
    await wrapper.find('[data-testid="edit-custom-strategy"]').trigger('click');
    await flushPromises();
    await wrapper
      .findAll('button')
      .find((b) => b.text() === '保存')!
      .trigger('click');
    await flushPromises();
    vi.unstubAllGlobals();

    const put = fetchMock.mock.calls.find((c) => (c[1] as RequestInit)?.method === 'PUT');
    expect(put).toBeTruthy();
    const body = JSON.parse((put![1] as RequestInit).body as string);
    expect(body.version).toBe(3);
    expect(body.sourceBuiltin).toBe('trend_breakout');
  });
});
