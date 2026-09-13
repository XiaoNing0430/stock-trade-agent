import { describe, expect, it, vi, beforeEach } from 'vitest';
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ViewStockDetail from '@/views/ViewStockDetail.vue';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { useAssistStore } from '@/stores/useAssistStore';

vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));

describe('ViewStockDetail', () => {
  beforeEach(() => {
    localStorage.clear();
    setActivePinia(createPinia());
  });

  it('页头「生成草案」按钮 → openFor 携带选中代码/名称/快照价', async () => {
    const quotes = useQuotesStore();
    quotes.market.quotes = [
      {
        code: '600519',
        name: '贵州茅台',
        exchange: '上交所',
        board: '主板',
        market: '沪市主板',
        price: 1700,
        change: 2.5,
      },
    ];
    quotes.selectedCode = '600519';
    const assist = useAssistStore();
    const spy = vi.spyOn(assist, 'openFor').mockResolvedValue(undefined);
    const wrapper = mount(ViewStockDetail);
    const button = wrapper.find('button[data-testid="generate-draft"]');
    expect(button.exists()).toBe(true);
    expect(button.text()).toContain('生成草案');
    await button.trigger('click');
    expect(spy).toHaveBeenCalledTimes(1);
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ code: '600519', name: '贵州茅台', price: 1700 }));
  });

  it('无报价时 openFor 携带 null（绝不造数，交由后端取实时价）', async () => {
    const quotes = useQuotesStore();
    quotes.selectedCode = '600519';
    const assist = useAssistStore();
    const spy = vi.spyOn(assist, 'openFor').mockResolvedValue(undefined);
    const wrapper = mount(ViewStockDetail);
    await wrapper.find('button[data-testid="generate-draft"]').trigger('click');
    expect(spy).toHaveBeenCalledWith(expect.objectContaining({ code: '600519', price: null }));
  });
});
