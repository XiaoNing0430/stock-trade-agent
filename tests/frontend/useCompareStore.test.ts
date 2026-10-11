import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useCompareStore } from '@/stores/useCompareStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { useGridStore } from '@/stores/useGridStore';
import { useStrategyStore } from '@/stores/useStrategyStore';

const downloadCsv = vi.fn();
vi.mock('@/modules/csv', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  downloadCsv: (...a: unknown[]) => downloadCsv(...a),
}));

function jsonResponse(payload: unknown, ok = true, status = 200) {
  return { ok, status, headers: { get: () => null }, json: async () => payload };
}

const RUN_PAYLOAD = {
  code: '600519',
  profile: {},
  dataSource: 'tencent',
  dataAsOf: '2026-08-30',
  barCount: 60,
  benchmarkCurve: [
    { date: '2026-01-01', equity: 1 },
    { date: '2026-01-02', equity: 1.01 },
  ],
  results: [
    {
      strategyType: 'grid',
      label: '网格',
      config: { gridCount: 8, lower: 90, upper: 110 },
      metrics: { returnPct: 5.2, maxDrawdownPct: 3 },
      equityCurve: [
        { date: '2026-01-01', equity: 1.0 },
        { date: '2026-01-02', equity: 1.02 },
      ],
      trades: [{ date: '2026-01-02', side: 'buy', triggerPrice: 90, price: 90.1, shares: 100, fee: 5 }],
      assumptions: '假设',
      error: null,
    },
    { strategyType: 'macd', label: 'MACD', error: '回测失败：引擎炸了' },
  ],
};

const SAVED_PAYLOAD = {
  rerun: false,
  results: [
    {
      id: 'grid-1',
      found: true,
      source: 'grid',
      name: '网格A',
      strategyType: 'grid',
      code: '600519',
      latestMetrics: { returnPct: 5 },
      missingReason: null,
    },
    { id: 'nope', found: false, missingReason: '不存在或不属于当前工作区' },
  ],
};

describe('useCompareStore', () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    setActivePinia(createPinia());
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    downloadCsv.mockClear();
  });

  it('默认勾选 8 个回测策略类型（不含 compare tab 自身）', () => {
    const store = useCompareStore();
    expect(store.selectedTypes).toHaveLength(8);
    expect(store.selectedTypes).not.toContain('compare');
    expect(store.selectedTypes).toContain('grid');
    expect(store.selectedTypes).toContain('multi_factor');
  });

  it('toggleType 勾选/取消', () => {
    const store = useCompareStore();
    store.toggleType('grid');
    expect(store.selectedTypes).not.toContain('grid');
    store.toggleType('grid');
    expect(store.selectedTypes).toContain('grid');
  });

  it('runCompare 发送勾选类型并保存结果；全空时中文提示不发请求', async () => {
    const workspace = useWorkspaceStore();
    const toastSpy = vi.spyOn(workspace, 'showToast');
    fetchMock.mockResolvedValue(jsonResponse(RUN_PAYLOAD));
    const store = useCompareStore();
    store.compareDraft.code = '600519';
    await store.runCompare();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, options] = fetchMock.mock.calls[0];
    expect(options.url ?? '/api/strategy/compare').toBe('/api/strategy/compare');
    expect(JSON.parse(options.body).strategyTypes).toHaveLength(8);
    expect(store.runResult?.results).toHaveLength(2);
    expect(store.runLoading).toBe(false);
    // 全空 → 不发请求
    store.selectedTypes = [];
    await store.runCompare();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(toastSpy).toHaveBeenCalledWith('至少勾选一个策略类型', 'error');
  });

  it('runCompare 422 时中文 toast 且不保存结果', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ detail: { error: '未知策略类型：nope', code: 'VALIDATION_ERROR' } }, false, 422)
    );
    const workspace = useWorkspaceStore();
    const toastSpy = vi.spyOn(workspace, 'showToast');
    const store = useCompareStore();
    await store.runCompare();
    expect(store.runResult).toBeNull();
    expect(toastSpy).toHaveBeenCalledWith('未知策略类型：nope', 'error');
  });

  it('runChartSvg：成功策略实线 + 基准虚线，error 策略跳过', () => {
    const store = useCompareStore();
    store.runResult = RUN_PAYLOAD;
    expect(store.runChartSvg).toContain('chart-line');
    expect(store.runChartSvg).toContain('网格');
    expect(store.runChartSvg).not.toContain('MACD');
  });

  it('compareSaved(snapshot) 读库并保存结果', async () => {
    fetchMock.mockResolvedValue(jsonResponse(SAVED_PAYLOAD));
    const store = useCompareStore();
    store.savedSelection = ['grid-1', 'nope'];
    await store.compareSaved('snapshot');
    expect(store.savedResult?.rerun).toBe(false);
    expect(store.savedLoading).toBe(false);
  });

  it('exportRunCsv 三种导出走 downloadCsv 且文件名正确', () => {
    const store = useCompareStore();
    store.runResult = RUN_PAYLOAD;
    store.exportRunCsv('metrics');
    store.exportRunCsv('curves');
    store.exportRunCsv('trades');
    expect(downloadCsv).toHaveBeenCalledTimes(3);
    expect(String(downloadCsv.mock.calls[0][0])).toMatch(/^atlas-compare-metrics-\d+\.csv$/);
    expect(String(downloadCsv.mock.calls[1][0])).toMatch(/^atlas-compare-curves-\d+\.csv$/);
    expect(String(downloadCsv.mock.calls[2][0])).toMatch(/^atlas-compare-trades-\d+\.csv$/);
    const tradesCsv = String(downloadCsv.mock.calls[2][1]);
    expect(tradesCsv).toContain('网格');
    expect(tradesCsv).not.toContain('MACD'); // error 策略无成交
  });

  it('exportSavedCsv：snapshot 只有 metrics 可导，rerun 才有 trades', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        rerun: true,
        results: [
          {
            id: 'grid-1',
            found: true,
            source: 'grid',
            name: '网格A',
            strategyType: 'grid',
            code: '600519',
            config: { gridCount: 8 },
            metrics: { returnPct: 6 },
            trades: [{ date: '2026-01-02', side: 'buy', price: 90, shares: 100, fee: 5 }],
            assumptions: '假设',
            dataSource: 'tencent',
            dataAsOf: '2026-08-30',
            error: null,
          },
        ],
      })
    );
    const store = useCompareStore();
    store.savedSelection = ['grid-1'];
    await store.compareSaved('rerun');
    store.exportSavedCsv('trades');
    expect(downloadCsv).toHaveBeenCalledTimes(1);
    expect(String(downloadCsv.mock.calls[0][1])).toContain('网格A');
    // snapshot 无 trades：导出 trades 时提示且不下载
    downloadCsv.mockClear();
    store.savedResult = SAVED_PAYLOAD;
    const workspace = useWorkspaceStore();
    const toastSpy = vi.spyOn(workspace, 'showToast');
    store.exportSavedCsv('trades');
    expect(downloadCsv).not.toHaveBeenCalled();
    expect(toastSpy).toHaveBeenCalledWith('快照模式无成交明细，请先用「重新回测并对比」', 'error');
  });

  it('savedOptions 合并网格与普通策略', () => {
    const store = useCompareStore();
    const grid = useGridStore();
    grid.gridStrategies = [
      { id: 'grid-1', name: '网格A', code: '600519', mode: 'classic', status: '启用', lastBacktestAt: '2026-10-10' },
    ];
    useStrategyStore().strategies = [
      {
        id: 'strategy-1',
        name: '双均线A',
        code: '600519',
        strategyType: 'ma_cross',
        status: '启用',
        lastBacktestAt: null,
      },
    ];
    expect(store.savedOptions.map((option) => option.key)).toEqual(['grid-1', 'strategy-1']);
    expect(store.savedOptions[0].typeLabel).toBe('经典网格');
    expect(store.savedOptions[1].typeLabel).toBe('双均线');
  });

  it('selectAllSaved 全选截断到 10；toggleSaved 满 10 后 no-op；clearSavedSelection 清空', () => {
    const store = useCompareStore();
    const grid = useGridStore();
    grid.gridStrategies = Array.from({ length: 12 }, (_, i) => ({
      id: `grid-${i}`,
      name: `网格${i}`,
      code: '600519',
      mode: 'classic',
      status: '启用',
      lastBacktestAt: null,
    }));
    // 全选：12 个 option 截断到前 10
    store.selectAllSaved();
    expect(store.savedSelection).toHaveLength(10);
    expect(store.savedSelection[0]).toBe('grid-0');
    expect(store.savedSelection[9]).toBe('grid-9');
    // 满 10 后 toggle 未选项 no-op
    store.toggleSaved('grid-11');
    expect(store.savedSelection).toHaveLength(10);
    expect(store.savedSelection).not.toContain('grid-11');
    // 清空后可再正常勾选
    store.clearSavedSelection();
    expect(store.savedSelection).toHaveLength(0);
    store.toggleSaved('grid-11');
    expect(store.savedSelection).toEqual(['grid-11']);
  });
});
