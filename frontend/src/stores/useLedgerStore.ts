import { computed, ref } from 'vue';
import { defineStore } from 'pinia';
import { requestJson } from '@/api/client';
import type { FillInput, FillRow, LedgerTotals, LedgerWarning, PositionRow } from '@/types/models';

type WriteResult = { ok: boolean; message?: string; warnings?: LedgerWarning[] };

type PositionsPayload = {
  positions: PositionRow[];
  totals: LedgerTotals;
  warnings: LedgerWarning[];
  disclosures: string[];
};

/**
 * 真实成交台账 store：成交 CRUD + 后端派生的持仓/盈亏。
 * 台账是 append 语义（作废保留审计），不并入 workspace 全量 PUT。
 */
export const useLedgerStore = defineStore('ledger', () => {
  const fills = ref<FillRow[]>([]);
  const positions = ref<PositionRow[]>([]);
  const totals = ref<LedgerTotals>({});
  const warnings = ref<LedgerWarning[]>([]);
  const disclosures = ref<string[]>([]);
  const loading = ref(false);
  const error = ref('');

  const positionFor = computed(() => (code: string) => positions.value.find((row) => row.code === code) ?? null);

  async function load(): Promise<WriteResult> {
    loading.value = true;
    error.value = '';
    try {
      const [fillBody, positionBody] = await Promise.all([
        requestJson<{ items: FillRow[] }>('/api/fills?limit=500'),
        requestJson<PositionsPayload>('/api/positions'),
      ]);
      fills.value = fillBody.items ?? [];
      positions.value = positionBody.positions ?? [];
      totals.value = positionBody.totals ?? {};
      warnings.value = positionBody.warnings ?? [];
      disclosures.value = positionBody.disclosures ?? [];
      return { ok: true };
    } catch (exc) {
      error.value = exc instanceof Error ? exc.message : '台账加载失败';
      return { ok: false, message: error.value };
    } finally {
      loading.value = false;
    }
  }

  function newRequestId(): string {
    return `ui-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
  }

  async function createFill(input: FillInput): Promise<WriteResult> {
    try {
      const body = await requestJson<{ fill: FillRow; warnings?: LedgerWarning[] }>('/api/fills', {
        method: 'POST',
        body: JSON.stringify({ ...input, clientRequestId: input.clientRequestId ?? newRequestId() }),
      });
      await load();
      return { ok: true, warnings: body.warnings ?? [] };
    } catch (exc) {
      return { ok: false, message: exc instanceof Error ? exc.message : '成交保存失败' };
    }
  }

  async function updateFill(id: string, patch: Partial<FillInput>): Promise<WriteResult> {
    try {
      await requestJson<{ fill: FillRow }>(`/api/fills/${encodeURIComponent(id)}`, {
        method: 'PUT',
        body: JSON.stringify(patch),
      });
      await load();
      return { ok: true };
    } catch (exc) {
      return { ok: false, message: exc instanceof Error ? exc.message : '成交保存失败' };
    }
  }

  async function voidFill(id: string, reason = ''): Promise<WriteResult> {
    try {
      await requestJson<{ fill: FillRow }>(`/api/fills/${encodeURIComponent(id)}/void`, {
        method: 'POST',
        body: JSON.stringify({ reason }),
      });
      await load();
      return { ok: true };
    } catch (exc) {
      return { ok: false, message: exc instanceof Error ? exc.message : '作废失败' };
    }
  }

  return {
    fills,
    positions,
    totals,
    warnings,
    disclosures,
    loading,
    error,
    positionFor,
    load,
    createFill,
    updateFill,
    voidFill,
  };
});
