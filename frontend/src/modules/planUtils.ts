import type { Plan } from '@/types/models';
import { validityExpiry } from '@/modules/format';

export function calculateShares(plan: Plan): number {
  const budget = Number(plan.capital || 0) * (Number(plan.position || 0) / 100);
  return plan.entry > 0 ? Math.max(0, Math.floor(budget / plan.entry / 100) * 100) : 0;
}

export function calculateRr(plan: Plan): number {
  const risk = Math.max(0.01, Number(plan.entry) - Number(plan.stop));
  const reward = Math.max(0, Number(plan.target) - Number(plan.entry));
  return reward / risk;
}

export function expiredPlans(plans: Plan[], now: number): Plan[] {
  const result: Plan[] = [];
  for (const plan of plans) {
    if (plan.status !== '执行中') continue;
    const expiresAt = validityExpiry(plan.createdAtMs, plan.validity);
    if (expiresAt && now > expiresAt) result.push({ ...plan, status: '已过期' });
  }
  return result;
}
