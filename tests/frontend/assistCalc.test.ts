import { describe, expect, it } from 'vitest';
import { selectStop, sizePosition } from '@/modules/assistCalc';
import type { SizingInput } from '@/modules/assistCalc';

// 警示文案与 backend/assist/calculator.py sizing() 逐字一致（契约）
const manualStopWarning = '候选止损价均不低于入场价，已置空止损（强趋势 / 数据不足），请手动设定';
const insufficientEquityWarning = '权益不足一手，无法按该风险比例建仓';
const capTruncateWarning = '建议仓位已按单票市值上限截断';
const multiDayTargetWarning = '目标位距入场价超单日涨幅上限，需多日达成';

const baseInput: SizingInput = {
  entry: 10,
  stopMode: 'atr',
  atr14: 0.5,
  ma20: 9.8,
  equity: 100000,
  riskPct: 1,
  rrRatio: 2,
  capPct: 25,
  limitRatio: 0.25,
};

describe('selectStop', () => {
  it('atr 模式优先且有效（入场 10、ATR 0.5 → 止损 9.0）', () => {
    expect(selectStop(10, 0.5, 9.8, 'atr')).toEqual({ stop: 9.0, warnings: [] });
  });

  it('ma20 模式取 ma20', () => {
    expect(selectStop(10, 0.5, 9.8, 'ma20')).toEqual({ stop: 9.8, warnings: [] });
  });

  it('首选候选不低于入场价时回退备选', () => {
    // ma20=10.2 ≥ 入场价无效，回退 ATR 候选 9.0
    expect(selectStop(10, 0.5, 10.2, 'ma20').stop).toBe(9.0);
  });

  it('候选价按两位小数舍入后再判定有效性', () => {
    // entry - 2*atr = 10 - 0.6666 = 9.334 → 9.33
    expect(selectStop(10, 0.3333, null, 'atr').stop).toBe(9.33);
    // ma20 舍入：9.8765 → 9.88
    expect(selectStop(10, null, 9.8765, 'ma20').stop).toBe(9.88);
  });

  it('×100 浮点缩放伪平局：2.675 的 double 严格低于十进制 2.675，ma20 候选为 2.67', () => {
    // 2.675 的 double = 2.6749999999999998224（严格低于），非平局 → Python round 得 2.67；
    // 旧实现 value*100 的乘积被舍入成精确的 267.5，误判平局（floor 267 为奇 → 进位）得 2.68。
    expect(selectStop(10, 5, 2.675, 'ma20').stop).toBe(2.67);
    // 对照：22.7/20 恰为 double 1.135（精确 1.1350000000000000089 ≥ 1.135），
    // Python round(22.7/20, 2) = 1.14，实现必须同为 1.14 而非 1.13。
    expect(selectStop(10, 5, 22.7 / 20, 'ma20').stop).toBe(1.14);
  });

  it('精确平局 dyadic：10.125 半程偶舍为 10.12（toFixed 会给出 10.13）', () => {
    // 10.125 = 81/8 精确可表示，×100 = 1012.5 恰好半程 → 舍入到偶数 1012 → 10.12
    expect(selectStop(11, null, 10.125, 'ma20').stop).toBe(10.12);
  });

  it('atr14 为 null 时该候选置空并回退 ma20', () => {
    expect(selectStop(10, null, 9.8, 'atr')).toEqual({ stop: 9.8, warnings: [] });
  });

  it('全部候选缺失返回 null 且不提示手动设定（数据不足提示由调用方负责）', () => {
    expect(selectStop(10, null, null, 'atr')).toEqual({ stop: null, warnings: [] });
  });

  it('候选均不低于入场价：止损置空并提示手动设定', () => {
    // ATR 数据不足（null）且 ma20=10.2 ≥ 入场价（强趋势）
    expect(selectStop(10, null, 10.2, 'atr')).toEqual({ stop: null, warnings: [manualStopWarning] });
    // 舍入后候选恰好等于入场价同样无效：10 - 2*0.002 = 9.996 → 10.0
    expect(selectStop(10, 0.002, null, 'atr')).toEqual({ stop: null, warnings: [manualStopWarning] });
  });
});

describe('sizePosition', () => {
  it('基准：整手 1000 股、目标 12.0、仓位 10%', () => {
    expect(sizePosition(baseInput)).toEqual({
      stop: 9.0,
      target: 12.0,
      stopDistance: 1.0,
      suggestedShares: 1000,
      positionPct: 10.0,
      warnings: [],
    });
  });

  it('权益不足一手：股数 0 并提示', () => {
    const r = sizePosition({ ...baseInput, equity: 9000 });
    expect(r.stop).toBe(9.0);
    expect(r.target).toBe(12.0);
    expect(r.suggestedShares).toBe(0);
    expect(r.positionPct).toBe(0);
    expect(r.warnings).toEqual([insufficientEquityWarning]);
  });

  it('风险仓位超单票市值上限：按整手截断', () => {
    const r = sizePosition({ ...baseInput, riskPct: 5 });
    expect(r.suggestedShares).toBe(2500);
    expect(r.positionPct).toBe(25.0);
    expect(r.warnings).toEqual([capTruncateWarning]);
  });

  it('目标位超单日涨幅上限：提示需多日达成', () => {
    // limitRatio 0.1（主板 10%），目标 12.0 距入场 20%
    const r = sizePosition({ ...baseInput, limitRatio: 0.1 });
    expect(r.target).toBe(12.0);
    expect(r.warnings).toEqual([multiDayTargetWarning]);
  });

  it('候选全部无效：止损/目标置空、股数 0，仅提示手动设定', () => {
    const r = sizePosition({ ...baseInput, atr14: null, ma20: 10.2 });
    expect(r).toEqual({
      stop: null,
      target: null,
      stopDistance: null,
      suggestedShares: 0,
      positionPct: 0,
      warnings: [manualStopWarning],
    });
  });

  it('指标全缺：输出零值且无本模块警示（数据不足提示由调用方负责）', () => {
    const r = sizePosition({ ...baseInput, atr14: null, ma20: null });
    expect(r).toEqual({
      stop: null,
      target: null,
      stopDistance: null,
      suggestedShares: 0,
      positionPct: 0,
      warnings: [],
    });
  });

  it('ma20 模式端到端：止损 9.8、仓位按上限截断', () => {
    const r = sizePosition({ ...baseInput, stopMode: 'ma20' });
    expect(r.stop).toBe(9.8);
    expect(r.stopDistance).toBe(0.2);
    expect(r.target).toBe(10.4);
    expect(r.suggestedShares).toBe(2500);
    expect(r.positionPct).toBe(25.0);
    expect(r.warnings).toEqual([capTruncateWarning]);
  });

  it('上限截断可归零：股数 0、仓位 0%', () => {
    // equity 3000、riskPct 5% → 风险额 150 → 100 股；市值上限仅容 0 股
    const r = sizePosition({ ...baseInput, equity: 3000, riskPct: 5 });
    expect(r.suggestedShares).toBe(0);
    expect(r.positionPct).toBe(0);
    expect(r.warnings).toEqual([capTruncateWarning]);
  });
});
