// ViewOverview — 总览视图组件（P3-1 方案 B，B2 迁移）
// 注意：项目无打包器，Vue 通过全局脚本加载，只能从 window.Vue 解构，不能 import from 'vue'。
import { APP_CTX } from './context.js';

const { inject, onMounted } = Vue;

export default {
  name: 'ViewOverview',
  template: `
    <section class="view-panel is-active">
      <div class="view-heading">
        <div>
          <span class="section-kicker">TRADING DESK</span>
          <h2>今日交易台</h2>
          <p class="heading-note">市场怎样、有什么机会、策略是否可靠、当前有哪些风险。</p>
        </div>
        <div class="view-heading-actions">
          <span class="data-updated"><span class="live-dot"></span>{{ fetchedLabel }}</span>
          <span class="strategy-label">{{ todayLabel }}</span>
        </div>
      </div>

      <div v-if="errorMessage" class="connection-banner">
        <i data-lucide="triangle-alert" aria-hidden="true"></i>
        <span>{{ errorMessage }}</span>
        <button class="text-button" type="button" @click="refreshAll()">重试</button>
      </div>

      <div class="desk-kpis">
        <section class="desk-kpi surface">
          <span class="desk-kpi-label">市场状态</span>
          <strong :class="trendClass(selectedIndex?.change)">{{ selectedIndex ? formatPct(selectedIndex.change) : '--' }}</strong>
          <span class="desk-kpi-note">上证指数 {{ selectedIndex ? formatNumber(selectedIndex.price) : '--' }} · {{ marketStatus }}</span>
        </section>
        <section class="desk-kpi surface">
          <span class="desk-kpi-label">候选数量</span>
          <strong>{{ screenRows.length }}</strong>
          <span class="desk-kpi-note">当前条件命中 {{ filteredRows.length }} 只 · {{ presetName }}</span>
        </section>
        <section class="desk-kpi surface">
          <span class="desk-kpi-label">运行中策略</span>
          <strong>{{ strategyStats.running }}</strong>
          <span class="desk-kpi-note">待重新回测 {{ strategyStats.pending }} 个 · 样本外超额 {{ strategyStats.latestExcess != null ? formatPct(strategyStats.latestExcess) : '--' }}</span>
        </section>
        <section class="desk-kpi surface">
          <span class="desk-kpi-label">待处理提醒</span>
          <strong>{{ unreadAlerts }}</strong>
          <span class="desk-kpi-note">活跃计划 {{ riskStats.active }} 份 · 止损触及 {{ riskStats.stopHit }}</span>
        </section>
      </div>

      <div class="desk-workspaces">
        <section class="desk-panel surface">
          <div class="surface-heading">
            <div>
              <span class="section-kicker">OPPORTUNITIES</span>
              <h3>发现机会</h3>
            </div>
            <span class="strategy-label">{{ presetName }}</span>
          </div>
          <div class="preset-hits">
            <button v-for="preset in presetHits" :key="preset.name" class="preset-hit" type="button" @click="applyPreset(preset); switchView('screener')">
              <span :class="['preset-icon', preset.iconClass]"><i :data-lucide="preset.icon" aria-hidden="true"></i></span>
              <span class="preset-hit-name">{{ preset.name }}</span>
              <strong class="preset-hit-count">{{ preset.count }}</strong>
            </button>
          </div>
          <div class="mini-stock-list">
            <div v-for="stock in filteredRows.slice(0, 4)" :key="stock.code" class="mini-stock-item" @click="selectStock(stock.code)">
              <span class="stock-dot stock-dot-blue">{{ stock.name.slice(0, 1) }}</span>
              <div class="mini-stock-copy"><strong>{{ stock.name }}</strong><span>{{ stock.code }} · 量比 {{ formatNullable(stock.volumeRatio, 2) }}</span></div>
              <span class="mini-stock-change" :class="trendClass(stock.change)">{{ formatPctNullable(stock.change) }}</span>
            </div>
            <div v-if="!filteredRows.length" class="empty-state compact-empty"><span>当前条件下暂无结果。</span></div>
          </div>
          <button class="button button-primary button-full" type="button" @click="switchView('screener')">
            <i data-lucide="scan-search" aria-hidden="true"></i>
            进入选股器
          </button>
        </section>

        <section class="desk-panel surface">
          <div class="surface-heading">
            <div>
              <span class="section-kicker">STRATEGY VALIDATION</span>
              <h3>验证策略</h3>
            </div>
          </div>
          <div class="desk-stat-rows">
            <div class="desk-stat-row"><span>运行中策略</span><strong>{{ strategyStats.running }}</strong></div>
            <div class="desk-stat-row"><span>待重新回测</span><strong>{{ strategyStats.pending }}</strong></div>
            <div class="desk-stat-row"><span>最近样本外超额</span><strong :class="trendClass(strategyStats.latestExcess)">{{ strategyStats.latestExcess != null ? formatPct(strategyStats.latestExcess) : '--' }}</strong></div>
          </div>
          <div v-if="!gridStrategies.length" class="empty-state compact-empty"><span>还没有保存的网格策略。</span></div>
          <button class="button button-secondary button-full" type="button" @click="openGridStrategy()">
            <i data-lucide="grid-3x3" aria-hidden="true"></i>
            进入网格策略
          </button>
        </section>

        <section class="desk-panel surface">
          <div class="surface-heading">
            <div>
              <span class="section-kicker">EXECUTION RISK</span>
              <h3>执行跟踪</h3>
            </div>
          </div>
          <div class="desk-stat-rows">
            <div class="desk-stat-row"><span>活跃计划</span><strong>{{ riskStats.active }}</strong></div>
            <div class="desk-stat-row desk-stat-row-risk"><span>触及止损</span><strong>{{ riskStats.stopHit }}</strong></div>
            <div class="desk-stat-row"><span>未读提醒</span><strong>{{ unreadAlerts }}</strong></div>
          </div>
          <div class="activity-list">
            <div v-for="alert in alerts.slice(0, 2)" :key="alert.id" class="activity-item">
              <div :class="['activity-icon', alert.kind === 'alert' ? 'alert' : alert.kind === 'success' ? 'success' : '']">
                <i :data-lucide="alert.kind === 'success' ? 'check-circle-2' : alert.kind === 'alert' ? 'triangle-alert' : alert.kind === 'system' ? 'wrench' : 'bell-ring'" aria-hidden="true"></i>
              </div>
              <div class="activity-copy"><strong>{{ alert.title }}</strong><span>{{ alert.message }}</span></div>
            </div>
            <div v-if="!alerts.length" class="empty-state compact-empty"><span>还没有提醒动态。</span></div>
          </div>
          <button class="button button-primary button-full" type="button" @click="switchView('monitor')">
            <i data-lucide="radar" aria-hidden="true"></i>
            进入盯盘提醒
          </button>
        </section>
      </div>

      <section class="market-board surface">
        <div class="surface-heading">
          <div>
            <span class="section-kicker">MARKET PULSE</span>
            <h3>盘面温度</h3>
          </div>
          <button class="icon-button" type="button" aria-label="打开盯盘中心" data-tooltip="盯盘中心" @click="switchView('monitor')">
            <i data-lucide="arrow-up-right" aria-hidden="true"></i>
          </button>
        </div>

        <div v-if="indices.length" class="index-grid">
          <div v-for="index in indices" :key="index.code" class="index-item">
            <div class="index-item-head">
              <span>{{ index.name }}</span>
              <i data-lucide="activity" aria-hidden="true"></i>
            </div>
            <strong class="index-item-value">{{ formatNumber(index.price) }}</strong>
            <div class="index-item-foot">
              <span>{{ index.market }}</span>
              <span :class="trendClass(index.change)">{{ formatPct(index.change) }}</span>
            </div>
          </div>
        </div>
        <div v-else-if="loading" class="empty-state compact-empty">
          <i data-lucide="loader-circle" aria-hidden="true"></i>
          <strong>正在读取指数</strong>
          <span>行情代理返回后会显示最新价。</span>
        </div>
        <div v-else class="empty-state compact-empty">
          <i data-lucide="chart-no-axes-combined" aria-hidden="true"></i>
          <strong>暂未获得指数报价</strong>
          <button class="text-button" type="button" @click="refreshAll()">刷新行情</button>
        </div>

        <div class="market-chart-wrap">
          <div class="chart-heading">
            <div>
              <span class="chart-label">上证指数 · 近 40 个交易日</span>
              <strong>{{ selectedIndex ? formatNumber(selectedIndex.price) : '--' }}</strong>
            </div>
            <span :class="trendClass(selectedIndex?.change)">{{ selectedIndex ? formatPct(selectedIndex.change) : '--' }}</span>
          </div>
          <div class="market-chart" v-html="chartSvg(indexHistory.map(item => item.close), '#ef6d53', '上证指数近 40 个交易日走势')"></div>
        </div>

        <div class="market-breadth">
          <div class="breadth-label">
            <span>已加载候选池涨跌</span>
            <strong>{{ breadth.up }} / {{ breadth.down }}</strong>
          </div>
          <div class="breadth-bar" aria-label="已加载候选池上涨家数与下跌家数">
            <span class="breadth-up" :style="{ width: (breadth.upRatio + '%') }"></span>
            <span class="breadth-flat" :style="{ width: (breadth.flatRatio + '%') }"></span>
            <span class="breadth-down" :style="{ width: (breadth.downRatio + '%') }"></span>
          </div>
          <div class="breadth-legend">
            <span><i class="legend-dot up"></i>上涨 {{ breadth.up }}</span>
            <span><i class="legend-dot flat"></i>平盘 {{ breadth.flat }}</span>
            <span><i class="legend-dot down"></i>下跌 {{ breadth.down }}</span>
          </div>
        </div>
      </section>
    </section>
  `,
  setup() {
    const ctx = inject(APP_CTX);
    const {
      fetchedLabel,
      todayLabel,
      errorMessage,
      refreshAll,
      selectedIndex,
      indices,
      marketStatus,
      loading,
      indexHistory,
      breadth,
      chartSvg,
      screenRows,
      filteredRows,
      presetName,
      presetHits,
      strategyStats,
      riskStats,
      unreadAlerts,
      gridStrategies,
      openGridStrategy,
      alerts,
      applyPreset,
      switchView,
      selectStock,
      formatNumber,
      formatPct,
      formatNullable,
      formatPctNullable,
      trendClass,
      renderIcons,
    } = ctx;

    onMounted(() => renderIcons());

    return {
      fetchedLabel,
      todayLabel,
      errorMessage,
      refreshAll,
      selectedIndex,
      indices,
      marketStatus,
      loading,
      indexHistory,
      breadth,
      chartSvg,
      screenRows,
      filteredRows,
      presetName,
      presetHits,
      strategyStats,
      riskStats,
      unreadAlerts,
      gridStrategies,
      openGridStrategy,
      alerts,
      applyPreset,
      switchView,
      selectStock,
      formatNumber,
      formatPct,
      formatNullable,
      formatPctNullable,
      trendClass,
      renderIcons,
    };
  },
};
