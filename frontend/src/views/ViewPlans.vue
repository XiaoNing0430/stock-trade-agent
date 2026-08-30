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
            <div class="plan-card-foot"><span>{{ plan.validity }} · {{ calculateShares(plan).toLocaleString() }} 股</span><div class="plan-card-actions"><button type="button" @click="monitorPlan(plan)">盯盘</button><button type="button" @click="archivePlan(plan.id)">归档</button></div></div>
          </article>
        </div>
        <div v-if="!activePlans.length" class="empty-state"><i data-lucide="clipboard-plus" aria-hidden="true"></i><strong>还没有交易计划</strong><span>先写下一个你愿意执行的交易剧本。</span></div>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { inject, onMounted } from 'vue';
import { APP_CTX } from '@/modules/views/context';

const ctx = inject(APP_CTX)!;
const {
  activePlans,
  draft,
  draftDirty,
  planOptions,
  planMetrics,
  savePlan,
  formatMoney,
  formatNumber,
  quoteFor,
  calculateRr,
  calculateShares,
  monitorPlan,
  archivePlan,
  switchView,
  refreshAll,
  renderIcons,
} = ctx;
onMounted(() => renderIcons());
</script>