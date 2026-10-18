import { beforeEach, describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import { nextTick } from 'vue';
import { createPinia, setActivePinia } from 'pinia';

// renderIcons() 在 onMounted 时调用 createIcons 扫描 DOM，测试中替换为 no-op。
vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));

import ViewMonitor from '@/views/ViewMonitor.vue';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';

// 回归：盯盘开关与监控标的数量必须跟随 store 更新（曾因不解构 ref 的 storeToRefs 而冻结）。
describe('盯盘开关与监控标的（store 响应性）', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  function seed() {
    const workspace = useWorkspaceStore();
    workspace.watchlistCodes = ['600519'];
    workspace.monitorEnabled = true;
    return { workspace, quotes: useQuotesStore() };
  }

  it('点击开关轨道翻转 workspace.monitorEnabled 并同步状态标签', async () => {
    const { workspace, quotes } = seed();
    const wrapper = mount(ViewMonitor);
    expect(quotes.hasWatchTargets).toBe(true);
    expect(wrapper.find('.monitor-toggle-wrap .toggle-label').text()).toBe('盯盘已开启');
    // 真实浏览器点击可视轨道：label 激活切换勾选态并派发 change（jsdom 只切换勾选态、不派发 change，故补发还原浏览器行为）
    const track = wrapper.find('.monitor-toggle-wrap .toggle-track');
    await track.trigger('click');
    expect((wrapper.find('.monitor-toggle-wrap input').element as HTMLInputElement).checked).toBe(false);
    await wrapper.find('.monitor-toggle-wrap input').trigger('change');
    expect(workspace.monitorEnabled).toBe(false);
    expect(quotes.monitorStatusLabel).toBe('盯盘已暂停');
    expect(wrapper.find('.monitor-toggle-wrap .toggle-label').text()).toBe('盯盘已暂停');
    wrapper.unmount();
  });

  it('挂载后替换 watchlistCodes，监控标的数量随渲染更新', async () => {
    const { workspace } = seed();
    const wrapper = mount(ViewMonitor);
    const count = () => wrapper.findAll('.monitor-stat strong')[0].text();
    expect(count()).toBe('1');
    workspace.watchlistCodes = ['600519', '000001', '300750'];
    await nextTick();
    expect(count()).toBe('3');
    wrapper.unmount();
  });
});
