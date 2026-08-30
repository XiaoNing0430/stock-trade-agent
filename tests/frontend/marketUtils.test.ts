import { describe, expect, it } from 'vitest';
import { mergeMarketQuotes } from '@/modules/marketUtils';
import type { Quote } from '@/types/models';

const q = (code: string, price: number): Quote => ({
  code,
  name: `股票${code}`,
  price,
  change: 0,
  changePct: 0,
  volumeRatio: 1,
});

describe('marketUtils', () => {
  it('mergeMarketQuotes 同名 code 由 incoming 覆盖', () => {
    const existing = [q('600519', 1700), q('000001', 11)];
    const incoming = [q('600519', 1750)];
    const result = mergeMarketQuotes(existing, incoming);
    expect(result).toHaveLength(2);
    expect(result.find((r) => r.code === '600519')?.price).toBe(1750);
    expect(result.find((r) => r.code === '000001')?.price).toBe(11);
  });
  it('mergeMarketQuotes 新 code 追加且保持原顺序', () => {
    const existing = [q('600519', 1700)];
    const incoming = [q('000001', 11), q('300750', 88)];
    const result = mergeMarketQuotes(existing, incoming);
    expect(result.map((r) => r.code)).toEqual(['600519', '000001', '300750']);
  });
  it('mergeMarketQuotes 空输入与不修改入参', () => {
    expect(mergeMarketQuotes([], [])).toEqual([]);
    expect(mergeMarketQuotes([q('600519', 1700)], [])).toHaveLength(1);
    expect(mergeMarketQuotes([], [q('600519', 1700)])).toHaveLength(1);
    const existing = [q('600519', 1700)];
    const incoming = [q('600519', 1750)];
    mergeMarketQuotes(existing, incoming);
    expect(existing[0].price).toBe(1700);
  });
});
