import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { durationFor, resetToasts, showToast, toastKey } from '@/modules/toastQueue';

function region() {
  return document.getElementById('toast-region') as HTMLElement;
}

// 到期后节点先挂 .toast-leaving 做 120ms 淡出才真正摘除（实现 LEAVE_MS=120）。
// 断言「已消失」需多等一个淡出窗；130ms 与上限/点击用例同口径。
const LEAVE_GRACE_MS = 130;

beforeEach(() => {
  vi.useFakeTimers();
  document.body.innerHTML = '<div id="toast-region" aria-live="polite"></div>';
  resetToasts();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('toastQueue 策略', () => {
  it('时长：error 6s，其余 3.2s', () => {
    expect(durationFor('error')).toBe(6000);
    expect(durationFor('success')).toBe(3200);
  });

  it('同文案去重：不新增节点，重置计时', () => {
    showToast('同步失败', 'error');
    showToast('同步失败', 'error');
    expect(region().children).toHaveLength(1);
    vi.advanceTimersByTime(5999);
    expect(region().children).toHaveLength(1);
    vi.advanceTimersByTime(1 + LEAVE_GRACE_MS);
    expect(region().children).toHaveLength(0);
  });

  it('同文案去重时重放高亮（.toast-pulse，spec §8.2-1）', () => {
    showToast('同步失败', 'error');
    const node = region().firstElementChild as HTMLElement;
    expect(node.classList.contains('toast-pulse')).toBe(false);
    showToast('同步失败', 'error');
    expect(region().children).toHaveLength(1);
    expect(node.classList.contains('toast-pulse')).toBe(true);
  });

  it('不同 tone 同文案不去重', () => {
    showToast('已保存', 'success');
    showToast('已保存', 'error');
    expect(region().children).toHaveLength(2);
    expect(toastKey('error', '已保存')).not.toBe(toastKey('success', '已保存'));
  });

  it('上限 3：超出先淘最旧', () => {
    showToast('一');
    showToast('二');
    showToast('三');
    showToast('四');
    vi.advanceTimersByTime(130);
    // 字面 3（不用导入的 TOAST_CAP）——上限若被改成 1/2 该断言必红
    expect(region().children).toHaveLength(3);
    expect(region().textContent).toContain('四');
    expect(region().textContent).not.toContain('一');
  });

  it('点击整条关闭', () => {
    showToast('可关闭');
    region().firstElementChild!.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    vi.advanceTimersByTime(130);
    expect(region().children).toHaveLength(0);
  });

  it('悬停暂停、移出后重新计时', () => {
    showToast('暂停我');
    const node = region().firstElementChild as HTMLElement;
    node.dispatchEvent(new MouseEvent('mouseenter'));
    vi.advanceTimersByTime(10000);
    expect(region().children).toHaveLength(1);
    node.dispatchEvent(new MouseEvent('mouseleave'));
    vi.advanceTimersByTime(3200 + LEAVE_GRACE_MS);
    expect(region().children).toHaveLength(0);
  });

  it('聚焦暂停、失焦后重新计时（focusin/focusout）', () => {
    showToast('聚焦我');
    const node = region().firstElementChild as HTMLElement;
    node.dispatchEvent(new FocusEvent('focusin'));
    vi.advanceTimersByTime(10000);
    expect(region().children).toHaveLength(1);
    node.dispatchEvent(new FocusEvent('focusout'));
    vi.advanceTimersByTime(3200 + LEAVE_GRACE_MS);
    expect(region().children).toHaveLength(0);
  });

  it('resetToasts 清空已挂节点与内部队列（同文案随后可再次入队）', () => {
    showToast('甲');
    showToast('乙');
    expect(region().children).toHaveLength(2);
    resetToasts();
    expect(region().children).toHaveLength(0);
    // 队列已清：同文案不再命中去重，可重新入队
    showToast('甲');
    expect(region().children).toHaveLength(1);
    expect(region().textContent).toContain('甲');
    // 旧计时器已被清除，推进时间不应报错或残留
    vi.advanceTimersByTime(3200 + LEAVE_GRACE_MS);
    expect(region().children).toHaveLength(0);
  });

  it('关闭按钮带中文 aria-label，且 renderIcons 被调用', () => {
    const renderIcons = vi.fn();
    showToast('带图标', 'success', { renderIcons });
    const close = region().querySelector('.toast-close') as HTMLElement;
    expect(close.getAttribute('aria-label')).toBe('关闭提示');
    expect(renderIcons).toHaveBeenCalled();
  });

  it('到期先挂 .toast-leaving、淡出窗内仍在 DOM，窗满才摘除（spec §8.2 的 120ms）', () => {
    showToast('淡出我', 'success');
    const node = region().firstElementChild as HTMLElement;

    vi.advanceTimersByTime(3200);
    // 时长刚满：节点必须仍在 DOM，且已进入淡出态（LEAVE_MS 若被清零，此处已无子节点）
    expect(region().children).toHaveLength(1);
    expect(region().firstElementChild).toBe(node);
    expect(node.classList.contains('toast-leaving')).toBe(true);

    // 淡出窗未满（119ms）时不得摘除（LEAVE_MS 若被改小，此处必红）
    vi.advanceTimersByTime(119);
    expect(region().children).toHaveLength(1);

    vi.advanceTimersByTime(1);
    expect(region().children).toHaveLength(0);
  });

  it('同文案去重会重置整段计时，而非仅重新入队', () => {
    showToast('同步失败', 'error');
    const node = region().firstElementChild as HTMLElement;

    // 未到期前再弹一次同文案（t=5900），触发去重重置
    vi.advanceTimersByTime(5900);
    expect(region().children).toHaveLength(1);
    expect(node.classList.contains('toast-leaving')).toBe(false);
    showToast('同步失败', 'error');
    expect(region().children).toHaveLength(1);
    expect(region().firstElementChild).toBe(node);

    // 推进越过「原到期点」（t=6000，即二次弹出后 100ms）：若计时未重置，节点早已淡出消失
    vi.advanceTimersByTime(5999); // t=11899
    expect(region().children).toHaveLength(1);
    expect(node.classList.contains('toast-leaving')).toBe(false);

    // 二次弹出起的满 6000ms 才到期（t=11900）
    vi.advanceTimersByTime(1);
    expect(node.classList.contains('toast-leaving')).toBe(true);
    vi.advanceTimersByTime(LEAVE_GRACE_MS);
    expect(region().children).toHaveLength(0);
  });

  it('淡出窗内突发 5 条：任一时刻 DOM 子节点 ≤3，且淘汰的是最旧（spec §8.2 子节点计上限）', () => {
    for (const text of ['一', '二', '三', '四', '五']) {
      showToast(text);
      // 每次调用返回后子节点数必须守住上限（旧实现按 entries 计，会在淡出窗内堆到 4–5）
      expect(region().children.length).toBeLessThanOrEqual(3);
    }
    expect(region().children).toHaveLength(3);
    // 存活的是最新三条，最旧两条被淘汰
    expect(region().textContent).toContain('三');
    expect(region().textContent).toContain('四');
    expect(region().textContent).toContain('五');
    expect(region().textContent).not.toContain('一');
    expect(region().textContent).not.toContain('二');
  });

  it('直接点击 .toast-close 按钮只关闭该条，其余不受影响', () => {
    showToast('甲');
    showToast('乙');
    const first = region().children[0] as HTMLElement;
    const close = first.querySelector('.toast-close') as HTMLElement;
    // 真实点击落在按钮上（唯一监听器挂在整行，事件冒泡到行）——不经由直接点击整行
    close.dispatchEvent(new MouseEvent('click', { bubbles: true }));

    vi.advanceTimersByTime(LEAVE_GRACE_MS);
    expect(region().children).toHaveLength(1);
    expect(region().textContent).toContain('乙');
    expect(region().textContent).not.toContain('甲');
  });

  it('上限淘汰遇到「已在淡出的孤儿」子节点：不抛错、立即摘除且不留残节点', () => {
    showToast('甲');
    // 自然到期：条目已出队，节点仍在 120ms 淡出窗内（无对应条目）
    vi.advanceTimersByTime(3200);
    expect(region().children).toHaveLength(1);
    expect(region().firstElementChild!.classList.contains('toast-leaving')).toBe(true);

    expect(() => {
      showToast('乙');
      showToast('丙');
      showToast('丁');
    }).not.toThrow();

    // 孤儿「甲」被立即摘除，突发窗口内仍守住上限
    expect(region().children.length).toBeLessThanOrEqual(3);
    expect(region().textContent).not.toContain('甲');

    // 推进到全部时长 + 淡出结束：无残留
    vi.advanceTimersByTime(3200 + LEAVE_GRACE_MS);
    expect(region().children).toHaveLength(0);
  });
});
