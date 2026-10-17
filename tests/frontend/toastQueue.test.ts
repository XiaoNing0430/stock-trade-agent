import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';
import { TOAST_CAP, durationFor, resetToasts, showToast, toastKey } from '@/modules/toastQueue';

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
    expect(region().children).toHaveLength(TOAST_CAP);
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

  it('关闭按钮带中文 aria-label，且 renderIcons 被调用', () => {
    const renderIcons = vi.fn();
    showToast('带图标', 'success', { renderIcons });
    const close = region().querySelector('.toast-close') as HTMLElement;
    expect(close.getAttribute('aria-label')).toBe('关闭提示');
    expect(renderIcons).toHaveBeenCalled();
  });
});
