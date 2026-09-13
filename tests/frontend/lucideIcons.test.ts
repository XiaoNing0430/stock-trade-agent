/** 图标注册表防回归：NAV_ITEMS 每个 kebab 图标必须能在按需注册表中解析（漏注册=侧边栏静默空白）。 */
import { NAV_ITEMS } from '@/modules/constants';
import { UI_ICONS } from '@/modules/lucideIcons';
import { describe, expect, it } from 'vitest';

/** 对齐 lucide createIcons 的 kebab→PascalCase 解析（数字段保持原样，grid-3x3 → Grid3x3）。 */
function toPascalCase(name: string): string {
  return name
    .split('-')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join('');
}

describe('lucideIcons 按需注册表', () => {
  it.each(NAV_ITEMS.map((item) => [item.id, item.icon] as const))('%s 的图标 %s 已注册', (_id, icon) => {
    expect(UI_ICONS).toHaveProperty(toPascalCase(icon));
  });

  it('组合风险视图模板图标已注册（chart-line/chevron-down/refresh-cw）', () => {
    for (const icon of ['chart-line', 'chevron-down', 'refresh-cw']) {
      expect(UI_ICONS).toHaveProperty(toPascalCase(icon));
    }
  });
});
