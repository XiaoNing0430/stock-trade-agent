import { describe, expect, it } from 'vitest';
import { signalText, signalClass } from '@/modules/signalUtils';
import type { Plan, Quote } from '@/types/models';

const plan: Plan = {
  id: 'p1',
  code: '600519',
  direction: 'buy',
  entry: 1700,
  stop: 1600,
  target: 1900,
  capital: 100000,
  position: 50,
  validity: '今日',
  note: '',
  status: '执行中',
  triggered: {},
  createdAtMs: 0,
};

const stock = (overrides: Partial<Quote> = {}): Quote => ({
  code: '600519',
  name: '贵州茅台',
  price: 1700,
  change: 1,
  changePct: 1,
  volumeRatio: 1,
  ...overrides,
});

describe('signalUtils', () => {
  it('signalText 触及止损', () => {
    expect(signalText(stock({ price: 1599 }), plan)).toBe('触及止损');
    expect(signalText(stock({ price: 1600 }), plan)).toBe('触及止损');
  });
  it('signalText 触及目标', () => {
    expect(signalText(stock({ price: 1900 }), plan)).toBe('触及目标');
    expect(signalText(stock({ price: 2000 }), plan)).toBe('触及目标');
  });
  it('signalText 触及计划价', () => {
    // price 在 (stop, target] 范围内且 ≤ entry
    expect(signalText(stock({ price: 1650 }), plan)).toBe('触及计划价');
    expect(signalText(stock({ price: 1700 }), plan)).toBe('触及计划价');
  });
  it('signalText 等待报价', () => {
    // stock 越过计划条件但 change 为空 → 等待报价
    expect(signalText(stock({ price: 1750, change: null }), plan)).toBe('等待报价');
    expect(signalText(stock({ price: null, change: null }), plan)).toBe('等待报价');
    expect(signalText(null, plan)).toBe('等待报价');
    expect(signalText(undefined, plan)).toBe('等待报价');
  });
  it('signalText 放量突破（price 需越过计划条件）', () => {
    const m = { price: 1750, change: 3, volumeRatio: 1.5 };
    expect(signalText(stock(m), plan)).toBe('放量突破');
    expect(signalText(stock({ price: 1750, change: 5, volumeRatio: 2 }), plan)).toBe('放量突破');
  });
  it('signalText 弱势观察', () => {
    expect(signalText(stock({ price: 1750, change: -3 }), plan)).toBe('弱势观察');
    expect(signalText(stock({ price: 1750, change: -5 }), plan)).toBe('弱势观察');
  });
  it('signalText 量能放大', () => {
    expect(signalText(stock({ price: 1750, change: 1, volumeRatio: 2 }), plan)).toBe('量能放大');
  });
  it('signalText 跟踪中', () => {
    expect(signalText(stock({ price: 1750, change: 1, volumeRatio: 1 }), null)).toBe('跟踪中');
    expect(signalText(stock({ price: 1750, change: 2.99, volumeRatio: 1.49 }), null)).toBe('跟踪中');
  });
  it('signalText 无计划时走行情信号', () => {
    expect(signalText(stock({ price: 1750, change: 3, volumeRatio: 1.5 }), null)).toBe('放量突破');
    expect(signalText(stock({ price: 1750, change: -3 }), null)).toBe('弱势观察');
    expect(signalText(stock({ price: 1750, change: 1, volumeRatio: 2 }), null)).toBe('量能放大');
    expect(signalText(stock({ price: 1750, change: 1, volumeRatio: 1 }), null)).toBe('跟踪中');
  });
  it('signalClass 四类 chip', () => {
    expect(signalClass('触及止损')).toBe('signal-chip-risk');
    expect(signalClass('触及目标')).toBe('signal-chip-buy');
    expect(signalClass('触及计划价')).toBe('signal-chip-buy');
    expect(signalClass('放量突破')).toBe('signal-chip-buy');
    expect(signalClass('等待报价')).toBe('signal-chip-neutral');
    expect(signalClass('弱势观察')).toBe('signal-chip-watch');
    expect(signalClass('量能放大')).toBe('signal-chip-watch');
    expect(signalClass('跟踪中')).toBe('signal-chip-watch');
    expect(signalClass('未知')).toBe('signal-chip-watch');
  });
});
