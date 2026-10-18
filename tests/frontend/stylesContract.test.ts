/**
 * 滚动锁 CSS 契约（spec §6.2 / 本批 `4bc6606` 修复的守卫）。
 *
 * 本批唯一的产品修复是一处 CSS 声明（`body.overlay-open .view-panel.is-active { overflow: hidden !important }`），
 * 其证明不能只留在 gitignored 的 `visual/` 证据里 —— 这里直接读 `frontend/src/styles.css` 建契约。
 * 手法照 `tests/frontend/lucideIcons.test.ts`（node `fs` 扫源码）。
 *
 * 容忍格式：先剥注释、把全部空白折叠为单个空格，再按**选择器文本**（而非行号）匹配规则块。
 */
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';

const STYLES_PATH = resolve(dirname(fileURLToPath(import.meta.url)), '../../frontend/src/styles.css');

/** 剥注释 + 折叠空白 → 单行化，使规则匹配与排版无关。 */
function flatten(css: string): string {
  return css
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
}

/** 取所有「选择器列表中恰含 `selector`」的规则块声明体（归一化后）。 */
function ruleBlocks(css: string, selector: string): string[] {
  const flat = flatten(css);
  const target = selector.replace(/\s+/g, ' ').trim();
  const blocks: string[] = [];
  const rule = /([^{}]+)\{([^{}]*)\}/g;
  for (const match of flat.matchAll(rule)) {
    const selectors = match[1].split(',').map((s) => s.trim());
    if (selectors.includes(target)) blocks.push(match[2].trim());
  }
  return blocks;
}

/**
 * 极简特异性 [id, class+属性+伪类, 元素]（伪元素不计）。
 * 锁规则 `body.overlay-open .view-panel.is-active` → [0,3,1]（.overlay-open/.view-panel/.is-active 三 + body）
 * 竞争规则 `.screener-view` → [0,1,0]（单类）
 */
function specificity(selector: string): [number, number, number] {
  const ids = (selector.match(/#[\w-]+/g) ?? []).length;
  const classes =
    (selector.match(/\.[\w-]+/g) ?? []).length +
    (selector.match(/\[[^\]]*\]/g) ?? []).length +
    (selector.match(/(?<!:):(?!:)[\w-]+/g) ?? []).length;
  const elements = (selector.match(/(?:^|[\s>+~])[a-zA-Z][\w-]*/g) ?? []).length;
  return [ids, classes, elements];
}

/** 字典序比较两项特异性：a 更强 → >0。 */
function compareSpec(a: [number, number, number], b: [number, number, number]): number {
  for (let i = 0; i < 3; i += 1) {
    if (a[i] !== b[i]) return a[i] - b[i];
  }
  return 0;
}

describe('滚动锁 CSS 契约（styles.css）', () => {
  const css = readFileSync(STYLES_PATH, 'utf8');

  it('锁规则存在且声明 overflow: hidden !important', () => {
    const blocks = ruleBlocks(css, 'body.overlay-open .view-panel.is-active');
    expect(blocks.length).toBeGreaterThan(0);
    expect(blocks.some((body) => /overflow:\s*hidden\s*!important/.test(body))).toBe(true);
  });

  it('竞争规则 .screener-view 仍声明 overflow: auto !important（证明二者同为 !important）', () => {
    const blocks = ruleBlocks(css, '.screener-view');
    expect(blocks.some((body) => /overflow:\s*auto\s*!important/.test(body))).toBe(true);
  });

  it('锁选择器特异性严格大于 .screener-view（同 !important 下由特异性裁决）', () => {
    const lockSpec = specificity('body.overlay-open .view-panel.is-active'); // 期望 [0,3,1]
    const screenerSpec = specificity('.screener-view'); // 期望 [0,1,0]
    expect(lockSpec).toEqual([0, 3, 1]);
    expect(screenerSpec).toEqual([0, 1, 0]);
    expect(compareSpec(lockSpec, screenerSpec)).toBeGreaterThan(0);
  });
});
