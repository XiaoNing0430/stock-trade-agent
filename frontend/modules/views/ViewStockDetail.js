// ViewStockDetail — 个股详情视图组件（P3-1 方案 B，B3 迁移）
// 注意：项目无打包器，Vue 通过全局脚本加载，只能从 window.Vue 解构，不能 import from 'vue'。
import { APP_CTX } from './context.js';

const { inject, onMounted } = Vue;

export default {
  name: 'ViewStockDetail',
  template: `
    <section class="view-panel is-active">
      <div class="view-heading">
        <div>
          <span class="section-kicker">STOCK DETAIL</span>
          <h2>{{ selectedStock?.name || '个股详情' }}</h2>
          <p class="heading-note">{{ selectedStock ? (selectedStock.code + ' · ' + selectedStock.exchange + ' · ' + selectedStock.board) : '选择一只股票' }}</p>
        </div>
        <div class="view-heading-actions">
          <button class="button button-secondary" type="button" @click="backFromDetail"><i data-lucide="arrow-left" aria-hidden="true"></i>返回</button>
        </div>
      </div>
      <section class="selected-stock-panel surface">
        <div class="selected-stock-summary">
          <div class="selected-stock-identity">
            <div class="stock-avatar">{{ selectedStock?.name?.slice(0, 1) || '—' }}</div>
            <div>
              <div class="stock-name-line"><h3>{{ selectedStock?.name || '选择一只股票' }}</h3><span class="ticker-code">{{ selectedStock ? (selectedStock.code + ' · ' + selectedStock.exchange + ' · ' + selectedStock.board) : '从列表中选择' }}</span></div>
              <span class="stock-sector">{{ selectedStock ? ('PE ' + formatNullable(selectedStock.pe, 1) + ' · PB ' + formatNullable(selectedStock.pb, 2)) : '暂无报价' }}</span>
            </div>
          </div>
          <div class="selected-stock-quote"><strong>{{ formatNullable(selectedStock?.price) }}</strong><span :class="trendClass(selectedStock?.change)">{{ formatPctNullable(selectedStock?.change) }}</span></div>
          <div class="selected-stock-metrics">
            <div><span>开盘</span><strong>{{ formatNullable(selectedStock?.open) }}</strong></div>
            <div><span>最高 / 最低</span><strong>{{ formatNullable(selectedStock?.high) }} / {{ formatNullable(selectedStock?.low) }}</strong></div>
            <div><span>成交额</span><strong>{{ formatAmount(selectedStock?.amount) }}</strong></div>
          </div>
          <div class="selected-stock-actions">
            <button class="button button-secondary" type="button" @click="toggleWatch(selectedCode)"><i :data-lucide="isWatched(selectedCode) ? 'star-off' : 'star'" aria-hidden="true"></i>{{ isWatched(selectedCode) ? '移出自选' : '加入自选' }}</button>
            <button class="button button-secondary" type="button" @click="openGridStrategy(selectedCode)"><i data-lucide="grid-3x3" aria-hidden="true"></i>网格策略</button>
            <button class="button button-primary" type="button" @click="createPlan(selectedCode)"><i data-lucide="clipboard-pen-line" aria-hidden="true"></i>制定计划</button>
          </div>
        </div>
        <div class="stock-detail-chart" v-html="chartSvg(selectedHistory.map(item => item.close), '#3b6fb6', (selectedStock?.name || '股票') + '近期走势')"></div>
        <div class="chart-source-row"><span :class="['source-badge', { 'source-badge-local': chartDataSource === 'local' }]">{{ chartDataSource === 'local' ? '本地缓存' : '实时·腾讯' }}</span></div>
      </section>
    </section>
  `,
  setup() {
    const ctx = inject(APP_CTX);
    const {
      selectedStock,
      selectedCode,
      backFromDetail,
      toggleWatch,
      isWatched,
      openGridStrategy,
      createPlan,
      formatNullable,
      formatPctNullable,
      formatAmount,
      trendClass,
      chartSvg,
      selectedHistory,
      chartDataSource,
      renderIcons,
    } = ctx;

    onMounted(() => renderIcons());

    return {
      selectedStock,
      selectedCode,
      backFromDetail,
      toggleWatch,
      isWatched,
      openGridStrategy,
      createPlan,
      formatNullable,
      formatPctNullable,
      formatAmount,
      trendClass,
      chartSvg,
      selectedHistory,
      chartDataSource,
      renderIcons,
    };
  },
};
