import { defineStore } from 'pinia';
import { ref } from 'vue';
import { requestJson } from '@/api/client';

export interface ReviewKpis {
  total: number;
  decided: number;
  flatCount: number;
  winRate: number | null;
  avgWinR: number | null;
  avgLossR: number | null;
  payoffRatio: number | null;
  expectancyR: number | null;
  notEnteredRate: number | null;
  openCount: number;
  invalidCount: number;
}
export interface ReviewGroupRow {
  key: string;
  label: string;
  decided: number;
  flatCount: number;
  wins: number;
  winRate: number | null;
  expectancyR: number | null;
  smallSample: boolean;
}
export interface ReviewItem {
  planId: string;
  code: string;
  source: string;
  direction: string;
  entry: number;
  stop: number;
  target: number;
  validity: string;
  status: string;
  outcome: 'win' | 'loss' | 'flat' | 'notEntered' | 'open' | 'invalid';
  rValue: number | null;
  netR: number | null;
  costR: number | null;
  entryDate: string | null;
  exitDate: string | null;
  ambiguous: boolean;
  gapFill: boolean;
  limitDeferred: boolean;
}
export interface ReviewPayload {
  kpis: ReviewKpis;
  groups: {
    source: ReviewGroupRow[];
    direction: ReviewGroupRow[];
    validity: ReviewGroupRow[];
    createdMonth: ReviewGroupRow[];
  };
  items: ReviewItem[];
  // 降级披露（N1）：这些代码由后端本地持久化兜底提供，数据可能陈旧；缺省（undefined）= 无降级。
  degraded?: string[];
}

// 扫描留痕行 = GET /api/screener/scan/history 列表行 camelCase（FR-4）。
// 无 mode 字段——T6 裁定：存储无 mode 列，brief 中的 mode 以裁定为准移除。
// runAtMs 可为 null：app.py 在日期解析失败时下发 null（终审 F5），视图据此渲染占位而非造时间。
export interface ScanTraceRow {
  strategyId: string;
  runAtMs: number | null;
  status: string;
  hitCount: number;
  newCount: number;
  elapsedMs: number;
  traceId: string;
}

export const useReviewStore = defineStore('review', () => {
  const review = ref<ReviewPayload | null>(null);
  const loading = ref(false);
  const days = ref<0 | 30 | 90>(90);
  const activeGroup = ref<'source' | 'direction' | 'validity' | 'createdMonth'>('source');
  const expanded = ref(false);
  const fetchedOnce = ref(false);
  const sortKey = ref<'netR' | 'outcome' | null>(null);
  const sortDir = ref<'asc' | 'desc'>('desc');
  const trace = ref<ScanTraceRow[] | null>(null);
  const traceLoading = ref(false);
  // 错误状态（终审 F3 红线 / N4）：复盘与留痕各自独立错误态，互不覆盖——trace 成功只清 traceError，
  // reviewError 保留至下次复盘成功；反之亦然，避免一路成功误抹另一路的可见错误。
  const reviewError = ref<string | null>(null);
  const traceError = ref<string | null>(null);

  async function fetchReview(d?: 0 | 30 | 90) {
    if (d !== undefined) days.value = d;
    loading.value = true;
    try {
      review.value = await requestJson<ReviewPayload>(`/api/plans/review?days=${days.value}`, { method: 'GET' });
      fetchedOnce.value = true;
      reviewError.value = null;
      void syncTrace();
    } catch (e) {
      // 红线：加载失败即无可信数据 → 清空 review，并复位 fetchedOnce 使再次展开可重新拉取（可重试）。
      review.value = null;
      fetchedOnce.value = false;
      reviewError.value = `复盘数据加载失败：${(e as Error).message}`;
    } finally {
      loading.value = false;
    }
  }
  async function toggle() {
    expanded.value = !expanded.value;
    if (expanded.value && !fetchedOnce.value) await fetchReview();
  }
  function toggleSort(key: 'netR' | 'outcome') {
    if (sortKey.value === key) sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc';
    else {
      sortKey.value = key;
      sortDir.value = 'desc';
    }
  }
  async function fetchTrace(strategyId: string) {
    traceLoading.value = true;
    try {
      const res = await requestJson<{ history: ScanTraceRow[] }>(
        `/api/screener/scan/history?strategyId=${encodeURIComponent(strategyId)}&limit=30`,
        { method: 'GET' }
      );
      // §6：请求取 30 条（后端按 runAt 降序），面板仅展示前 10 条。
      trace.value = (res.history ?? []).slice(0, 10);
      traceError.value = null;
    } catch (e) {
      trace.value = null;
      traceError.value = `扫描留痕加载失败：${(e as Error).message}`;
    } finally {
      traceLoading.value = false;
    }
  }
  function syncTrace() {
    // 来源分组下存在 scan:{strategyId} 行时自动拉取该策略近 30 天留痕（评审 B5）
    if (activeGroup.value !== 'source') {
      trace.value = null;
      return;
    }
    const row = (review.value?.groups.source ?? []).find((r) => r.key.startsWith('scan:'));
    if (row) void fetchTrace(row.key.slice(5));
    else trace.value = null;
  }
  function setGroup(k: typeof activeGroup.value) {
    activeGroup.value = k;
    syncTrace();
  }
  function formatRatio(v: number | null | undefined): string {
    return v === null || v === undefined ? '--' : `${(v * 100).toFixed(1)}%`;
  }
  function formatR(v: number | null | undefined): string {
    return v === null || v === undefined ? '--' : v.toFixed(2);
  }
  return {
    review,
    loading,
    days,
    activeGroup,
    expanded,
    sortKey,
    sortDir,
    trace,
    traceLoading,
    reviewError,
    traceError,
    fetchReview,
    toggle,
    setGroup,
    setDays: fetchReview,
    toggleSort,
    fetchTrace,
    formatRatio,
    formatR,
  };
});
