import { escapeHtml } from '@/modules/format';

export function chartSvg(points: number[], accent: string, label: string) {
  if (!Array.isArray(points) || points.length < 2) {
    return '<div class="chart-empty">暂无足够的日线数据</div>';
  }
  const width = 640;
  const height = 150;
  const pad = { top: 12, right: 12, bottom: 24, left: 12 };
  const innerWidth = width - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const coords = points.map((value, index) => {
    const x = pad.left + (index / (points.length - 1)) * innerWidth;
    const y = pad.top + (1 - (value - min) / range) * innerHeight;
    return [x, y];
  });
  const linePath = coords
    .map(([x, y], index) => `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`)
    .join(' ');
  const areaPath = `${linePath} L ${coords[coords.length - 1][0].toFixed(1)} ${height - pad.bottom} L ${coords[0][0].toFixed(1)} ${height - pad.bottom} Z`;
  const grid = [0.22, 0.5, 0.78]
    .map((ratio) => {
      const y = pad.top + innerHeight * ratio;
      return `<line class="chart-grid-line" x1="${pad.left}" y1="${y.toFixed(1)}" x2="${width - pad.right}" y2="${y.toFixed(1)}"></line>`;
    })
    .join('');
  const labels = ['较早', '中段', '最新'];
  const labelMarkup = labels
    .map((text, index) => {
      const x = pad.left + (index / (labels.length - 1)) * innerWidth;
      const anchor = index === 0 ? 'start' : index === labels.length - 1 ? 'end' : 'middle';
      return `<text class="chart-axis-label" x="${x.toFixed(1)}" y="${height - 5}" text-anchor="${anchor}">${text}</text>`;
    })
    .join('');
  const last = coords[coords.length - 1];
  const safeLabel = escapeHtml(label);
  return `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${safeLabel}">
      <title>${safeLabel}</title>
      ${grid}
      <path class="chart-area" style="fill:${accent}16" d="${areaPath}"></path>
      <path class="chart-line" style="stroke:${accent}" d="${linePath}"></path>
      <circle class="chart-dot" style="stroke:${accent}" cx="${last[0].toFixed(1)}" cy="${last[1].toFixed(1)}" r="4"></circle>
      ${labelMarkup}
    </svg>
  `;
}

export function compareChartSvg(
  result:
    | {
        equityCurve?: Array<{ equity: number }>;
        benchmarkCurve?: Array<{ equity: number }>;
      }
    | null
    | undefined
) {
  const strategy = (result?.equityCurve || []).map((point) => Number(point.equity));
  const benchmark = (result?.benchmarkCurve || []).map((point) => Number(point.equity));
  if (strategy.length < 2 || benchmark.length < 2) {
    return '<div class="chart-empty">暂无足够的权益数据</div>';
  }
  const width = 640;
  const height = 150;
  const pad = { top: 12, right: 12, bottom: 24, left: 12 };
  const innerWidth = width - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;
  const all = [...strategy, ...benchmark];
  const min = Math.min(...all);
  const max = Math.max(...all);
  const range = max - min || 1;
  const pathFor = (values: number[]) =>
    values
      .map((value, index) => {
        const x = pad.left + (index / (values.length - 1)) * innerWidth;
        const y = pad.top + (1 - (value - min) / range) * innerHeight;
        return `${index === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`;
      })
      .join(' ');
  const grid = [0.25, 0.5, 0.75]
    .map((ratio) => {
      const y = pad.top + innerHeight * ratio;
      return `<line class="chart-grid-line" x1="${pad.left}" y1="${y.toFixed(1)}" x2="${width - pad.right}" y2="${y.toFixed(1)}"></line>`;
    })
    .join('');
  const label = escapeHtml('网格策略与持有基准的归一化权益对比');
  return `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${label}">
      <title>${label}</title>
      ${grid}
      <path class="chart-line chart-line-benchmark" style="stroke:#9aa7bd" d="${pathFor(benchmark)}"></path>
      <path class="chart-line chart-line-strategy" style="stroke:#ef6d53" d="${pathFor(strategy)}"></path>
    </svg>
    <div class="chart-legend">
      <span><i class="legend-line legend-line-strategy"></i>网格策略</span>
      <span><i class="legend-line legend-line-benchmark"></i>持有基准</span>
    </div>
  `;
}

// 多线归一图（组合风险 NAV 曲线用）：任意条数系列、点值可 null（断线不连线，分段 M 起点）；
// 所有文本插值过 escapeHtml（chartSvg 同款 XSS 纪律，label 可能含用户数据）。
export interface MultiLineSeries {
  label: string;
  points: (number | null)[];
  style: 'solid' | 'dash';
  color: string;
}

export function multiLineSvg(
  series: MultiLineSeries[],
  opts: { height?: number; ariaLabel?: string; legend?: boolean } = {}
): string {
  const valid = (Array.isArray(series) ? series : []).filter(
    (s) => Array.isArray(s?.points) && s.points.some((p) => p !== null && Number.isFinite(Number(p)))
  );
  const hasCurve = valid.some((s) => s.points.filter((p) => p !== null).length >= 2);
  if (!valid.length || !hasCurve) {
    return '<div class="chart-empty">暂无足够的组合净值数据</div>';
  }
  const width = 640;
  // 收尾硬化 L5：外部传非数 height 会一路流入 viewBox/坐标属性——Number 化+有限性兜底。
  const rawH = Number(opts.height);
  const height = Number.isFinite(rawH) && rawH > 0 ? rawH : 150;
  const pad = { top: 12, right: 12, bottom: 24, left: 12 };
  const innerWidth = width - pad.left - pad.right;
  const innerHeight = height - pad.top - pad.bottom;
  const maxLen = Math.max(...valid.map((s) => s.points.length));
  const xSpan = Math.max(maxLen - 1, 1);
  const flat = valid.flatMap((s) => s.points.filter((p): p is number => p !== null).map(Number));
  const min = Math.min(...flat);
  const max = Math.max(...flat);
  const range = max - min || 1;
  const paths = valid
    .map((s) => {
      // null 断线：连续非空段各成一条子路径（段首 M，段内 L），互不连线。
      const segments: string[] = [];
      let current: string[] = [];
      s.points.forEach((raw, index) => {
        if (raw === null || !Number.isFinite(Number(raw))) {
          if (current.length) segments.push(current.join(' '));
          current = [];
          return;
        }
        const x = pad.left + (index / xSpan) * innerWidth;
        const y = pad.top + (1 - (Number(raw) - min) / range) * innerHeight;
        current.push(`${current.length ? 'L' : 'M'} ${x.toFixed(1)} ${y.toFixed(1)}`);
      });
      if (current.length) segments.push(current.join(' '));
      const dash = s.style === 'dash' ? ' stroke-dasharray="4 3"' : '';
      return `<path class="chart-line multi-line-path" style="stroke:${escapeHtml(s.color)}"${dash} d="${segments.join(' ')}"></path>`;
    })
    .join('');
  const grid = [0.25, 0.5, 0.75]
    .map((ratio) => {
      const y = pad.top + innerHeight * ratio;
      return `<line class="chart-grid-line" x1="${pad.left}" y1="${y.toFixed(1)}" x2="${width - pad.right}" y2="${y.toFixed(1)}"></line>`;
    })
    .join('');
  const label = escapeHtml(opts.ariaLabel ?? '组合净值多线对比');
  const legend =
    opts.legend === false
      ? ''
      : `<div class="chart-legend">${valid
          .map(
            (s) =>
              `<span><i class="legend-line multi-line-legend" style="border-color:${escapeHtml(s.color)}${s.style === 'dash' ? ';border-top-style:dashed' : ''}"></i>${escapeHtml(s.label)}</span>`
          )
          .join('')}</div>`;
  return `
    <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${label}">
      <title>${label}</title>
      ${grid}
      ${paths}
    </svg>
    ${legend}
  `;
}
