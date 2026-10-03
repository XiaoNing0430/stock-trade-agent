import { describe, expect, it, vi, beforeEach } from 'vitest';
import { flushPromises, mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import ViewStockDetail from '@/views/ViewStockDetail.vue';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { useAssistStore } from '@/stores/useAssistStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { fetchMinute } from '@/api/client';

vi.mock('lucide', () => ({ createIcons: vi.fn(), icons: {} }));
vi.mock('@/modules/lucideIcons', () => ({ UI_ICONS: {} }));
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  fetchMinute: vi.fn(),
}));

const fetchMinuteMock = vi.mocked(fetchMinute);

function minuteResponse(overrides: Record<string, unknown> = {}) {
  return {
    bars: [{ close: 10.5 }, { close: 10.8 }],
    source: 'upstream',
    state: 'ok',
    degraded: false,
    updatedAtMs: null,
    ...overrides,
  };
}

async function mountDetail() {
  const quotes = useQuotesStore();
  quotes.selectedCode = '600519';
  const workspace = useWorkspaceStore();
  const wrapper = mount(ViewStockDetail);
  return { quotes, workspace, wrapper };
}

type DetailWrapper = Awaited<ReturnType<typeof mountDetail>>['wrapper'];

async function clickPeriod(wrapper: DetailWrapper, period: string) {
  await wrapper
    .findAll('.minute-toolbar button')
    .filter((b) => b.text() === period)[0]
    .trigger('click');
  await flushPromises();
}

describe('ViewStockDetail', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.clearAllMocks();
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

  it('分钟周期按钮组渲染 1m/5m/15m/30m/60m（默认 5m，无轮询仅手动触发）', async () => {
    const { wrapper } = await mountDetail();
    const labels = wrapper.findAll('.minute-toolbar button').map((b) => b.text());
    expect(labels).toEqual(['1m', '5m', '15m', '30m', '60m']);
    expect(fetchMinuteMock).not.toHaveBeenCalled();
  });

  it('ok+upstream → 正常画线，无降级提示', async () => {
    fetchMinuteMock.mockResolvedValueOnce(minuteResponse() as any);
    const { wrapper } = await mountDetail();
    await clickPeriod(wrapper, '1m');
    expect(wrapper.find('[data-testid="minute-chart"]').html()).toContain('<svg');
    expect(wrapper.find('.minute-status').exists()).toBe(false);
    expect(wrapper.find('.minute-status-badge').exists()).toBe(false);
  });

  it('ok+cache_l1 命中 → 黄标「分钟线（缓存，N 分钟前）」（updatedAtMs 分钟差）', async () => {
    fetchMinuteMock.mockResolvedValueOnce(
      minuteResponse({ source: 'cache_l1', updatedAtMs: Date.now() - 2 * 60_000 }) as any
    );
    const { wrapper } = await mountDetail();
    await clickPeriod(wrapper, '5m');
    expect(wrapper.find('.minute-status-badge').text()).toBe('分钟线（缓存，2 分钟前）');
    expect(wrapper.find('[data-testid="minute-chart"]').html()).toContain('<svg');
  });

  it('ok+degraded 无 updatedAtMs → 黄标「分钟线（缓存）」', async () => {
    fetchMinuteMock.mockResolvedValueOnce(minuteResponse({ source: 'cache_l2', degraded: true }) as any);
    const { wrapper } = await mountDetail();
    await clickPeriod(wrapper, '5m');
    expect(wrapper.find('.minute-status-badge').text()).toBe('分钟线（缓存）');
  });

  it('etl_busy → 灰条「日线同步中，分钟线稍后可用」附重试，不画线不造数', async () => {
    fetchMinuteMock.mockResolvedValueOnce(
      minuteResponse({ bars: [], source: null, state: 'etl_busy', degraded: true }) as any
    );
    const { wrapper } = await mountDetail();
    await clickPeriod(wrapper, '5m');
    expect(wrapper.find('.minute-status').text()).toBe('日线同步中，分钟线稍后可用重试');
    expect(wrapper.find('[data-testid="minute-retry"]').exists()).toBe(true);
    expect(wrapper.find('[data-testid="minute-chart"]').exists()).toBe(false);
  });

  it('circuit_open → 灰条「分钟线暂不可用」附重试', async () => {
    fetchMinuteMock.mockResolvedValueOnce(
      minuteResponse({ bars: [], source: null, state: 'circuit_open', degraded: true }) as any
    );
    const { wrapper } = await mountDetail();
    await clickPeriod(wrapper, '5m');
    expect(wrapper.find('.minute-status').text()).toBe('分钟线暂不可用重试');
  });

  it('拉取异常（非 429）→ 灰条「分钟线暂不可用」', async () => {
    fetchMinuteMock.mockRejectedValueOnce(Object.assign(new Error('HTTP 500'), { status: 500 }));
    const { wrapper } = await mountDetail();
    await clickPeriod(wrapper, '5m');
    expect(wrapper.find('.minute-status').text()).toContain('分钟线暂不可用');
  });

  it('灰条态点重试 → 仅一次手动请求（无轮询纪律）', async () => {
    fetchMinuteMock.mockResolvedValueOnce(
      minuteResponse({ bars: [], source: null, state: 'etl_busy', degraded: true }) as any
    );
    const { wrapper } = await mountDetail();
    await clickPeriod(wrapper, '5m');
    expect(fetchMinuteMock).toHaveBeenCalledTimes(1);
    await wrapper.find('[data-testid="minute-retry"]').trigger('click');
    await flushPromises();
    expect(fetchMinuteMock).toHaveBeenCalledTimes(2);
  });

  it('429 → toast「请求过于频繁」，不改状态条', async () => {
    fetchMinuteMock.mockRejectedValueOnce(Object.assign(new Error('请求过于频繁，请稍后再试'), { status: 429 }));
    const { wrapper, workspace } = await mountDetail();
    const toastSpy = vi.spyOn(workspace, 'showToast');
    await clickPeriod(wrapper, '5m');
    expect(toastSpy).toHaveBeenCalledWith('请求过于频繁', 'error');
    expect(wrapper.find('.minute-status').exists()).toBe(false);
  });
});
