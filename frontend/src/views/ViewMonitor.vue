<template>
  <section class="view-panel is-active">
    <div class="view-heading">
      <div><span class="section-kicker">MONITORING CENTER</span><h2>盯住规则，不盯住情绪</h2><p class="heading-note">添加标的并开启自动扫描，触发结果统一进入个人中心提醒中心。</p></div>
      <div class="view-heading-actions"><div class="monitor-toggle-wrap"><span class="toggle-label" :style="{ color: hasWatchTargets && monitorEnabled ? 'var(--green)' : 'var(--muted)' }">{{ monitorStatusLabel }}</span><label class="toggle"><input v-model="monitorEnabled" type="checkbox"><span class="toggle-track"><span></span></span></label></div><button v-if="hasWatchTargets" class="button button-secondary" type="button" @click="scanNow"><i data-lucide="radar" aria-hidden="true"></i>立即扫描</button><button v-else class="button button-primary" type="button" @click="switchView('screener')"><i data-lucide="scan-search" aria-hidden="true"></i>添加标的</button></div>
    </div>
    <div class="monitor-summary-row">
      <div class="monitor-stat"><span class="monitor-stat-label">监控标的</span><strong>{{ watchlistCodes.length }}</strong><span>只</span></div>
      <div class="monitor-stat"><span class="monitor-stat-label">下一次扫描</span><strong>{{ monitorNextScan }}</strong><span>{{ hasWatchTargets ? '自动' : '待配置' }}</span></div>
      <div class="monitor-stat monitor-stat-source"><span class="monitor-stat-label">行情源</span><strong><span class="live-dot"></span>{{ providerLabel }}</strong><span>{{ fetchedLabel }}</span></div>
    </div>
    <div class="monitor-layout">
      <section class="monitor-table-panel surface">
        <div class="surface-heading"><div><span class="section-kicker">LIVE WATCH</span><h3>盯盘列表</h3></div><button class="text-button" type="button" @click="switchView('screener')">添加标的 <i data-lucide="plus" aria-hidden="true"></i></button></div>
        <div v-if="hasWatchTargets" class="table-responsive">
          <table class="data-table monitor-table">
            <thead><tr><th>股票</th><th class="text-end">最新价</th><th class="text-end">涨跌幅</th><th>计划价</th><th>止损 / 目标</th><th>状态</th><th class="text-end">操作</th></tr></thead>
            <tbody>
              <tr v-for="stock in watchlistQuotes" :key="stock.code" class="clickable-row" @click="selectStock(stock.code)">
                <td><div class="stock-cell"><span class="stock-dot stock-dot-coral">{{ stock.name.slice(0, 1) }}</span><div class="stock-cell-copy"><strong>{{ stock.name }}</strong><span>{{ stock.code }} · {{ stock.exchange }} · {{ stock.board }}</span></div></div></td>
                <td class="text-end">{{ formatNullable(stock.price) }}</td>
                <td class="text-end" :class="trendClass(stock.change)">{{ formatPctNullable(stock.change) }}</td>
                <td><span v-if="planFor(stock.code)" class="price-levels"><span><i class="entry-dot"></i>{{ formatNumber(planFor(stock.code).entry) }}</span></span><span v-else class="muted-count">未设定</span></td>
                <td><span v-if="planFor(stock.code)" class="price-levels"><span><i class="stop-dot"></i>{{ formatNumber(planFor(stock.code).stop) }}</span><span><i class="target-dot"></i>{{ formatNumber(planFor(stock.code).target) }}</span></span><span v-else class="muted-count">先创建计划</span></td>
                <td><span :class="['signal-chip', signalClass(stock)]">{{ signalText(stock) }}</span></td>
                <td class="text-end"><button class="table-action" type="button" aria-label="移出自选" data-tooltip="移出自选" @click.stop="toggleWatch(stock.code)"><i data-lucide="x" aria-hidden="true"></i></button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-else class="empty-state"><i data-lucide="radar" aria-hidden="true"></i><strong>先添加监控标的</strong><span>从选股器加入一只股票，再为它设定价格规则。</span><button class="button button-primary" type="button" @click="switchView('screener')"><i data-lucide="scan-search" aria-hidden="true"></i>去选股器添加标的</button></div>
      </section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { inject, onMounted } from 'vue';
import { APP_CTX } from '@/modules/views/context';

const ctx = inject(APP_CTX)!;
const {
  monitorStatusLabel,
  hasWatchTargets,
  monitorEnabled,
  scanNow,
  switchView,
  watchlistCodes,
  monitorNextScan,
  providerLabel,
  fetchedLabel,
  watchlistQuotes,
  selectStock,
  formatNullable,
  formatPctNullable,
  formatNumber,
  trendClass,
  planFor,
  signalText,
  signalClass,
  toggleWatch,
  renderIcons,
} = ctx;

onMounted(() => renderIcons());
</script>