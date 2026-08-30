import type { Plan, Quote } from '@/types/models';

export function signalText(stock: Quote | undefined | null, plan: Plan | null): string {
  if (plan && stock?.price != null) {
    if (stock.price <= plan.stop) return '触及止损';
    if (stock.price >= plan.target) return '触及目标';
    if (stock.price <= plan.entry) return '触及计划价';
  }
  if (stock?.change == null) return '等待报价';
  if (stock.change >= 3 && Number(stock.volumeRatio || 0) >= 1.5) return '放量突破';
  if (stock.change <= -3) return '弱势观察';
  if (Number(stock.volumeRatio || 0) >= 1.5) return '量能放大';
  return '跟踪中';
}

export function signalClass(text: string): string {
  if (text === '触及止损') return 'signal-chip-risk';
  if (text === '触及目标' || text === '触及计划价' || text === '放量突破') return 'signal-chip-buy';
  if (text === '等待报价') return 'signal-chip-neutral';
  return 'signal-chip-watch';
}
