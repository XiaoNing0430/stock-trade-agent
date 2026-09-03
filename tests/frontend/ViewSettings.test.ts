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

  it('数据分组渲染4个动态数据源下拉（实时/日线/选股/基本面）', () => {
    const alerts = useAlertsStore();
    const settings = useSettingsStore();
    alerts.hubTab = 'settings';
    settings.settingsTab = 'data';
    // 注入模拟数据源
    settings.dataSources = [
      { id: 'tencent', name: '腾讯公开行情', available: true, realtime: true, history: true, screener: true },
      { id: 'eastmoney', name: '东方财富', available: true, realtime: true, history: true, screener: true, fundamental: true },
      { id: 'mock_us', name: '美股模拟', available: true, realtime: true, history: true, screener: true, fundamental: true },
    ];
    settings.settingsDraft.realtimeSource = 'tencent';
    settings.settingsDraft.historySource = 'eastmoney';
    settings.settingsDraft.screenerSource = 'tencent';
    settings.settingsDraft.fundamentalSource = 'eastmoney';
    const wrapper = mount(ViewSettings);
    // 验证所有下拉存在且动态选项
    const realtimeSelect = wrapper.find('select[aria-label="实时行情来源"]');
    expect(realtimeSelect.exists()).toBe(true);
    const realtimeOptions = realtimeSelect.findAll('option');
    // 所有 3 个源都有 realtime 能力
    expect(realtimeOptions.length).toBe(3);

    const historySelect = wrapper.find('select[aria-label="历史日线来源"]');
    expect(historySelect.exists()).toBe(true);
    const historyOptions = historySelect.findAll('option');
    expect(historyOptions.length).toBe(3);

    const screenerSelect = wrapper.find('select[aria-label="选股指标来源"]');
    expect(screenerSelect.exists()).toBe(true);
    const screenerOptions = screenerSelect.findAll('option');
    expect(screenerOptions.length).toBe(3);

    const fundamentalSelect = wrapper.find('select[aria-label="财务数据源"]');
    expect(fundamentalSelect.exists()).toBe(true);
    const fundamentalOptions = fundamentalSelect.findAll('option');
    // 只有 eastmoney 和 mock_us 有 fundamental 能力
    expect(fundamentalOptions.length).toBe(2);
  });

  it('数据渲染不可用能力筛选（fundamental 仅 eastmoney/mock_us）', () => {
    const alerts = useAlertsStore();
    const settings = useSettingsStore();
    alerts.hubTab = 'settings';
    settings.settingsTab = 'data';
    settings.dataSources = [
      { id: 'tencent', name: '腾讯公开行情', available: true, realtime: true, history: true, screener: true },
      { id: 'eastmoney', name: '东方财富', available: true, realtime: true, history: true, screener: true, fundamental: true },
    ];
    const wrapper = mount(ViewSettings);
    // realtime 下拉有 2 个选项
    expect(wrapper.find('select[aria-label="实时行情来源"]').findAll('option').length).toBe(2);
    // fundamental 下拉只有 1 个选项
    expect(wrapper.find('select[aria-label="财务数据源"]').findAll('option').length).toBe(1);
  });

  it('连接分组展示能力徽标', () => {
    const alerts = useAlertsStore();
    const settings = useSettingsStore();
    alerts.hubTab = 'settings';
    settings.settingsTab = 'connection';
    settings.dataSources = [
      { id: 'tencent', name: '腾讯公开行情', available: true, realtime: true, history: true, screener: true },
      { id: 'eastmoney', name: '东方财富', available: true, realtime: true, history: true, screener: true, fundamental: true },
    ];
    const wrapper = mount(ViewSettings);
    expect(wrapper.text()).toContain('腾讯公开行情');
    expect(wrapper.text()).toContain('东方财富');
    // 能力徽标文本
    expect(wrapper.findAll('.badge').length).toBe(7); // tencent: 3 badges, eastmoney: 4 badges
  });
});
