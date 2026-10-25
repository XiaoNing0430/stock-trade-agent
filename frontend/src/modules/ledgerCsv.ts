// 成交台账 CSV（复用 csv.ts：每格都过 csvCell，含公式注入缓解与 RFC4180 包裹）
import { buildCsv } from './csv';
import type { FillRow } from '@/types/models';

function stamp(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function buildFillsCsv(rows: FillRow[]): string {
  const header = ['成交时间', '方向', '代码', '价格', '数量', '费用', '金额', '关联计划', '状态', '备注'];
  const body = rows.map((row) => [
    stamp(row.tradedAtMs),
    row.direction === 'buy' ? '买入' : '卖出',
    row.code,
    row.price.toFixed(2),
    row.qty,
    row.fee.toFixed(2),
    (row.price * row.qty).toFixed(2),
    row.planId ?? '',
    row.voidedAtMs ? '已作废' : '有效',
    row.note,
  ]);
  return buildCsv(header, body);
}
