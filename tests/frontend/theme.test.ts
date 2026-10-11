import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

type FakeMedia = {
  matches: boolean;
  addEventListener: ReturnType<typeof vi.fn>;
  removeEventListener: ReturnType<typeof vi.fn>;
};
let media: FakeMedia;
let store: Record<string, string>;

async function fresh() {
  vi.resetModules();
  return import('@/modules/theme');
}

beforeEach(() => {
  store = {};
  media = { matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() };
  vi.stubGlobal('localStorage', {
    getItem: (k: string) => (k in store ? store[k] : null),
    setItem: (k: string, v: string) => {
      store[k] = v;
    },
    removeItem: (k: string) => {
      delete store[k];
    },
  });
  vi.stubGlobal(
    'matchMedia',
    vi.fn(() => media)
  );
  document.documentElement.removeAttribute('data-theme');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('theme 模块', () => {
  it('未设偏好 + 系统浅色 → effective light，initTheme 写入 data-theme=light', async () => {
    const theme = await fresh();
    theme.initTheme();
    expect(theme.effectiveTheme.value).toBe('light');
    expect(document.documentElement.dataset.theme).toBe('light');
    expect(media.addEventListener).toHaveBeenCalled();
  });

  it('未设偏好 + 系统深色 → 跟随系统为 dark', async () => {
    media.matches = true;
    const theme = await fresh();
    theme.initTheme();
    expect(theme.effectiveTheme.value).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('显式 light/dark 覆盖系统偏好', async () => {
    media.matches = true;
    store['atlas-theme'] = 'light';
    let theme = await fresh();
    theme.initTheme();
    expect(theme.effectiveTheme.value).toBe('light');
    store['atlas-theme'] = 'dark';
    theme = await fresh();
    theme.initTheme();
    expect(theme.effectiveTheme.value).toBe('dark');
  });

  it('非法存储值视同未设（跟随系统）', async () => {
    media.matches = true;
    store['atlas-theme'] = 'blue';
    const theme = await fresh();
    theme.initTheme();
    expect(theme.themePreference.value).toBeNull();
    expect(theme.effectiveTheme.value).toBe('dark');
  });

  it('setTheme 写入存储并即时生效；setTheme(null) 删键回跟随系统', async () => {
    const theme = await fresh();
    theme.initTheme();
    theme.setTheme('dark');
    expect(store['atlas-theme']).toBe('dark');
    expect(document.documentElement.dataset.theme).toBe('dark');
    theme.setTheme(null);
    expect('atlas-theme' in store).toBe(false);
    expect(theme.themePreference.value).toBeNull();
  });

  it('系统偏好变化仅在未显式选择时联动', async () => {
    const theme = await fresh();
    theme.initTheme();
    const handler = media.addEventListener.mock.calls[0][1] as (e: { matches: boolean }) => void;
    handler({ matches: true });
    expect(document.documentElement.dataset.theme).toBe('dark');
    theme.setTheme('light');
    handler({ matches: false });
    expect(document.documentElement.dataset.theme).toBe('light');
  });

  it('localStorage 抛异常时静默降级（内存态仍生效，不崩溃）', async () => {
    vi.stubGlobal('localStorage', {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
      removeItem: () => {
        throw new Error('blocked');
      },
    });
    const theme = await fresh();
    theme.initTheme();
    expect(() => theme.setTheme('dark')).not.toThrow();
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('toggleTheme 在浅深间翻转（显式写入）', async () => {
    const theme = await fresh();
    theme.initTheme();
    theme.toggleTheme();
    expect(theme.themePreference.value).toBe('dark');
    theme.toggleTheme();
    expect(theme.themePreference.value).toBe('light');
  });
});
