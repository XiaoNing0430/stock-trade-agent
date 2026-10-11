// CSV 组装与下载（多策略对比导出用）。
// 纪律：csvCell 对 = + - @ \t \r 开头的字符串加 "'" 前缀（Excel 公式注入标准缓解，spec §4.3）；
// 数字/布尔豁免（负数如 -12.5 原样输出，不得加前缀）；
// downloadCsv 统一 BOM + Blob，与 useScreenerStore.exportCsv 先例一致。

export function csvCell(value: unknown): string {
  if (value === null || value === undefined) return '';
  const text = String(value);
  const exempt = typeof value === 'number' || typeof value === 'boolean';
  return !exempt && /^[=+\-@\t\r]/.test(text) ? `'${text}` : text;
}

export function buildCsv(headers: string[], rows: unknown[][]): string {
  const line = (row: unknown[]) => row.map((cell) => csvCell(cell)).join(',');
  return [line(headers), ...rows.map(line)].join('\n');
}

export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([`\ufeff${csv}`], { type: 'text/csv;charset=utf-8;' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

/** 指标中文表头映射（spec §6 全集，列顺序固定）。 */
export const METRIC_LABELS: Record<string, string> = {
  returnPct: '区间收益%',
  annualizedReturnPct: '年化收益%',
  benchmarkReturnPct: '基准收益%',
  excessReturnPct: '超额收益%',
  maxDrawdownPct: '最大回撤%',
  maxDrawdownDurationDays: '最长回撤天数',
  annualizedVolatilityPct: '年化波动%',
  sharpeRatio: '夏普比率',
  winRatePct: '胜率%',
  profitFactor: '利润因子',
  avgGridReturnPct: '单格平均收益%',
  medianGridReturnPct: '单格收益中位%',
  tradeCount: '成交次数',
  buyCount: '买入次数',
  sellCount: '卖出次数',
  totalFees: '总费用',
  turnoverMultiple: '换手倍数',
  startEquity: '期初权益',
  endEquity: '期末权益',
  skippedLimitUpDays: '涨停跳过天数',
  skippedLimitDownDays: '跌停跳过天数',
  skippedSuspensionDays: '停牌天数',
  onePriceLimitUpDays: '一字涨停天数',
  onePriceLimitDownDays: '一字跌停天数',
};

export interface CompareMetricRow {
  label: string;
  type: string;
  params: string;
  metrics: Record<string, unknown> | null;
}

/** 参数摘要：按插入序拼 key=value（spec §4.3）。 */
export function summarizeConfig(config: Record<string, unknown> | null | undefined): string {
  if (!config || typeof config !== 'object') return '';
  return Object.entries(config)
    .filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => `${key}=${value}`)
    .join(', ');
}

export function buildCompareMetricsCsv(rows: CompareMetricRow[]): string {
  const keys = Object.keys(METRIC_LABELS);
  const headers = ['策略', '类型', '参数', ...keys.map((key) => METRIC_LABELS[key])];
  const body = rows.map((row) => {
    const metrics = row.metrics || {};
    return [row.label, row.type, row.params, ...keys.map((key) => (metrics[key] ?? null) as unknown)];
  });
  return buildCsv(headers, body);
}

export interface CompareCurvesRun {
  benchmarkCurve: { date: string; equity: number }[] | null;
  results: { label: string; equityCurve: { date: string; equity: number }[] | null }[];
}

/** 宽表：日期 + 每策略一列 + 基准列；error 策略无曲线整列省略（spec §4.3）。 */
export function buildCompareCurvesCsv(run: CompareCurvesRun): string {
  const okResults = (run.results || []).filter((item) => Array.isArray(item.equityCurve));
  const benchmark = run.benchmarkCurve || [];
  const headers = ['日期', ...okResults.map((item) => `${item.label} 净值`), '基准净值'];
  const body: unknown[][] = [];
  for (let i = 0; i < benchmark.length; i++) {
    body.push([
      benchmark[i]?.date ?? '',
      ...okResults.map((item) => item.equityCurve?.[i]?.equity ?? null),
      benchmark[i]?.equity ?? null,
    ]);
  }
  return buildCsv(headers, body);
}

export interface CompareTradesRow {
  label: string;
  trades: Record<string, unknown>[] | null;
}

/** 长表：策略 / 日期 / 方向 / 触发价 / 成交价 / 股数 / 费用 / 模块。 */
export function buildCompareTradesCsv(rows: CompareTradesRow[]): string {
  const headers = ['策略', '日期', '方向', '触发价', '成交价', '股数', '费用', '模块'];
  const body: unknown[][] = [];
  for (const row of rows) {
    for (const trade of row.trades || []) {
      body.push([
        row.label,
        trade.date,
        trade.side,
        trade.triggerPrice ?? null,
        trade.price,
        trade.shares,
        trade.fee,
        trade.module ?? null,
      ]);
    }
  }
  return buildCsv(headers, body);
}
