import { describe, expect, it } from 'vitest';
import { buildFillsCsv } from '@/modules/ledgerCsv';
import type { FillRow } from '@/types/models';

const ROW: FillRow = {
  id: 'fill_a1',
  clientRequestId: null,
  code: '600519',
  direction: 'buy',
  price: 10,
  qty: 100,
  fee: 5,
  tradedAtMs: 1760000000000,
  planId: 'plan-1',
  note: '=cmd|calc',
  voidedAtMs: null,
  voidReason: null,
  createdAtMs: 1,
  updatedAtMs: 1,
};

describe('buildFillsCsv', () => {
  it('includes header and localized direction', () => {
    const csv = buildFillsCsv([ROW]);
    expect(csv.split('\n')[0]).toContain('成交时间');
    expect(csv).toContain('买入');
    expect(csv).toContain('有效');
  });

  it('neutralizes spreadsheet formula injection in notes', () => {
    expect(buildFillsCsv([ROW])).toContain("'=cmd|calc");
  });

  it('marks voided rows', () => {
    expect(buildFillsCsv([{ ...ROW, voidedAtMs: 2 }])).toContain('已作废');
  });
});
