import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const requestJson = vi.fn();
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  requestJson: (...args: unknown[]) => requestJson(...args),
}));

import { useLedgerStore } from '@/stores/useLedgerStore';

const FILL = {
  id: 'fill_a1',
  clientRequestId: null,
  code: '600519',
  direction: 'buy' as const,
  price: 10,
  qty: 100,
  fee: 5,
  tradedAtMs: 1760000000000,
  planId: null,
  note: '',
  voidedAtMs: null,
  voidReason: null,
  createdAtMs: 1,
  updatedAtMs: 1,
};

const POSITION = {
  code: '600519',
  name: '贵州茅台',
  qty: 100,
  avgCost: 10.05,
  costBasis: 1005,
  lastPrice: 12,
  marketValue: 1200,
  unrealizedPnl: 195,
  realizedPnl: 0,
};

function mockLoad() {
  requestJson.mockImplementation((url: string) =>
    url.startsWith('/api/positions')
      ? Promise.resolve({
          positions: [POSITION],
          totals: { marketValue: 1200, unrealizedPnl: 195, realizedPnl: 0, costBasis: 1005 },
          warnings: [],
          disclosures: ['市值为实时不复权价口径'],
        })
      : Promise.resolve({ items: [FILL] })
  );
}

describe('useLedgerStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    requestJson.mockReset();
  });

  it('loads fills and positions', async () => {
    mockLoad();
    const store = useLedgerStore();
    const result = await store.load();
    expect(result.ok).toBe(true);
    expect(store.fills).toHaveLength(1);
    expect(store.positions[0].avgCost).toBe(10.05);
    expect(store.positionFor('600519')?.qty).toBe(100);
    expect(store.positionFor('000001')).toBeNull();
    expect(store.disclosures).toHaveLength(1);
    expect(store.error).toBe('');
  });

  it('createFill posts payload with client request id and reloads', async () => {
    requestJson.mockImplementation((url: string, init?: RequestInit) => {
      if (url === '/api/fills' && init?.method === 'POST') {
        const body = JSON.parse(String(init.body));
        expect(body.qty).toBe(100);
        expect(body.clientRequestId).toMatch(/^ui-/);
        return Promise.resolve({ fill: FILL, warnings: [], planMissing: false });
      }
      return url.startsWith('/api/positions')
        ? Promise.resolve({ positions: [POSITION], totals: {}, warnings: [], disclosures: [] })
        : Promise.resolve({ items: [FILL] });
    });
    const store = useLedgerStore();
    const result = await store.createFill({
      code: '600519',
      direction: 'buy',
      price: 10,
      qty: 100,
      fee: 5,
      tradedAtMs: 1760000000000,
    });
    expect(result.ok).toBe(true);
    expect(store.fills).toHaveLength(1);
  });

  it('surfaces backend chinese error', async () => {
    requestJson.mockRejectedValue(new Error('卖出 200 股超过可用持仓 100 股'));
    const store = useLedgerStore();
    const result = await store.createFill({
      code: '600519',
      direction: 'sell',
      price: 10,
      qty: 200,
      fee: 0,
      tradedAtMs: 1760000000000,
    });
    expect(result.ok).toBe(false);
    expect(result.message).toContain('超过可用持仓');
  });

  it('voidFill posts reason and reloads', async () => {
    requestJson.mockImplementation((url: string) => {
      if (url.endsWith('/void')) return Promise.resolve({ fill: { ...FILL, voidedAtMs: 1 } });
      return url.startsWith('/api/positions')
        ? Promise.resolve({ positions: [], totals: {}, warnings: [], disclosures: [] })
        : Promise.resolve({ items: [] });
    });
    const store = useLedgerStore();
    const result = await store.voidFill('fill_a1', '录错');
    expect(result.ok).toBe(true);
    expect(requestJson).toHaveBeenCalledWith('/api/fills/fill_a1/void', expect.objectContaining({ method: 'POST' }));
    expect(store.fills).toHaveLength(0);
  });

  it('load failure keeps error message and does not throw', async () => {
    requestJson.mockRejectedValue(new Error('成交记录读取失败'));
    const store = useLedgerStore();
    const result = await store.load();
    expect(result.ok).toBe(false);
    expect(store.error).toContain('成交记录读取失败');
  });
});
