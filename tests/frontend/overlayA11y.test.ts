import { beforeEach, describe, expect, it, vi } from 'vitest';
import { defineComponent, h, nextTick, ref, type Ref } from 'vue';
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
    closeOnEsc: { type: Boolean, default: true },
  },
  setup(props) {
    const panel = ref<HTMLElement | null>(null);
    useOverlayA11y({
      id: props.id,
      isOpen: () => props.open,
      panelRef: panel,
      onClose: () => props.onClose(),
      closeOnEsc: props.closeOnEsc,
    });
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

  it('focusableWithin 过滤 display:none 与 inert 元素（spec §11：disabled / display:none / tabindex=-1）', () => {
    const root = document.createElement('div');
    root.innerHTML =
      '<button class="a">A</button>' +
      '<button class="hidden" style="display:none">H</button>' +
      '<button class="inert" inert>I</button>' +
      '<span tabindex="-1">T</span>';
    document.body.appendChild(root);
    expect(focusableWithin(root).map((el) => el.className || el.tagName)).toEqual(['a']);
  });

  it('focusableWithin 过滤祖先子树带 inert 的元素（closest 沿祖链判定）', () => {
    const root = document.createElement('div');
    root.innerHTML =
      '<div inert><button class="ancestor-inert">I</button></div>' +
      '<div><span inert><button class="nested-inert">N</button></span></div>' +
      '<button class="a">A</button>';
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

  it('关闭态挂载的浮层不偷锁（计数幂等）', async () => {
    const a = mount(Harness, { props: { id: 'a', open: true, onClose: vi.fn() }, attachTo: document.body });
    expect(document.body.classList.contains('overlay-open')).toBe(true);
    const b = mount(Harness, { props: { id: 'b', open: false, onClose: vi.fn() }, attachTo: document.body });
    expect(document.body.classList.contains('overlay-open')).toBe(true);
    expect(topOverlayId()).toBe('a');
    await a.setProps({ open: false });
    expect(document.body.classList.contains('overlay-open')).toBe(false);
    a.unmount();
    b.unmount();
  });

  it('同一 Esc 只关栈顶（栈顶先挂载的顺序）', async () => {
    // 真实接线中关闭信号常为同步生效（Pinia store / 局部 ref）；而经 VTU 根组件更新 props
    // 是异步重渲染，无法在同一次 keydown 派发内弹出栈顶。故用同结构的面板 harness + ref 驱动。
    const makeRefHarness = (openState: Ref<boolean>) =>
      defineComponent({
        props: { id: { type: String, required: true }, onClose: { type: Function, required: true } },
        setup(props) {
          const panel = ref<HTMLElement | null>(null);
          useOverlayA11y({
            id: props.id,
            isOpen: () => openState.value,
            panelRef: panel,
            onClose: () => props.onClose(),
          });
          return () =>
            openState.value
              ? h('section', { ref: panel, 'data-testid': `panel-${props.id}` }, [
                  h('button', { class: 'a' }, 'A'),
                  h('button', { class: 'b', disabled: true }, 'B'),
                  h('button', { class: 'c' }, 'C'),
                ])
              : null;
        },
      });
    const bOpen = ref(false);
    const aOpen = ref(true);
    const onCloseA = vi.fn(() => {
      aOpen.value = false;
    });
    const onCloseB = vi.fn(() => {
      bOpen.value = false;
    });
    const b = mount(makeRefHarness(bOpen), { props: { id: 'b', onClose: onCloseB }, attachTo: document.body });
    const a = mount(makeRefHarness(aOpen), { props: { id: 'a', onClose: onCloseA }, attachTo: document.body });
    await nextTick();
    bOpen.value = true;
    await nextTick();
    expect(topOverlayId()).toBe('b');
    press('Escape');
    expect(onCloseB).toHaveBeenCalledTimes(1);
    expect(onCloseA).not.toHaveBeenCalled();
    expect(topOverlayId()).toBe('a');
    a.unmount();
    b.unmount();
  });

  it('closeOnEsc:false 时 Esc 不关闭，但同一浮层的 Tab 焦点陷阱仍生效', async () => {
    const onClose = vi.fn();
    const wrapper = mount(Harness, {
      props: { id: 'noesc', open: true, onClose, closeOnEsc: false },
      attachTo: document.body,
    });
    await nextTick();
    press('Escape');
    expect(onClose).not.toHaveBeenCalled();
    // 同一实例：Tab 仍应回绕（末 → 首），证明关不掉 Esc 不影响陷阱接线
    (document.querySelector('.c') as HTMLElement).focus();
    press('Tab');
    expect(document.activeElement?.className).toBe('a');
    wrapper.unmount();
  });

  it('[data-autofocus] 元素优先于 DOM 首个可聚焦元素', async () => {
    const AutofocusHarness = defineComponent({
      setup() {
        const panel = ref<HTMLElement | null>(null);
        const open = ref(true);
        useOverlayA11y({ id: 'af', isOpen: () => open.value, panelRef: panel, onClose: () => {} });
        return () =>
          open.value
            ? h('section', { ref: panel, 'data-testid': 'panel-af' }, [
                h('button', { class: 'first' }, '1'),
                h('button', { class: 'preferred', 'data-autofocus': '' }, '2'),
              ])
            : null;
      },
    });
    const wrapper = mount(AutofocusHarness, { attachTo: document.body });
    await nextTick();
    expect(document.activeElement?.className).toBe('preferred');
    wrapper.unmount();
  });

  it('面板无可聚焦子元素：面板自身补 tabindex=-1 并接管焦点', async () => {
    const EmptyPanelHarness = defineComponent({
      setup() {
        const panel = ref<HTMLElement | null>(null);
        useOverlayA11y({ id: 'empty', isOpen: () => true, panelRef: panel, onClose: () => {} });
        return () => h('section', { ref: panel, 'data-testid': 'panel-empty' }, [h('span', '不可聚焦')]);
      },
    });
    const wrapper = mount(EmptyPanelHarness, { attachTo: document.body });
    await nextTick();
    const panelEl = document.querySelector('[data-testid="panel-empty"]') as HTMLElement;
    expect(panelEl.getAttribute('tabindex')).toBe('-1');
    expect(document.activeElement).toBe(panelEl);
    wrapper.unmount();
  });

  it('归还目标已脱离 DOM（isConnected=false）时跳过聚焦（不调用 focus）且不抛错', async () => {
    const onClose = vi.fn();
    const trigger = document.getElementById('trigger') as HTMLButtonElement;
    trigger.focus();
    const wrapper = mount(Harness, { props: { id: 'x', open: false, onClose }, attachTo: document.body });
    await wrapper.setProps({ open: true });
    await nextTick();
    // restoreTarget（open() 处捕获的 document.activeElement）此刻仍指向 trigger，但 trigger 已断开
    trigger.remove();
    // 断言「focus 是否被调用」而非「focus 的效果」：jsdom 对已断开节点调用 focus()
    // 是静默 no-op，只比较 activeElement 在守卫缺失时同样通过（用例无力）。
    const focusSpy = vi.spyOn(trigger, 'focus');
    await wrapper.setProps({ open: false });
    await nextTick(); // 延迟归还：守卫 `if (target.isConnected && …)` 生效即不触达 focus
    expect(focusSpy).not.toHaveBeenCalled();
    expect(document.activeElement?.closest('[data-testid="panel-x"]')).toBeNull(); // 焦点未被移入浮层
    wrapper.unmount();
  });

  it('栈顶但面板 ref 为空时 Tab 被吞掉（defaultPrevented），焦点不落回背景页', async () => {
    const NoPanelHarness = defineComponent({
      setup() {
        const panel = ref<HTMLElement | null>(null);
        useOverlayA11y({ id: 'nopanel', isOpen: () => true, panelRef: panel, onClose: () => {} });
        return () => h('span', '面板尚未挂载');
      },
    });
    const wrapper = mount(NoPanelHarness, { attachTo: document.body });
    await nextTick();
    expect(topOverlayId()).toBe('nopanel');
    const event = new KeyboardEvent('keydown', { key: 'Tab', bubbles: true, cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    wrapper.unmount();
  });

  it('同一 tick 内开→关：延迟自动聚焦不得把焦点抢回面板', async () => {
    const trigger = document.getElementById('trigger') as HTMLButtonElement;
    trigger.focus();
    const openRef = ref(false);
    // 面板常驻 DOM（v-show 风格）：关闭后 panelRef 仍非空，守卫缺失时延迟回调会抢回焦点
    const PersistentHarness = defineComponent({
      setup() {
        const panel = ref<HTMLElement | null>(null);
        useOverlayA11y({ id: 'persist', isOpen: () => openRef.value, panelRef: panel, onClose: () => {} });
        return () => h('section', { ref: panel, 'data-testid': 'panel-persist' }, [h('button', { class: 'p1' }, 'P')]);
      },
    });
    const wrapper = mount(PersistentHarness, { attachTo: document.body });
    const p1 = document.querySelector('.p1') as HTMLButtonElement;
    const focusSpy = vi.spyOn(p1, 'focus');
    openRef.value = true; // 同步打开：排队延迟聚焦
    openRef.value = false; // 同 tick 立即关闭
    await nextTick();
    expect(focusSpy).not.toHaveBeenCalled(); // 守卫 `if (!opened) return` 生效即不触达面板
    expect(document.activeElement?.closest('[data-testid="panel-persist"]')).toBeNull();
    wrapper.unmount();
  });
});
