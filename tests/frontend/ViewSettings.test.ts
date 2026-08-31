import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ViewSettings from '@/views/ViewSettings.vue';
import { useAlertsStore } from '@/stores/useAlertsStore';
import { useSettingsStore } from '@/stores/useSettingsStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';

vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));

describe('ViewSettings', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it('默认展示提醒中心', () => {
    const wrapper = mount(ViewSettings);
    expect(wrapper.text()).toContain('提醒中心');
    expect(wrapper.text()).toContain('通知收件箱');
  });

  it('切换到网站设置并回显 workspaceName', () => {
    const alerts = useAlertsStore();
    const settings = useSettingsStore();
    alerts.hubTab = 'settings';
    settings.settingsDraft.workspaceName = '我的工作台';
    const wrapper = mount(ViewSettings);
    const input = wrapper.find('input[aria-label="工作区名称"]');
    expect(input.exists()).toBe(true);
    expect((input.element as HTMLInputElement).value).toBe('我的工作台');
  });

  it('数据获取分组包含行情刷新间隔输入', () => {
    const alerts = useAlertsStore();
    const settings = useSettingsStore();
    alerts.hubTab = 'settings';
    settings.settingsTab = 'data';
    settings.settingsDraft.refreshInterval = 30;
    const wrapper = mount(ViewSettings);
    const input = wrapper.find('input[aria-label="行情刷新间隔"]');
    expect(input.exists()).toBe(true);
    expect((input.element as HTMLInputElement).value).toBe('30');
  });

  it('保存设置按钮存在且触发 saveSettings（mock 避免网络请求）', async () => {
    const alerts = useAlertsStore();
    const settings = useSettingsStore();
    alerts.hubTab = 'settings';
    const saveSpy = vi.spyOn(settings, 'saveSettings').mockResolvedValue(undefined);
    const wrapper = mount(ViewSettings);
    const saveButton = wrapper.findAll('button').find((b) => b.text().includes('保存设置'));
    expect(saveButton).toBeTruthy();
    await saveButton!.trigger('click');
    expect(saveSpy).toHaveBeenCalled();
  });

  it('提醒中心渲染默认提醒', () => {
    const workspace = useWorkspaceStore();
    const wrapper = mount(ViewSettings);
    expect(workspace.alerts.length).toBeGreaterThan(0);
    expect(wrapper.text()).toContain('真实行情连接已就绪');
  });
});
