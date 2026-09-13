<template>
  <section class="view-panel is-active">
    <div class="view-heading">
      <div><span class="section-kicker">TRADE PLAN</span><h2>把想法写成可以执行的规则</h2><p class="heading-note">一份计划至少要有入场、止损、目标和仓位。</p></div>
      <div class="view-heading-actions"><span class="plan-count"><strong>{{ activePlans.length }}</strong> 份执行中</span><button class="button button-secondary" type="button" @click="switchView('monitor')"><i data-lucide="radar" aria-hidden="true"></i>去盯盘</button></div>
    </div>
    <div class="plan-layout">
      <section class="plan-form-panel surface">
        <div class="surface-heading"><div><span class="section-kicker">NEW PLAN</span><h3>创建交易计划</h3></div><span class="draft-status">{{ draftDirty ? '未保存' : '草稿' }}</span></div>
        <form @submit.prevent="savePlan">
          <div class="form-grid">
            <label class="field field-wide"><span>标的</span><select v-model="draft.code" required><option v-for="stock in planOptions" :key="stock.code" :value="stock.code">{{ stock.name }} · {{ stock.code }}</option></select></label>
            <label class="field"><span>方向</span><select v-model="draft.direction"><option value="buy">买入计划</option><option value="sell">卖出计划</option></select></label>
            <label class="field"><span>有效期</span><select v-model="draft.validity"><option value="今日">今日</option><option value="本周内">本周内</option><option value="本月内">本月内</option></select></label>
            <label class="field"><span>计划价</span><div class="number-input"><input v-model.number="draft.entry" type="number" min="0.01" step="0.01" required><span>元</span></div></label>
            <label class="field"><span>止损价</span><div class="number-input"><input v-model.number="draft.stop" type="number" min="0.01" step="0.01" required><span>元</span></div></label>
            <label class="field"><span>目标价</span><div class="number-input"><input v-model.number="draft.target" type="number" min="0.01" step="0.01" required><span>元</span></div></label>
            <label class="field"><span>账户资金</span><div class="number-input"><input v-model.number="draft.capital" type="number" min="1000" step="1000" required><span>元</span></div></label>
            <label class="field"><span>计划仓位 <strong>{{ draft.position }}%</strong></span><input v-model.number="draft.position" type="range" min="5" max="100" step="5"></label>
          </div>
          <label class="field field-note"><span>交易逻辑</span><textarea v-model.trim="draft.note" rows="3" placeholder="例如：放量突破平台，回踩不破 5 日线再执行。"></textarea></label>
          <div class="risk-preview">
            <div class="risk-preview-heading"><span>计划测算</span><span class="muted-inline">按 100 股整数倍计算</span></div>
            <div class="risk-metrics"><div><span>盈亏比</span><strong>{{ planMetrics.rr.toFixed(2) }}</strong></div><div><span>预计股数</span><strong>{{ planMetrics.shares.toLocaleString() }} 股</strong></div><div><span>单笔最大风险</span><strong>{{ formatMoney(planMetrics.risk) }}</strong></div></div>
            <div class="risk-bar"><span :style="{ width: (Math.min(100, Math.max(8, planMetrics.rr / 3 * 100)) + '%') }"></span></div>
          </div>
          <div class="form-footer"><span class="form-footnote"><i data-lucide="cloud-upload" aria-hidden="true"></i>计划保存在本地浏览器与服务器，换设备打开自动同步</span><button class="button button-primary" type="submit"><i data-lucide="save" aria-hidden="true"></i>保存计划</button></div>
        </form>
      </section>

      <section class="plans-list-panel surface">
        <div class="surface-heading"><div><span class="section-kicker">ACTIVE PLANS</span><h3>执行中的计划</h3></div><button class="icon-button" type="button" aria-label="刷新计划状态" data-tooltip="刷新计划" @click="refreshAll()"><i data-lucide="refresh-cw" aria-hidden="true"></i></button></div>
        <div class="plan-list">
          <article v-for="plan in activePlans" :key="plan.id" class="plan-card">
            <div class="plan-card-head"><div class="plan-card-identity"><span class="stock-dot stock-dot-coral">{{ quoteFor(plan.code)?.name?.slice(0, 1) || plan.code.slice(0, 1) }}</span><div><strong>{{ quoteFor(plan.code)?.name || plan.code }}</strong><span>{{ plan.code }} · {{ plan.direction === 'buy' ? '买入计划' : '卖出计划' }}</span></div></div><span :class="['plan-status', plan.status === '已触发' ? 'plan-status-triggered' : '']">{{ plan.status }}</span></div>
            <div class="plan-card-body"><div class="plan-card-metric"><span>计划价</span><strong>{{ formatNumber(plan.entry) }}</strong></div><div class="plan-card-metric"><span>止损</span><strong>{{ formatNumber(plan.stop) }}</strong></div><div class="plan-card-metric"><span>目标</span><strong>{{ formatNumber(plan.target) }}</strong></div><div class="plan-card-metric"><span>盈亏比</span><strong>{{ calculateRr(plan).toFixed(2) }}</strong></div></div>
            <!-- Task 9 交易对关联：仅 sell 行显示（activePlans 已限定 执行中/已触发）；写路径 = updatePlanLinkage → 既有 workspace PUT -->
            <div v-if="plan.direction === 'sell'" class="plan-pairing" data-testid="plan-pairing">
              <label class="field"><span>关联建仓计划</span><select data-testid="pair-select" :value="plan.relatedPlan ?? ''" @change="onPairChange(plan, $event)"><option value="">{{ plan.relatedPlan ? '（解除关联）' : '（未关联）' }}</option><option v-for="buy in candidateBuys(plan)" :key="buy.id" :value="buy.id">{{ quoteFor(buy.code)?.name || buy.code }} · 计划价 {{ formatNumber(buy.entry) }}（{{ buy.id }}）</option></select></label>
              <label class="field"><span>离场模式</span><select data-testid="exit-mode-select" :value="plan.exitMode ?? 'race'" @change="onExitModeChange(plan, $event)"><option v-for="mode in EXIT_MODES" :key="mode.value" :value="mode.value">{{ mode.label }}</option></select></label>
            </div>
            <div class="plan-card-foot"><span>{{ plan.validity }} · {{ calculateShares(plan).toLocaleString() }} 股</span><div class="plan-card-actions"><button type="button" @click="monitorPlan(plan)">盯盘</button><button type="button" @click="archivePlan(plan.id)">归档</button></div></div>
          </article>
        </div>
        <div v-if="!activePlans.length" class="empty-state"><i data-lucide="clipboard-plus" aria-hidden="true"></i><strong>还没有交易计划</strong><span>先写下一个你愿意执行的交易剧本。</span></div>
      </section>

      <section class="review-panel surface">
        <button class="review-toggle" data-testid="review-toggle" type="button" @click="review.toggle()">
          <span>绩效复盘</span>
          <span v-if="review.review" class="muted">{{ reviewSummary }}</span>
          <i data-lucide="chevron-down" :class="{ flipped: review.expanded }"></i>
        </button>
        <template v-if="review.expanded">
          <p v-if="review.reviewError" class="plan-draft-error" data-testid="review-error" role="alert">{{ review.reviewError }}</p>
          <p v-if="review.review?.degraded?.length" class="muted" data-testid="review-degraded">以下代码使用本地历史兜底，数据可能陈旧：{{ review.review?.degraded?.join('、') }}</p>
          <div class="review-days">
            <button v-for="d in REVIEW_DAYS" :key="d" type="button"
                    :class="{ active: review.days === d }" @click="review.setDays(d)">
              {{ d === 0 ? '全部' : `近 ${d} 天` }}
            </button>
          </div>
          <div class="review-kpis" data-testid="review-kpis">
            <div class="kpi"><b>{{ review.review?.kpis.total ?? '--' }}</b><span>计划总数</span></div>
            <div class="kpi"><b>{{ review.formatRatio(review.review?.kpis.winRate) }}</b><span>胜率</span></div>
            <div class="kpi"><b>{{ review.formatR(review.review?.kpis.payoffRatio) }}</b><span>盈亏比</span></div>
            <div class="kpi"><b>{{ review.formatR(review.review?.kpis.expectancyR) }}</b><span>期望值 R</span></div>
            <div class="kpi"><b>{{ review.formatRatio(review.review?.kpis.notEnteredRate) }}</b><span>未入场率</span></div>
            <div class="kpi"><b>{{ review.review?.kpis.openCount ?? '--' }}</b><span>进行中</span></div>
            <span class="kpi-note" data-testid="review-fee-note">成本假设（可调，参考范围 0.1%–0.5%）：feeRate × 入场 ÷ 止损距离，近似值</span>
          </div>
          <div class="review-tabs">
            <button v-for="g in GROUPS" :key="g.key" data-testid="review-group-tab" type="button"
                    :class="{ active: review.activeGroup === g.key }" @click="review.setGroup(g.key)">{{ g.label }}</button>
          </div>
          <table class="review-table" data-testid="review-items">
            <thead><tr><th>分组</th><th>已决</th><th>胜</th><th>胜率</th><th>期望 R</th></tr></thead>
            <tbody>
              <tr v-for="row in activeRows" :key="row.key">
                <td>{{ row.label }} <span v-if="row.smallSample" class="badge-muted">样本不足，仅供参考</span></td>
                <td>{{ row.decided }}</td><td>{{ row.wins }}</td>
                <td>{{ review.formatRatio(row.winRate) }}</td>
                <td>{{ review.formatR(row.expectancyR) }}</td>
              </tr>
            </tbody>
          </table>
          <table class="review-table" data-testid="review-items-detail">
            <thead><tr><th>代码</th><th>来源</th><th><button type="button" @click="review.toggleSort('outcome')">结局</button></th><th><button type="button" @click="review.toggleSort('netR')">净 R</button></th><th>入场日</th><th>离场日</th></tr></thead>
            <tbody>
              <tr v-for="item in sortedDetail" :key="item.planId">
                <td>{{ item.code }}</td><td>{{ sourceLabel(item.source) }}</td>
                <td>{{ outcomeLabel(item) }}<span v-if="item.ambiguous" class="badge-muted">保守裁定</span><span v-if="item.gapFill" class="badge-muted">跳空</span><span v-if="item.limitDeferred" class="badge-muted">顺延</span></td>
                <td>{{ review.formatR(item.netR) }}</td><td>{{ item.entryDate ?? '--' }}</td><td>{{ item.exitDate ?? '--' }}</td>
              </tr>
            </tbody>
          </table>
          <p v-if="review.traceError" class="plan-draft-error" data-testid="review-trace-error" role="alert">{{ review.traceError }}</p>
          <div v-if="activeScanTrace.length" data-testid="review-trace" class="review-trace">
            <p class="muted">{{ traceSummary }}</p>
            <p v-for="(t, i) in activeScanTrace" :key="t.runAtMs ?? i" class="muted">{{ t.runAtMs == null ? '--' : formatTime(t.runAtMs) }} · {{ t.status }} · 命中 {{ t.hitCount }} / 新增 {{ t.newCount }}</p>
          </div>
          <p class="review-disclaimer" data-testid="review-disclaimer">设计口径回放，非实际成交；历史回放不代表未来；不构成投资建议。</p>
        </template>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { storeToRefs } from 'pinia';
import { formatMoney, formatNumber, formatTime } from '@/modules/format';
import { calculateRr, calculateShares } from '@/modules/planUtils';
import type { Plan } from '@/types/models';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { usePlansStore } from '@/stores/usePlansStore';
import { useReviewStore, type ReviewItem } from '@/stores/useReviewStore';

const workspace = useWorkspaceStore();
const quotes = useQuotesStore();
const plans = usePlansStore();
const review = useReviewStore();

const { activePlans, draftDirty } = storeToRefs(workspace);
const { refreshAll, renderIcons, showToast } = workspace;
const { draft, planOptions, planMetrics } = storeToRefs(plans);
const { quoteFor } = quotes;
const { switchView } = quotes;
const { savePlan, monitorPlan, archivePlan, updatePlanLinkage } = plans;

// ── Task 9 交易对关联：sell 行 → 关联建仓下拉 + exitMode 四档 ──
// 后端语义（storage.validate_plan_links）：仅 sell 可携带 relatedPlan；目标须存在/buy/同 code/非归档；
// 一 buy 至多被一 sell 关联（先到先得）。前端仅做简单过滤兜底，规则冲突以后端 422 为准。
const EXIT_MODES: Array<{ value: NonNullable<Plan['exitMode']>; label: string }> = [
  { value: 'race', label: '先到先平' },
  { value: 'sell_priority', label: '平仓单优先' },
  { value: 'sell_stop_only', label: '止损优先' },
  { value: 'sell_only', label: '仅平仓单' },
];

function candidateBuys(sell: Plan): Plan[] {
  const taken = new Set(
    workspace.plans
      .filter((item) => item.direction === 'sell' && item.id !== sell.id && item.relatedPlan)
      .map((item) => item.relatedPlan as string)
  );
  return workspace.plans.filter(
    (item) =>
      item.direction === 'buy' &&
      item.code === sell.code &&
      item.status !== '已归档' &&
      !taken.has(item.id)
  );
}

async function onPairChange(plan: Plan, ev: Event) {
  const select = ev.target as HTMLSelectElement;
  try {
    await updatePlanLinkage(plan.id, { relatedPlan: select.value || null });
  } catch (error: any) {
    // store 已回滚并重新入队同步；这里仅把 DOM 选择框拨回数据真值（无重渲染不会自动复原）
    select.value = plan.relatedPlan ?? '';
    showToast(error?.message || '计划关联保存失败', 'error');
  }
}

async function onExitModeChange(plan: Plan, ev: Event) {
  const select = ev.target as HTMLSelectElement;
  const mode = select.value as NonNullable<Plan['exitMode']>;
  if (mode === 'sell_only' && !window.confirm('切换为「仅平仓单（sell_only）」后，该卖出计划将仅由关联平仓单离场，无止损保护。确认切换？')) {
    select.value = plan.exitMode ?? 'race';
    return;
  }
  try {
    await updatePlanLinkage(plan.id, { exitMode: mode });
  } catch (error: any) {
    select.value = plan.exitMode ?? 'race';
    showToast(error?.message || '离场模式保存失败', 'error');
  }
}

// ── 绩效复盘（Task 8）：四维分组 + 明细排序 + 扫描留痕（store 的 syncTrace 在 fetchReview/setGroup 后自动触发，组件无额外 watch）
const GROUPS = [
  { key: 'source', label: '来源' },
  { key: 'direction', label: '方向' },
  { key: 'validity', label: '有效期' },
  { key: 'createdMonth', label: '创建月份' },
] as const;
const REVIEW_DAYS: Array<0 | 30 | 90> = [30, 90, 0];

const activeRows = computed(() => review.review?.groups[review.activeGroup] ?? []);
const reviewSummary = computed(() => {
  const k = review.review?.kpis;
  if (!k || k.decided === 0) return '暂无已了结计划';
  const daysLabel = review.days === 0 ? '全部' : `近 ${review.days} 天`;
  return `${daysLabel} ${k.decided} 份已了结计划，胜率 ${review.formatRatio(k.winRate)}`;
});
// 明细排序：outcome 按 localeCompare、netR 按数值（?? -Infinity）；
// 未选排序键 → 保持后端原序（plan_review.py 已按 createdAtMs 降序返回，且该字段不随 payload 下发）。
const sortedDetail = computed<ReviewItem[]>(() => {
  const items = [...(review.review?.items ?? [])];
  if (!review.sortKey) return items;
  const dir = review.sortDir === 'asc' ? 1 : -1;
  if (review.sortKey === 'outcome') {
    return items.sort((a, b) => dir * a.outcome.localeCompare(b.outcome));
  }
  return items.sort((a, b) => dir * ((a.netR ?? -Infinity) - (b.netR ?? -Infinity)));
});
const activeScanTrace = computed(() => review.trace ?? []);
const traceSummary = computed(() => {
  // 仅在 activeScanTrace.length > 0 时（见 review-trace 的 v-if）被读取，故空数组分支不可达（终审 F5）：
  // 除零由 v-if 保证，删除原不可达的 `if (!runs.length) return ...` 死分支。
  const runs = activeScanTrace.value;
  const avgHits = runs.reduce((sum, t) => sum + t.hitCount, 0) / runs.length;
  return `近 30 天运行 ${runs.length} 次 · 平均命中 ${avgHits.toFixed(1)}`;
});
function outcomeLabel(item: ReviewItem): string {
  switch (item.outcome) {
    case 'win': return '胜';
    case 'loss': return '败';
    case 'flat': return '平出';
    case 'notEntered': return '未入场';
    case 'open': return '进行中';
    case 'invalid': return '参数无效';
    default: return item.outcome;
  }
}
function sourceLabel(source: string): string {
  if (source.startsWith('scan:')) return `扫描·${source.slice(5)}`;
  if (source === 'legacy') return '早期计划';
  if (source === 'manual') return '手动新建';
  if (source === 'screener') return '策略命中';
  if (source === 'monitor') return '盯盘信号';
  return source;
}

onMounted(() => renderIcons());
</script>