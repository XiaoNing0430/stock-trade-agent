import { beforeEach, describe, expect, it, vi } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';

vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));

import ShortcutHelpDialog from '@/components/ShortcutHelpDialog.vue';
import { helpOpen } from '@/modules/shortcuts';
import { resetOverlayStack } from '@/modules/overlayA11y';

beforeEach(() => {
  setActivePinia(createPinia());
  resetOverlayStack();
  document.body.innerHTML = '';
  helpOpen.value = true;
});

describe('快捷键帮助浮层（spec §9.3）', () => {
  it('列出全部键位并声明 dialog 语义', () => {
    const wrapper = mount(ShortcutHelpDialog, { attachTo: document.body });
    const panel = wrapper.find('.dialog-panel');
    expect(panel.attributes('role')).toBe('dialog');
    expect(panel.attributes('aria-modal')).toBe('true');
    expect(panel.attributes('aria-label')).toBe('键盘快捷键');
    for (const text of ['聚焦搜索', '打开 / 关闭帮助', '切换到个人中心']) {
      expect(panel.text()).toContain(text);
    }
    wrapper.unmount();
    helpOpen.value = false;
  });

  it('覆盖 spec §9.3 的 Enter 提交语义行', () => {
    const wrapper = mount(ShortcutHelpDialog, { attachTo: document.body });
    const rows = wrapper.findAll('.shortcut-table tr');
    const enterRow = rows.find((row) => row.find('kbd').text() === 'Enter');
    expect(enterRow).toBeTruthy();
    expect(enterRow!.text()).toContain('搜索框');
    expect(enterRow!.text()).toContain('回测参数框');
    expect(enterRow!.text()).toContain('提交');
    wrapper.unmount();
    helpOpen.value = false;
  });

  it('Esc 关闭（写回 helpOpen=false）', async () => {
    const wrapper = mount(ShortcutHelpDialog, { attachTo: document.body });
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await flushPromises();
    expect(helpOpen.value).toBe(false);
    wrapper.unmount();
  });

  it('关闭按钮与遮罩都能关', async () => {
    const wrapper = mount(ShortcutHelpDialog, { attachTo: document.body });
    await wrapper.find('.dialog-head .text-button').trigger('click');
    expect(helpOpen.value).toBe(false);
    helpOpen.value = true;
    await flushPromises();
    await wrapper.find('.dialog-backdrop').trigger('click.self');
    expect(helpOpen.value).toBe(false);
    wrapper.unmount();
  });
});
