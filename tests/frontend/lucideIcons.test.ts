/** 图标注册表防回归：NAV_ITEMS 每个 kebab 图标必须能在按需注册表中解析（漏注册=侧边栏静默空白）。 */
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
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

const SRC_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '../../frontend/src');

function collectSources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return collectSources(full);
    return entry.name.endsWith('.vue') ? [full] : [];
  });
}

/**
 * 模板里出现的全部图标名：静态 `data-lucide="x"`，以及绑定 `:data-lucide="…'x'…"` 里的字符串字面量
 * （三元链跨多行，故按整份文件匹配）。绑定表达式里的比较操作数（`=== 'dark'`）不是图标名，先剔除。
 */
function collectTemplateIcons(): Map<string, string> {
  const found = new Map<string, string>();
  for (const file of collectSources(SRC_ROOT)) {
    const source = readFileSync(file, 'utf8');
    const relative = file.slice(SRC_ROOT.length + 1).replace(/\\/g, '/');
    for (const match of source.matchAll(/(?<!:)\bdata-lucide="([^">]*)"/g)) {
      if (match[1] && !match[1].includes('{')) found.set(match[1], relative);
    }
    for (const match of source.matchAll(/:data-lucide="([^"]*)"/g)) {
      const expression = match[1].replace(/[!=]==\s*'[^']*'/g, '');
      for (const literal of expression.matchAll(/'([^']+)'/g)) {
        found.set(literal[1], relative);
      }
    }
  }
  return found;
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

  it('模板里出现的每个 data-lucide 图标都已注册（漏注册=图标静默空白）', () => {
    const icons = [...collectTemplateIcons().entries()];
    // 扫描本身要有效：模板里至少应有数十个图标名，否则说明收集逻辑坏了（假通过）。
    expect(icons.length).toBeGreaterThan(20);
    const missing = icons
      .filter(([icon]) => !Object.prototype.hasOwnProperty.call(UI_ICONS, toPascalCase(icon)))
      .map(([icon, file]) => `${icon}（${file}）`);
    expect(missing).toEqual([]);
  });
});
