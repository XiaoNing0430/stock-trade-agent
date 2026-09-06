<script setup lang="ts">
import { computed, reactive, watch } from 'vue';
import { useAssistStore } from '@/stores/useAssistStore';
import { useSettingsStore } from '@/stores/useSettingsStore';
import { formatNumber } from '@/modules/format';
import type { Plan } from '@/types/models';
import type { AssistRecalcInput } from '@/stores/useAssistStore';

const assist = useAssistStore();
const settings = useSettingsStore();

// 可调参数（本地态；draft 为服务端一次返回的指标原值）
const params = reactive({
  entryInput: '',
  stopMode: 'atr' as 'atr' | 'ma20',
  rrRatio: 2,
  riskPct: 1,
  capPct: 25,
  manualStop: null as number | null,
  equity: 100000,
  note: '',
});

function collectRecalcInput(): AssistRecalcInput {
  return {
    entry: Number(params.entryInput) || 0,
    stopMode: params.stopMode,
    rrRatio: params.rrRatio,
    riskPct: params.riskPct,
    capPct: params.capPct,
    manualStop: params.manualStop,
    equity: params.equity,
  };
}

// 新草案打开：调参回归默认（FR-13），entry 回显服务端值，权益回显设置默认资金
watch(
  () => assist.draft,
  (d) => {
    if (!d) return;
    params.entryInput = d.entry != null ? String(d.entry) : '';
    params.stopMode = 'atr';
    params.rrRatio = 2;
    params.riskPct = 1;
    params.capPct = 25;
    params.manualStop = null;
    params.equity = Number(settings.settingsDraft.defaultCapital) || 100000;
    params.note = '';
    assist.recalc(collectRecalcInput());
  },
  { immediate: true },
);

// 调参仅本地重算，零 API（FR-13）
watch(params, () => assist.recalc(collectRecalcInput()), { deep: true });

function onManualStopInput(event: Event) {
  const raw = (event.target as HTMLInputElement).value;
  const value = Number(raw);
  params.manualStop = raw.trim() === '' || !Number.isFinite(value) ? null : value;
}

// 合并警示：后端 warnings 在前（数据不足 2 条由后端透传），assistCalc sizing 警示在后
const mergedWarnings = computed(() => [
  ...(assist.draft?.warnings ?? []),
  ...(assist.suggestion?.warnings ?? []),
]);

const equityLabel = computed(() => `${formatNumber(params.equity)} 元`);

async function onConfirm() {
  const d = assist.draft;
  const s = assist.suggestion;
  if (assist.submitting || !d || !s || s.stop == null || s.target == null || s.suggestedShares === 0) return;
  const plan = {
    id: `plan-${d.code}-${Date.now()}`,
    code: d.code,
    direction: d.direction === 'sell' ? 'sell' : 'buy',
    entry: Number(Number(params.entryInput).toFixed(2)),
    stop: Number(s.stop.toFixed(2)),
    target: Number(s.target.toFixed(2)),
    capital: params.equity,
    position: s.positionPct,
    validity: '本周内',
    note: params.note.trim() || '未填写交易逻辑',
    status: '执行中',
    triggered: {},
    createdAtMs: Date.now(),
    createdAt: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }),
  } as Plan & { createdAt?: string };
  await assist.confirmDraft(plan);
}
</script>

<template>
  <div
    v-if="assist.visible"
    class="dialog-backdrop"
    @click.self="assist.close()"
  >
    <section
      class="dialog-panel plan-draft-panel"
      role="dialog"
      aria-modal="true"
      aria-label="交易计划草案"
    >
      <header class="plan-draft-head">
        <strong>交易计划草案{{ assist.draft ? ` · ${assist.draft.name || assist.draft.code}` : '' }}</strong>
        <span
          v-if="assist.draft?.fallbackUsed"
          class="draft-fallback-badge"
          data-testid="fallback-badge"
        >备用数据源</span>
        <button
          class="text-button"
          type="button"
          @click="assist.close()"
        >
          关闭
        </button>
      </header>

      <div
        v-if="assist.loading"
        class="plan-draft-state"
      >
        草案生成中…
      </div>
      <div
        v-else-if="assist.error"
        class="plan-draft-state plan-draft-error"
      >
        {{ assist.error }}
      </div>

      <template v-else-if="assist.draft">
        <div
          v-if="assist.draft.stale"
          class="draft-stale-banner"
          data-testid="stale-banner"
        >
          入场价可能已过期（快照时间未知或超过 60 秒），请核实现价后再确认
        </div>

        <dl class="draft-metrics">
          <div><dt>数据日期</dt><dd>{{ assist.draft.referenceDate || '--' }}</dd></div>
          <div><dt>数据来源</dt><dd>{{ assist.draft.provider || '--' }}</dd></div>
          <div>
            <dt>入场价</dt>
            <dd>
              <input
                v-model="params.entryInput"
                type="number"
                step="0.01"
                min="0.01"
                data-testid="entry-input"
                aria-label="入场价"
              >
            </dd>
          </div>
        </dl>

        <ul
          v-if="mergedWarnings.length"
          class="draft-warnings"
          data-testid="warnings"
        >
          <li
            v-for="(warning, index) in mergedWarnings"
            :key="index"
            data-testid="warning-item"
          >
            {{ warning }}
          </li>
        </ul>

        <fieldset class="draft-params">
          <legend>调参（仅本地重算，零 API）</legend>
          <div class="draft-params-grid">
            <label>止损模式
              <select
                v-model="params.stopMode"
                data-testid="stop-mode-select"
              >
                <option value="atr">ATR（入场价 − 2×ATR14）</option>
                <option value="ma20">MA20 均线</option>
              </select>
            </label>
            <label>手动止损
              <input
                :value="params.manualStop ?? ''"
                type="number"
                step="0.01"
                placeholder="留空按模式计算"
                data-testid="manual-stop-input"
                aria-label="手动止损"
                @input="onManualStopInput"
              >
            </label>
            <label>盈亏比
              <input
                v-model.number="params.rrRatio"
                type="number"
                step="0.5"
                min="1"
                max="10"
                data-testid="rr-input"
                aria-label="盈亏比"
              >
            </label>
            <label>单笔风险比例（%）
              <input
                v-model.number="params.riskPct"
                type="number"
                step="0.1"
                min="0.1"
                max="5"
                data-testid="risk-pct-input"
                aria-label="单笔风险比例"
              >
            </label>
            <label>单票市值上限（%）
              <input
                v-model.number="params.capPct"
                type="number"
                step="1"
                min="5"
                max="100"
                data-testid="cap-pct-input"
                aria-label="单票市值上限"
              >
            </label>
            <label>账户权益（元）
              <input
                v-model.number="params.equity"
                type="number"
                step="1000"
                min="1"
                data-testid="equity-input"
                aria-label="账户权益"
              >
            </label>
            <label class="draft-note">交易逻辑备注
              <input
                v-model="params.note"
                type="text"
                data-testid="note-input"
                placeholder="未填写交易逻辑"
                aria-label="交易逻辑备注"
              >
            </label>
          </div>
        </fieldset>

        <dl class="draft-result">
          <div><dt>止损价</dt><dd>{{ formatNumber(assist.suggestion?.stop ?? null) }}</dd></div>
          <div data-testid="target">
            <dt>目标价</dt><dd>{{ formatNumber(assist.suggestion?.target ?? null) }}</dd>
          </div>
          <div data-testid="shares">
            <dt>建议股数</dt><dd>{{ assist.suggestion ? `${assist.suggestion.suggestedShares} 股` : '--' }}</dd>
          </div>
          <div data-testid="position">
            <dt>仓位占比</dt><dd>{{ assist.suggestion ? `${formatNumber(assist.suggestion.positionPct)}%` : '--' }}</dd>
          </div>
          <div><dt>账户权益</dt><dd>{{ equityLabel }}</dd></div>
        </dl>

        <p class="draft-disclaimer">
          {{ assist.draft.disclaimer }}
        </p>

        <p
          v-if="assist.suggestion && !assist.submitting && (assist.suggestion.stop == null || assist.suggestion.suggestedShares === 0)"
          class="draft-disable-hint"
          data-testid="confirm-hint"
        >
          资金不足以按该风险比例建仓，请调高风险比例或降低入场价
        </p>

        <footer class="plan-draft-foot">
          <button
            class="button button-secondary"
            type="button"
            @click="assist.close()"
          >
            取消
          </button>
          <button
            class="button button-primary"
            type="button"
            data-testid="confirm"
            :disabled="assist.submitting || !assist.suggestion || assist.suggestion.stop == null || assist.suggestion.suggestedShares === 0"
            @click="onConfirm"
          >
            {{ assist.submitting ? '保存中…' : '确认落入计划' }}
          </button>
        </footer>
      </template>
    </section>
  </div>
</template>
