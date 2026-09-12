import { defineStore } from 'pinia';
import { ref } from 'vue';
import { requestJson } from '@/api/client';

export interface ReviewKpis {
  total: number; decided: number; flatCount: number; winRate: number | null;
  avgWinR: number | null; avgLossR: number | null; payoffRatio: number | null;
  expectancyR: number | null; notEnteredRate: number | null; openCount: number; invalidCount: number;
}
export interface ReviewGroupRow {
  key: string; label: string; decided: number; flatCount: number; wins: number;
  winRate: number | null; expectancyR: number | null; smallSample: boolean;
}
export interface ReviewItem {
  planId: string; code: string; source: string; direction: string;
  entry: number; stop: number; target: number; validity: string; status: string;
  outcome: 'win' | 'loss' | 'flat' | 'notEntered' | 'open' | 'invalid';
  rValue: number | null; netR: number | null; costR: number | null;
  entryDate: string | null; exitDate: string | null;
  ambiguous: boolean; gapFill: boolean; limitDeferred: boolean;
}
export interface ReviewPayload {
  kpis: ReviewKpis;
  groups: { source: ReviewGroupRow[]; direction: ReviewGroupRow[]; validity: ReviewGroupRow[]; createdMonth: ReviewGroupRow[] };
  items: ReviewItem[];
}

// 扫描留痕行 = GET /api/screener/scan/history 列表行 camelCase（FR-4）。
// 无 mode 字段——T6 裁定：存储无 mode 列，brief 中的 mode 以裁定为准移除。
export interface ScanTraceRow {
  strategyId: string; runAtMs: number; status: string; hitCount: number;
  newCount: number; elapsedMs: number; traceId: string;
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

  async function fetchReview(d?: 0 | 30 | 90) {
    if (d !== undefined) days.value = d;
    loading.value = true;
    try {
      review.value = await requestJson<ReviewPayload>(`/api/plans/review?days=${days.value}`, { method: 'GET' });
      fetchedOnce.value = true;
      void syncTrace();
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
    else { sortKey.value = key; sortDir.value = 'desc'; }
  }
  async function fetchTrace(strategyId: string) {
    traceLoading.value = true;
    try {
      const res = await requestJson<{ history: ScanTraceRow[] }>(
        `/api/screener/scan/history?strategyId=${encodeURIComponent(strategyId)}&limit=30`, { method: 'GET' });
      trace.value = res.history;
    } finally {
      traceLoading.value = false;
    }
  }
  function syncTrace() {
    // 来源分组下存在 scan:{strategyId} 行时自动拉取该策略近 30 天留痕（评审 B5）
    if (activeGroup.value !== 'source') { trace.value = null; return; }
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
  return { review, loading, days, activeGroup, expanded, sortKey, sortDir, trace, traceLoading,
           fetchReview, toggle, setGroup, setDays: fetchReview, toggleSort, fetchTrace, formatRatio, formatR };
});
