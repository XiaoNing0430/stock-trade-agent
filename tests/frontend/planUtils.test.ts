import { describe, expect, it } from 'vitest';
import { calculateShares, calculateRr, expiredPlans } from '@/modules/planUtils';
import type { Plan } from '@/types/models';

const basePlan: Plan = {
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

describe('planUtils', () => {
  it('calculateShares 按资金与仓位计算整手股数', () => {
    // 50000 / 1700 = 29.41 股，不足一手（100 股）→ 0 股
    expect(calculateShares(basePlan)).toBe(0);
    // 50000 / 17 = 2941 股 = 29.41 手 → 整手 2900 股
    expect(calculateShares({ ...basePlan, entry: 17 })).toBe(2900);
    expect(calculateShares({ ...basePlan, entry: 0 })).toBe(0);
    expect(calculateShares({ ...basePlan, capital: 0 })).toBe(0);
    expect(calculateShares({ ...basePlan, position: 0 })).toBe(0);
  });
  it('calculateRr 计算盈亏比', () => {
    expect(calculateRr(basePlan)).toBe(2); // (1900-1700)/(1700-1600)
    // 目标价不高于入场价 → reward 为 0
    expect(calculateRr({ ...basePlan, target: 1600 })).toBe(0);
    // 止损价不低于入场价 → risk 被下限钳到 0.01 → 200 / 0.01 = 20000
    expect(calculateRr({ ...basePlan, stop: 1700 })).toBe(20000);
  });
  it('expiredPlans 标记过期且不改原数组', () => {
    const now = Date.now();
    const plans = [{ ...basePlan, createdAtMs: now - 2 * 86400000 }];
    const result = expiredPlans(plans, now);
    expect(result[0].status).toBe('已过期');
    expect(plans[0].status).toBe('执行中');
    expect(expiredPlans([], now)).toEqual([]);
  });
  it('expiredPlans 忽略非执行中计划与未到期计划', () => {
    const now = Date.now();
    const archived = { ...basePlan, id: 'p2', status: '已归档', createdAtMs: now - 3 * 86400000 };
    const fresh = { ...basePlan, id: 'p3', createdAtMs: now };
    expect(expiredPlans([archived, fresh], now)).toEqual([]);
  });
});
