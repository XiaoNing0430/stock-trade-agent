import { test } from 'vitest';
import assert from 'node:assert/strict';
import { PRESETS, NAV_ITEMS, VIEW_META, SETTINGS_TABS, STRATEGY_TYPES, STRATEGY_SCHEMAS } from '@/modules/constants';

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

test('STRATEGY_TYPES 包含八种策略', () => {
  const ids = STRATEGY_TYPES.map((item) => item.id);
  assert.deepEqual(ids, ['grid', 'ma_cross', 'dca', 'macd', 'bollinger', 'donchian', 'momentum', 'multi_factor']);
  for (const item of STRATEGY_TYPES) {
    assert.equal(typeof item.label, 'string');
    assert.equal(typeof item.description, 'string');
  }
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
