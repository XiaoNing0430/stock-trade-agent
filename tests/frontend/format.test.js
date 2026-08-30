import test from 'node:test';
import assert from 'node:assert/strict';
import {
  formatNumber,
  formatPct,
  formatTime,
  formatDateLabel,
  formatAmount,
  formatMoney,
  formatNullable,
  formatPctNullable,
  trendClass,
  escapeHtml,
  validityExpiry,
} from '../../frontend/modules/format.js';

test('formatNumber 正常值保留指定位数', () => {
  assert.equal(formatNumber(1234.567), '1,234.57');
  assert.equal(formatNumber(1234.567, 0), '1,235');
  assert.equal(formatNumber(0), '0.00');
  assert.equal(formatNumber(-5.5), '-5.50');
});

test('formatNumber 边缘值返回占位符', () => {
  assert.equal(formatNumber(null), '--');
  assert.equal(formatNumber(undefined), '--');
  assert.equal(formatNumber(NaN), '--');
});

test('formatPct 正负与占位符', () => {
  assert.equal(formatPct(10), '+10.00%');
  assert.equal(formatPct(-5.123), '-5.12%');
  assert.equal(formatPct(0), '+0.00%');
  assert.equal(formatPct(null), '--');
  assert.equal(formatPct(undefined), '--');
});

test('formatTime 有效时间戳与占位符', () => {
  const ts = new Date(2026, 0, 1, 9, 5, 7).getTime();
  assert.equal(formatTime(ts), '09:05:07');
  assert.equal(formatTime(0), '--:--:--');
  assert.equal(formatTime(undefined), '--:--:--');
});

test('formatDateLabel 委托 formatTime 并处理无效值', () => {
  const ts = new Date(2026, 0, 1, 8, 0, 0).getTime();
  assert.equal(formatDateLabel(ts), '更新于 08:00:00');
  assert.equal(formatDateLabel(0), '尚未更新');
  assert.equal(formatDateLabel(null), '尚未更新');
});

test('formatAmount 亿/万/元三档', () => {
  assert.equal(formatAmount(1000000000), '10.00 亿');
  assert.equal(formatAmount(50000000), '5000.00 万');
  assert.equal(formatAmount(1234), '1,234 元');
  assert.equal(formatAmount(0), '0 元');
  assert.equal(formatAmount(null), '--');
});

test('formatMoney 货币格式', () => {
  assert.equal(formatMoney(1000000), '¥1,000,000');
  assert.equal(formatMoney(0), '¥0');
  assert.equal(formatMoney(null), '¥0');
  assert.equal(formatMoney(undefined), '¥0');
});

test('formatNullable 与 formatPctNullable 委托基础函数', () => {
  assert.equal(formatNullable(1234.567), '1,234.57');
  assert.equal(formatNullable(null), '--');
  assert.equal(formatPctNullable(10), '+10.00%');
  assert.equal(formatPctNullable(undefined), '--');
});

test('trendClass 分涨跌平三类', () => {
  assert.equal(trendClass(1.2), 'trend-up');
  assert.equal(trendClass(-0.5), 'trend-down');
  assert.equal(trendClass(0), 'trend-up');
  assert.equal(trendClass(null), 'trend-flat');
  assert.equal(trendClass(undefined), 'trend-flat');
});

test('escapeHtml 转义全部特殊字符', () => {
  assert.equal(escapeHtml('&<>"\''), '&amp;&lt;&gt;&quot;&#39;');
  assert.equal(escapeHtml('普通文本'), '普通文本');
  assert.equal(escapeHtml(''), '');
  assert.equal(escapeHtml(undefined), '');
});

test('validityExpiry 今日/本周/本月/未知', () => {
  const ts = new Date(2026, 0, 15, 12, 0, 0).getTime(); // 2026-01-15 周四
  const end = validityExpiry(ts, '今日');
  assert.equal(new Date(end).getHours(), 23);
  assert.equal(new Date(end).getMinutes(), 59);
  assert.equal(new Date(end).getSeconds(), 59);
  assert.equal(new Date(end).getDate(), 15);

  const week = validityExpiry(ts, '本周内');
  assert.equal(new Date(week).getDay(), 0); // 周日末
  assert.equal(new Date(week).getDate(), 18); // 2026-01-15 周四 → 周日 18 日

  const month = validityExpiry(ts, '本月内');
  assert.equal(new Date(month).getMonth(), 0); // 1 月
  assert.equal(new Date(month).getDate(), 31); // 月末

  const unknown = validityExpiry(ts, '自定义');
  assert.equal(new Date(unknown).getDate(), 15); // 回落当日末

  assert.equal(validityExpiry(0, '今日'), null);
});
