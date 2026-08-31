import { test } from 'vitest';
import assert from 'node:assert/strict';
import { chartSvg, compareChartSvg } from '@/modules/chart';

test('chartSvg 空数组返回空状态', () => {
  assert.equal(chartSvg([], '#3b6fb6', '测试'), '<div class="chart-empty">暂无足够的日线数据</div>');
});

test('chartSvg 单元素返回空状态', () => {
  assert.equal(chartSvg([10], '#3b6fb6', '测试'), '<div class="chart-empty">暂无足够的日线数据</div>');
});

test('chartSvg 两个点生成正常 SVG', () => {
  const svg = chartSvg([10, 20], '#3b6fb6', '测试走势');
  assert.match(svg, /<svg class="chart-svg"/);
  assert.match(svg, /viewBox="0 0 640 150"/);
  assert.match(svg, /class="chart-area"/);
  assert.match(svg, /class="chart-line"/);
  assert.match(svg, /class="chart-dot"/);
  assert.match(svg, /text-anchor="start"/);
  assert.match(svg, /text-anchor="end"/);
});

test('chartSvg 转义注入标签', () => {
  const svg = chartSvg([1, 2], '#3b6fb6', '<script>alert(1)</script>');
  assert.ok(!svg.includes('<script>'), '标签内容必须被转义');
  assert.match(svg, /&lt;script&gt;/);
});

test('chartSvg 多个点生成折线 path', () => {
  const svg = chartSvg([1, 2, 3, 4, 5], '#3b6fb6', '上升序列');
  assert.match(svg, /<path class="chart-line"/);
  // 5 个点应生成 4 段 L 指令（M + 4 L = 5 个 token）
  const line = svg.match(/class="chart-line"[^>]*d="([^"]+)"/)![1];
  assert.equal(line.split(' L ').length, 5);
});

test('chartSvg 平坦序列不除零', () => {
  const svg = chartSvg([5, 5, 5], '#3b6fb6', '平坦');
  assert.match(svg, /<svg class="chart-svg"/);
  assert.ok(!svg.includes('NaN'), '平坦序列不应产生 NaN 坐标');
});

test('compareChartSvg 空结果返回空状态', () => {
  assert.equal(compareChartSvg(null), '<div class="chart-empty">暂无足够的权益数据</div>');
  assert.equal(compareChartSvg({}), '<div class="chart-empty">暂无足够的权益数据</div>');
});

test('compareChartSvg 曲线不足两个点返回空状态', () => {
  const result = { equityCurve: [{ equity: 1 }], benchmarkCurve: [{ equity: 1 }] };
  assert.equal(compareChartSvg(result), '<div class="chart-empty">暂无足够的权益数据</div>');
});

test('compareChartSvg 正常结果生成双曲线对比图', () => {
  const result = {
    equityCurve: [
      { date: '2026-01-01', equity: 1.0 },
      { date: '2026-01-02', equity: 1.05 },
      { date: '2026-01-03', equity: 1.02 },
    ],
    benchmarkCurve: [
      { date: '2026-01-01', equity: 1.0 },
      { date: '2026-01-02', equity: 1.01 },
      { date: '2026-01-03', equity: 1.03 },
    ],
  };
  const svg = compareChartSvg(result);
  assert.match(svg, /<svg class="chart-svg"/);
  assert.match(svg, /chart-line-benchmark/);
  assert.match(svg, /chart-line-strategy/);
  assert.match(svg, /chart-legend/);
  assert.match(svg, /网格策略/);
  assert.match(svg, /持有基准/);
});
