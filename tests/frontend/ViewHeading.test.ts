import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

// 真实视图（非 stub）页头的回归守卫：AppShell.test.ts 的 `.section-kicker` 断言因视图全被 stub
// 而恒真，故此处单独挂一个真实视图（ViewScreener）钉住「视图内页头只剩功能控件」。
vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>();
  return { ...actual, requestJson: vi.fn() };
});

import ViewScreener from '@/views/ViewScreener.vue';

describe('视图页头层级（spec §8，真实视图）', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it('页头块只保留 view-heading-actions，无 section-kicker 与装饰性 h2/heading-note', () => {
    const wrapper = mount(ViewScreener);
    const heading = wrapper.find('.view-heading');
    expect(heading.exists()).toBe(true);
    expect(heading.find('.section-kicker').exists()).toBe(false);
    expect(heading.findAll('h2')).toHaveLength(0);
    expect(heading.find('.heading-note').exists()).toBe(false);
    expect(heading.element.children).toHaveLength(1);
    expect(heading.findAll('.view-heading-actions')).toHaveLength(1);
    wrapper.unmount();
  });
});
