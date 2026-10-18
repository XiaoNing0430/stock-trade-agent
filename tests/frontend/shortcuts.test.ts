import { describe, expect, it } from 'vitest';
import { shortcutFor, shortcutForView, isTypingTarget, helpOpen, toggleHelp } from '@/modules/shortcuts';

function key(k: string, init: KeyboardEventInit = {}) {
  return new KeyboardEvent('keydown', { key: k, bubbles: true, cancelable: true, ...init });
}
const ctx = { overlayOpen: false, helpOpen: false };

describe('shortcuts 键表与抑制', () => {
  it('数字键映射 7 个视图（顺序同 NAV_ITEMS）', () => {
    expect(shortcutFor(key('7'), ctx)).toEqual({ type: 'view', view: 'settings' });
    expect(shortcutFor(key('1'), ctx)).toEqual({ type: 'view', view: 'overview' });
    expect(shortcutFor(key('0'), ctx)).toBeNull();
    expect(shortcutForView('portfolio')).toBe('6');
    expect(shortcutForView('stock-detail')).toBeNull();
  });

  it('斜杠聚焦搜索、问号切帮助；Esc 不在此处理', () => {
    expect(shortcutFor(key('/'), ctx)).toEqual({ type: 'search' });
    expect(shortcutFor(key('?'), ctx)).toEqual({ type: 'toggle-help' });
    expect(shortcutFor(key('？'), ctx)).toEqual({ type: 'toggle-help' });
    expect(shortcutFor(key('Escape'), ctx)).toBeNull();
  });

  it('原型链继承键不算视图（constructor / toString 等自有属性判定）', () => {
    expect(shortcutFor(key('constructor'), ctx)).toBeNull();
    expect(shortcutFor(key('toString'), ctx)).toBeNull();
    expect(shortcutFor(key('hasOwnProperty'), ctx)).toBeNull();
  });

  it('抑制矩阵：输入控件内不触发', () => {
    for (const node of [
      document.createElement('input'),
      document.createElement('textarea'),
      document.createElement('select'),
      document.createElement('div'),
    ]) {
      if (node.tagName === 'DIV') node.contentEditable = 'true';
      document.body.appendChild(node);
      expect(isTypingTarget(node)).toBe(true);
      const event = key('2');
      node.dispatchEvent(event);
      expect(event.target).toBe(node);
      expect(shortcutFor(event, ctx)).toBeNull();
      node.remove();
    }
    expect(isTypingTarget(document.body)).toBe(false);
  });

  it('抑制矩阵：修饰键 / 输入法组合中 / 浮层打开', () => {
    expect(shortcutFor(key('2', { ctrlKey: true }), ctx)).toBeNull();
    expect(shortcutFor(key('2', { metaKey: true }), ctx)).toBeNull();
    expect(shortcutFor(key('2', { altKey: true }), ctx)).toBeNull();
    const composing = key('2');
    Object.defineProperty(composing, 'isComposing', { value: true });
    expect(shortcutFor(composing, ctx)).toBeNull();
    expect(shortcutFor(key('2'), { overlayOpen: true, helpOpen: false })).toBeNull();
    expect(shortcutFor(key('/'), { overlayOpen: true, helpOpen: false })).toBeNull();
  });

  it('帮助浮层打开时问号关闭它，其它键仍被浮层抑制', () => {
    expect(shortcutFor(key('?'), { overlayOpen: true, helpOpen: true })).toEqual({ type: 'toggle-help' });
    expect(shortcutFor(key('3'), { overlayOpen: true, helpOpen: true })).toBeNull();
  });

  it('toggleHelp 翻转 helpOpen', () => {
    const before = helpOpen.value;
    toggleHelp();
    expect(helpOpen.value).toBe(!before);
  });
});
