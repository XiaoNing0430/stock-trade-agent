import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { requestJson } from '@/api/client';
import { useWorkspaceStore } from './useWorkspaceStore';

/** GET /api/screener/scan/hits 条目（spec §4.2）。 */
interface ScanHitCode {
  code: string;
  name: string | null;
  score: number | null;
  firstSeen: string;
}
interface ScanHit {
  strategyId: string;
  strategyName: string;
  scannedAt: string | null;
  status: string | null;
  codes: ScanHitCode[];
}
export interface ScanConfig {
  strategyId: string;
  strategyName: string;
  enabled: boolean;
  mode: string;
  lastRunAt: string | null;
  lastStatus: string | null;
  hitCount: number;
  newCount: number;
}
/** POST /api/screener/scan/now 返回（spec §4.3）。 */
export interface RunScanResult {
  alerted: number;
}
/** 合成提醒项（spec §4.3 形状逐字）。 */
export interface ScanAlertItem {
  id: string;
  kind: 'alert';
  title: string;
  message: string;
  code: string;
  strategyId: string;
  firstSeen: string;
  createdAtMs: number;
  read: false;
}

function seenKey(strategyId: string): string {
  return `atlas.scan.seen.${strategyId}`;
}
const SEEN_PREFIX = 'atlas.scan.seen.';
function firstSeenMs(firstSeen: string): number {
  return new Date(`${firstSeen}T15:40:00+08:00`).getTime();
}

export const useScanStore = defineStore('scan', () => {
  const workspace = useWorkspaceStore();
  const hits = ref<ScanHit[]>([]);
  const loaded = ref(false);

  async function fetchHits(): Promise<void> {
    try {
      const payload = await requestJson<{ hits?: ScanHit[] }>('/api/screener/scan/hits');
      hits.value = payload?.hits ?? [];
      loaded.value = true;
    } catch {
      // 提醒中心不因扫描端点失败而中断（合成项下次轮询再补）
    }
  }

  const scanAlerts = computed<ScanAlertItem[]>(() =>
    hits.value.flatMap((hit) =>
      hit.codes.map((c) => ({
        id: `scan:${hit.strategyId}:${c.code}:${c.firstSeen}`,
        kind: 'alert' as const,
        title: `扫描命中 · ${hit.strategyName}`,
        message: `${c.code} ${c.name ?? ''}（评分 ${c.score ?? '--'}）`.trim(),
        code: c.code,
        strategyId: hit.strategyId,
        firstSeen: c.firstSeen,
        createdAtMs: firstSeenMs(c.firstSeen),
        read: false as const,
      }))
    )
  );

  // 已读时间戳：键 `atlas.scan.seen.{strategyId}`（brief 逐字），读取沿用 useWorkspaceStore STORAGE_KEY 先例——
  // localStorage 读入响应式状态、写入时逐键持久化。
  // （brief 实现稿每次直接读 localStorage：非响应式导致 markSeen 后 unreadScanCount 不重算，无法通过其自身 Step 1 测试，故改为 ref。）
  function loadSeen(): Record<string, number> {
    const seen: Record<string, number> = {};
    try {
      for (let i = 0; i < localStorage.length; i += 1) {
        const key = localStorage.key(i);
        if (!key || !key.startsWith(SEEN_PREFIX)) continue;
        const ms = Number(localStorage.getItem(key));
        if (Number.isFinite(ms) && ms > 0) seen[key.slice(SEEN_PREFIX.length)] = ms;
      }
    } catch {
      return {};
    }
    return seen;
  }

  const seen = ref<Record<string, number>>(loadSeen());
  function seenMs(strategyId: string): number {
    return Number(seen.value[strategyId] || 0);
  }
  function isUnseen(item: ScanAlertItem): boolean {
    return item.createdAtMs > seenMs(item.strategyId);
  }
  const unreadScanCount = computed(() => scanAlerts.value.filter(isUnseen).length);
  function markSeen(strategyId: string): void {
    const ms = Date.now();
    seen.value = { ...seen.value, [strategyId]: ms };
    try {
      localStorage.setItem(seenKey(strategyId), String(ms));
    } catch {
      // Storage is optional; real quotes continue to work without it.
    }
  }

  async function loadConfig(strategyId: string): Promise<ScanConfig | null> {
    try {
      const payload = await requestJson<{ configs?: ScanConfig[] }>('/api/screener/scan/configs');
      const list = payload?.configs ?? [];
      return list.find((c) => c.strategyId === strategyId) ?? null;
    } catch {
      return null;
    }
  }

  async function saveConfig(strategyId: string, enabled: boolean, mode: string): Promise<boolean> {
    try {
      await requestJson('/api/screener/scan/configs', {
        method: 'PUT',
        body: JSON.stringify({ strategyId, enabled, mode }),
      });
      return true;
    } catch (error: any) {
      workspace.showToast(
        error?.status === 422 ? '扫描配置无效（策略或模式不合法）' : '扫描配置保存失败，稍后重试',
        'error'
      );
      return false;
    }
  }

  async function runScanNow(strategyId: string): Promise<RunScanResult | null> {
    try {
      const payload = await requestJson('/api/screener/scan/now', {
        method: 'POST',
        body: JSON.stringify({ strategyId }),
      });
      await fetchHits();
      return payload as RunScanResult;
    } catch {
      workspace.showToast('扫描失败（上游不可用），稍后可重试', 'error');
      return null;
    }
  }

  return {
    hits, loaded, fetchHits, scanAlerts, unreadScanCount, isUnseen, markSeen,
    loadConfig, saveConfig, runScanNow,
  };
});
