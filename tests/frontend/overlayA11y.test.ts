import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick, ref } from 'vue';
import { mount } from '@vue/test-utils';
import {
  focusableWithin,
  isAnyOverlayOpen,
  isOverlayOpen,
  nextFocusTarget,
  resetOverlayStack,
  topOverlayId,
  useOverlayA11y,
} from '@/modules/overlayA11y';

const Harness = defineComponent({
  props: {
    id: { type: String, required: true },
    open: { type: Boolean, required: true },
    onClose: { type: Function, required: true },
  },
  setup(props) {
    const panel = ref<HTMLElement | null>(null);
    useOverlayA11y({ id: props.id, isOpen: () => props.open, panelRef: panel, onClose: () => props.onClose() });
    return () =>
      props.open
        ? h('section', { ref: panel, 'data-testid': `panel-${props.id}` }, [
            h('button', { class: 'a' }, 'A'),
            h('button', { class: 'b', disabled: true }, 'B'),
            h('button', { class: 'c' }, 'C'),
          ])
        : null;
  },
});

function press(key: string, shiftKey = false) {
  window.dispatchEvent(new KeyboardEvent('keydown', { key, shiftKey, bubbles: true, cancelable: true }));
}

beforeEach(() => {
  resetOverlayStack();
  document.body.className = '';
  document.body.innerHTML = '<button id="trigger">触发</button>';
});

describe('overlayA11y 纯函数', () => {
  it('focusableWithin 过滤 disabled 与 tabindex="-1"', () => {
    const root = document.createElement('div');
    root.innerHTML = '<button class="a">A</button><button disabled>B</button><span tabindex="-1">C</span>';
    document.body.appendChild(root);
    expect(focusableWithin(root).map((el) => el.className || el.tagName)).toEqual(['a']);
  });

  it('nextFocusTarget 空集返回 null，越界回绕', () => {
    const a = document.createElement('button');
    const b = document.createElement('button');
    expect(nextFocusTarget([], null, false)).toBeNull();
    expect(nextFocusTarget([a, b], a, true)).toBe(b);
    expect(nextFocusTarget([a, b], b, false)).toBe(a);
  });
});

describe('useOverlayA11y 行为', () => {
  it('打开时焦点进面板第一个可聚焦元素；关闭后归还触发者', async () => {
    const onClose = vi.fn();
    const trigger = document.getElementById('trigger') as HTMLButtonElement;
    trigger.focus();
    const wrapper = mount(Harness, { props: { id: 'x', open: false, onClose }, attachTo: document.body });
    await wrapper.setProps({ open: true });
    await nextTick();
    expect(document.activeElement?.className).toBe('a');
    await wrapper.setProps({ open: false });
    await nextTick();
    expect(document.activeElement).toBe(trigger);
    wrapper.unmount();
  });

  it('Tab 在面板内回绕（末→首、首→末）', async () => {
    const wrapper = mount(Harness, { props: { id: 'x', open: true, onClose: vi.fn() }, attachTo: document.body });
    await nextTick();
    (document.querySelector('.c') as HTMLElement).focus();
    press('Tab');
    expect(document.activeElement?.className).toBe('a');
    press('Tab', true);
    expect(document.activeElement?.className).toBe('c');
    wrapper.unmount();
  });

  it('Esc 只由栈顶浮层响应并调用 onClose', async () => {
    const onCloseTop = vi.fn();
    const onCloseBottom = vi.fn();
    const bottom = mount(Harness, {
      props: { id: 'bottom', open: true, onClose: onCloseBottom },
      attachTo: document.body,
    });
    const top = mount(Harness, { props: { id: 'top', open: true, onClose: onCloseTop }, attachTo: document.body });
    expect(topOverlayId()).toBe('top');
    press('Escape');
    expect(onCloseTop).toHaveBeenCalledTimes(1);
    expect(onCloseBottom).not.toHaveBeenCalled();
    bottom.unmount();
    top.unmount();
  });

  it('滚动锁计数幂等：两个浮层全关才摘 body.overlay-open', async () => {
    const a = mount(Harness, { props: { id: 'a', open: true, onClose: vi.fn() }, attachTo: document.body });
    const b = mount(Harness, { props: { id: 'b', open: true, onClose: vi.fn() }, attachTo: document.body });
    expect(document.body.classList.contains('overlay-open')).toBe(true);
    expect(isAnyOverlayOpen()).toBe(true);
    await a.setProps({ open: false });
    expect(document.body.classList.contains('overlay-open')).toBe(true);
    await b.setProps({ open: false });
    expect(document.body.classList.contains('overlay-open')).toBe(false);
    expect(isOverlayOpen('a')).toBe(false);
    a.unmount();
    b.unmount();
  });
});
