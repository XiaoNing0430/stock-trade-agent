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
});
