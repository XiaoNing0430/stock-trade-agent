// 主题偏好（spec §5）：localStorage 键 atlas-theme 存 'light'|'dark'；键不存在 = 跟随系统。
// 状态内聚在本模块（单值不值得一个 Pinia store）；localStorage 异常静默降级为跟随系统。
import { computed, ref } from 'vue';

export type ThemePreference = 'light' | 'dark' | null;
export type EffectiveTheme = 'light' | 'dark';

const STORAGE_KEY = 'atlas-theme';
const preference = ref<ThemePreference>(readStored());
const systemDark = ref(false);

function readStored(): ThemePreference {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    return raw === 'light' || raw === 'dark' ? raw : null;
  } catch {
    return null;
  }
}

export const themePreference = computed(() => preference.value);
export const effectiveTheme = computed<EffectiveTheme>(() => preference.value ?? (systemDark.value ? 'dark' : 'light'));

function apply(): void {
  document.documentElement.dataset.theme = effectiveTheme.value;
}

function onSystemChange(event: MediaQueryListEvent): void {
  systemDark.value = event.matches;
  if (preference.value === null) apply();
}

export function setTheme(next: ThemePreference): void {
  preference.value = next;
  try {
    if (next === null) window.localStorage.removeItem(STORAGE_KEY);
    else window.localStorage.setItem(STORAGE_KEY, next);
  } catch {
    /* 隐私模式/存储被禁：仅内存生效 */
  }
  apply();
}

export function toggleTheme(): void {
  setTheme(effectiveTheme.value === 'dark' ? 'light' : 'dark');
}

export function initTheme(): void {
  try {
    const media = window.matchMedia('(prefers-color-scheme: dark)');
    systemDark.value = media.matches;
    media.addEventListener('change', onSystemChange);
  } catch {
    /* matchMedia 不可用：保持浅色兜底 */
  }
  apply();
}
