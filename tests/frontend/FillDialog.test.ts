import { describe, expect, it } from 'vitest';
import { mount } from '@vue/test-utils';
import FillDialog from '@/components/FillDialog.vue';

function mountDialog(props: Record<string, unknown> = {}) {
  return mount(FillDialog, {
    props: { open: true, ...props },
    global: { stubs: { teleport: true } },
  });
}

describe('FillDialog', () => {
  it('renders chinese labels and prefilled plan values', () => {
    const wrapper = mountDialog({ preset: { code: '600519', direction: 'buy', price: 10, qty: 100 } });
    expect(wrapper.text()).toContain('录入成交');
    expect((wrapper.get('[data-testid="fill-code"]').element as HTMLInputElement).value).toBe('600519');
    expect((wrapper.get('[data-testid="fill-qty"]').element as HTMLInputElement).value).toBe('100');
  });

  it('blocks empty code or non-positive qty with chinese hint', async () => {
    const wrapper = mountDialog();
    await wrapper.get('[data-testid="fill-submit"]').trigger('click');
    expect(wrapper.text()).toContain('请填写证券代码');
    await wrapper.get('[data-testid="fill-code"]').setValue('600519');
    await wrapper.get('[data-testid="fill-price"]').setValue('10');
    await wrapper.get('[data-testid="fill-qty"]').setValue('0');
    await wrapper.get('[data-testid="fill-submit"]').trigger('click');
    expect(wrapper.text()).toContain('成交数量必须是正整数');
  });

  it('emits submit payload with ms timestamp', async () => {
    const wrapper = mountDialog({ preset: { code: '600519', price: 10, qty: 100 } });
    await wrapper.get('[data-testid="fill-submit"]').trigger('click');
    const payload = wrapper.emitted('submit')?.[0]?.[0] as { code: string; tradedAtMs: number };
    expect(payload.code).toBe('600519');
    expect(typeof payload.tradedAtMs).toBe('number');
  });

  it('estimates fee for shanghai stock buy and sell', async () => {
    const wrapper = mountDialog({ preset: { code: '600519', price: 10, qty: 1000 } });
    await wrapper.get('[data-testid="fill-estimate"]').trigger('click');
    // 买入：max(5, 10000*0.0003)=5 + 过户费 0.1
    expect((wrapper.get('[data-testid="fill-fee"]').element as HTMLInputElement).value).toBe('5.1');
    await wrapper.get('[data-testid="fill-direction"]').setValue('sell');
    await wrapper.get('[data-testid="fill-estimate"]').trigger('click');
    // 卖出：5 + 印花税 5 + 过户费 0.1
    expect((wrapper.get('[data-testid="fill-fee"]').element as HTMLInputElement).value).toBe('10.1');
  });

  it('does not emit when closed', async () => {
    const wrapper = mountDialog({ open: false });
    expect(wrapper.find('[data-testid="fill-submit"]').exists()).toBe(false);
  });
});
