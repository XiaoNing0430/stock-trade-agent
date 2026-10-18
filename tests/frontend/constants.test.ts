import { test } from 'vitest';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';
import {
  PRESETS,
  NAV_ITEMS,
  NAV_GROUPS,
  APP_VERSION,
  VIEW_META,
  SETTINGS_TABS,
  STRATEGY_TYPES,
  COMPARE_STRATEGY_TYPES,
  STRATEGY_SCHEMAS,
} from '@/modules/constants';

test('PRESETS 结构完整且 id 唯一', () => {
  assert.equal(PRESETS.length, 3);
  for (const preset of PRESETS) {
    assert.equal(typeof preset.name, 'string');
    assert.equal(typeof preset.icon, 'string');
    assert.equal(typeof preset.iconClass, 'string');
    assert.equal(typeof preset.description, 'string');
    assert.equal(typeof preset.filters, 'object');
    assert.ok(preset.name.length > 0);
  }
});

test('NAV_ITEMS 长度与 id 唯一性', () => {
  const ids = NAV_ITEMS.map((item) => item.id);
  assert.equal(new Set(ids).size, ids.length, 'nav id 必须唯一');
  assert.ok(ids.includes('overview'));
  assert.ok(ids.includes('screener'));
  assert.ok(ids.includes('grid'));
  assert.ok(ids.includes('plans'));
  assert.ok(ids.includes('monitor'));
  assert.ok(ids.includes('settings'));
  for (const item of NAV_ITEMS) {
    assert.equal(typeof item.label, 'string');
    assert.equal(typeof item.icon, 'string');
  }
});

test('VIEW_META 覆盖所有视图', () => {
  for (const item of NAV_ITEMS) {
    assert.ok(VIEW_META[item.id], `VIEW_META 缺少视图 ${item.id}`);
    assert.equal(VIEW_META[item.id].length, 2);
  }
  assert.ok(VIEW_META['stock-detail'], '详情视图元数据存在');
});

test('SETTINGS_TABS 结构完整', () => {
  assert.ok(SETTINGS_TABS.length >= 3);
  for (const tab of SETTINGS_TABS) {
    assert.equal(typeof tab.id, 'string');
    assert.equal(typeof tab.label, 'string');
  }
});

test('STRATEGY_TYPES 包含八种回测策略与 compare tab', () => {
  const ids = STRATEGY_TYPES.map((item) => item.id);
  assert.deepEqual(ids, [
    'grid',
    'ma_cross',
    'dca',
    'macd',
    'bollinger',
    'donchian',
    'momentum',
    'multi_factor',
    'compare',
  ]);
  for (const item of STRATEGY_TYPES) {
    assert.equal(typeof item.label, 'string');
    assert.equal(typeof item.description, 'string');
  }
});

test('COMPARE_STRATEGY_TYPES 为不含 compare 的回测策略类型集', () => {
  const ids = COMPARE_STRATEGY_TYPES.map((item) => item.id);
  assert.deepEqual(ids, ['grid', 'ma_cross', 'dca', 'macd', 'bollinger', 'donchian', 'momentum', 'multi_factor']);
  assert.ok(!ids.includes('compare'));
});

test('STRATEGY_SCHEMAS 各类型配置字段结构', () => {
  for (const type of ['ma_cross', 'dca', 'macd', 'bollinger', 'donchian', 'momentum', 'multi_factor']) {
    const schema = STRATEGY_SCHEMAS[type];
    assert.ok(Array.isArray(schema) && schema.length > 0, `${type} 应有配置字段`);
    for (const field of schema) {
      assert.equal(typeof field.key, 'string');
      assert.equal(typeof field.label, 'string');
      assert.ok(['int', 'float'].includes(field.type), `${type}.${field.key} 类型合法`);
      assert.ok(field.default !== undefined, `${type}.${field.key} 应有默认值`);
    }
  }
});

test('NAV_GROUPS 分区顺序与成员覆盖', () => {
  assert.deepEqual(
    NAV_GROUPS.map((group) => group.id),
    ['research', 'validation', 'execution', 'risk', 'system']
  );
  assert.deepEqual(
    NAV_GROUPS.map((group) => group.label),
    ['研究', '验证', '执行', '风控', '系统']
  );
  for (const group of NAV_GROUPS) {
    assert.ok(NAV_ITEMS.filter((item) => item.group === group.id).length > 0, `${group.id} 至少 1 个成员`);
  }
});

test('NAV_ITEMS 具备 shortLabel 与 group，且顺序不变', () => {
  for (const item of NAV_ITEMS) {
    assert.equal(typeof item.shortLabel, 'string');
    assert.ok(item.shortLabel.length > 0);
  }
  assert.deepEqual(
    NAV_ITEMS.map((item) => item.id),
    ['overview', 'screener', 'grid', 'plans', 'monitor', 'portfolio', 'settings'],
    '顺序被 app.ts:97 快捷键契约锁定'
  );
  assert.deepEqual(
    NAV_ITEMS.filter((item) => item.group === null).map((item) => item.id),
    ['overview']
  );
});

test('APP_VERSION 与 package.json 同步', () => {
  // 注意：不可用 `new URL('../../package.json', import.meta.url)`——Vite 的 asset
  // import.meta.url 插件会把它重写成 dev-server 的 http 资源地址，导致 fs 读取报
  // “The URL must be of scheme file”。fileURLToPath 能拿到真实的 file: 路径。
  const pkgPath = resolve(dirname(fileURLToPath(import.meta.url)), '../../package.json');
  const pkg = JSON.parse(readFileSync(pkgPath, 'utf8')) as { version: string };
  assert.equal(APP_VERSION, pkg.version);
});
