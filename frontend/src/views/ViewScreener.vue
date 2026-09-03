<template>
  <section class="view-panel is-active screener-view">
    <div class="view-heading">
      <div>
        <span class="section-kicker">SCREENING LAB</span>
        <h2>用真实行情筛出值得研究的标的</h2>
        <p class="heading-note">筛选字段来自行情列表：涨跌幅、PE、PB、量比和换手率。</p>
      </div>
      <div class="view-heading-actions">
        <span class="scan-time">行情列表 {{ screenerUpdatedLabel }}</span>
        <button class="button button-primary" type="button" @click="scanNow">
          <i data-lucide="play" aria-hidden="true"></i>
          重新扫描
        </button>
      </div>
    </div>

    <div class="screener-tabs">
      <button :class="['screener-tab', { 'is-active': screenerMode === 'featured' }]" type="button" @click="switchScreenerMode('featured')">精选 50</button>
      <button :class="['screener-tab', { 'is-active': screenerMode === 'all' }]" type="button" @click="switchScreenerMode('all')">全市场</button>
      <button :class="['screener-tab', { 'is-active': screenerMode === 'strategy' }]" type="button" @click="openStrategyTab()">策略</button>
    </div>

    <div v-if="screenerMode === 'strategy'" class="screener-layout">
      <section class="filter-panel surface">
        <div class="surface-heading">
          <div>
            <span class="section-kicker">PIPELINE</span>
            <h3>策略选股</h3>
          </div>
          <i data-lucide="git-branch" class="heading-icon" aria-hidden="true"></i>
        </div>
        <div class="field-grid">
          <label class="field">
            <span>策略</span>
            <select v-model="strategyName" class="input">
              <option v-for="s in strategies" :key="s.id" :value="s.id">{{ s.name }}</option>
            </select>
          </label>
          <div class="field">
            <span>模式</span>
            <div class="screener-tabs strategy-mode-tabs">
              <button :class="['screener-tab', { 'is-active': strategyRunMode === 'quick' }]" type="button" @click="switchStrategyMode('quick')">极速</button>
              <button :class="['screener-tab', { 'is-active': strategyRunMode === 'deep' }]" type="button" @click="switchStrategyMode('deep')">深度</button>
            </div>
          </div>
        </div>
        <p class="heading-note">{{ strategyDescription }}{{ strategyRunMode === 'deep' ? '（深度模式需逐票拉取历史数据，预计 10–30 秒）' : '' }}</p>
        <div class="filter-divider"></div>
        <button class="button button-primary" type="button" :disabled="strategyLoading" @click="runStrategy">
          <i data-lucide="play" aria-hidden="true"></i>
          {{ strategyLoading ? '计算中…' : '运行策略' }}
        </button>
      </section>

      <div class="results-panel surface">
        <div class="surface-heading">
          <div>
            <span class="section-kicker">RESULTS</span>
            <h3>命中结果 <span v-if="strategyReferenceDate" class="heading-note">基准日期 {{ strategyReferenceDate }}</span></h3>
          </div>
          <span v-if="strategyCached" class="scan-time">{{ strategyStale ? '⚠ 数据可能滞后（缓存降级）' : '缓存命中' }}</span>
        </div>
        <div v-if="strategyStale" class="empty-state"><i data-lucide="alert-triangle" aria-hidden="true"></i><strong>数据可能滞后</strong><span>数据源暂时不可用，以下为上次缓存结果，请稍后强制刷新。</span></div>
        <div class="table-responsive results-table-wrap">
          <table class="data-table data-table-dense">
            <thead><tr>
              <th>代码</th>
              <th>名称</th>
              <th class="text-end">评分</th>
              <th>达标因子</th>
              <th class="text-end">现价</th>
              <th class="text-end">涨跌幅</th>
              <th class="text-end">PE</th>
              <th class="text-end">PB</th>
              <th class="text-end">ROE</th>
              <th class="text-end">操作</th>
            </tr></thead>
            <tbody>
              <tr v-for="stock in strategyRows" :key="stock.code" class="clickable-row" @click="selectStock(stock.code)">
                <td>{{ stock.code }}</td>
                <td><div class="stock-cell"><span class="stock-dot stock-dot-blue">{{ stock.name.slice(0, 1) }}</span><div class="stock-cell-copy"><strong>{{ stock.name }}</strong></div></div></td>
                <td class="text-end"><strong>{{ stock.score ?? '--' }}</strong></td>
                <td><span v-for="tag in strategyFactorTags(stock)" :key="tag" class="sort-arrow factor-tag">{{ tag }}</span><span v-if="!strategyFactorTags(stock).length">--</span></td>
                <td class="text-end">{{ formatNullable(stock.price) }}</td>
                <td class="text-end" :class="trendClass(stock.changePct)">{{ formatPctNullable(stock.changePct) }}</td>
                <td class="text-end">{{ formatNullable(stock.pe, 1) }}</td>
                <td class="text-end">{{ formatNullable(stock.pb, 2) }}</td>
                <td class="text-end">{{ stock.roe != null ? stock.roe.toFixed(1) + '%' : '--' }}</td>
                <td class="text-end"><button class="table-action" type="button" :aria-label="isWatched(stock.code) ? '移出自选' : '加入自选'" :data-tooltip="isWatched(stock.code) ? '移出自选' : '加入自选'" @click.stop="toggleWatch(stock.code)"><i :data-lucide="isWatched(stock.code) ? 'star-off' : 'star'" aria-hidden="true"></i></button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="strategyLoading" class="empty-state"><i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在运行策略</strong><span>{{ strategyRunMode === 'deep' ? '深度模式需逐票计算因子，请稍候。' : '极速模式筛选中…' }}</span></div>
        <div v-else-if="!strategyRows.length" class="empty-state"><i data-lucide="search-x" aria-hidden="true"></i><strong>暂无结果</strong><span>点击「运行策略」开始选股。</span></div>
      </div>
    </div>

    <div v-if="screenerMode === 'featured'" class="screener-layout">
      <section class="filter-panel surface">
        <div class="surface-heading">
          <div>
            <span class="section-kicker">STRATEGY</span>
            <h3>筛选策略</h3>
          </div>
          <i data-lucide="sparkles" class="heading-icon" aria-hidden="true"></i>
        </div>
        <div class="preset-list">
          <button v-for="preset in presets" :key="preset.name" class="preset-item" :class="{ 'is-active': presetName === preset.name }" type="button" @click="applyPreset(preset)">
            <span :class="['preset-icon', preset.iconClass]"><i :data-lucide="preset.icon" aria-hidden="true"></i></span>
            <span><strong>{{ preset.name }}</strong><small>{{ preset.description }}</small></span>
            <i data-lucide="check" class="preset-check" aria-hidden="true"></i>
          </button>
        </div>

        <div class="filter-divider"></div>
        <div class="filter-fields">
          <label class="field"><span>交易所</span><select v-model="filters.exchange"><option value="全部">全部交易所</option><option value="上交所">上交所</option><option value="深交所">深交所</option><option value="北交所">北交所</option></select></label>
          <label class="field"><span>板块</span><select v-model="filters.market"><option value="全部">全部板块</option><option value="沪深主板">沪深主板</option><option value="创业板">创业板</option><option value="科创板">科创板</option><option value="北交所">北交所</option><option value="沪市ETF">沪市 ETF</option><option value="深市ETF">深市 ETF</option><option value="科创板ETF">科创板 ETF</option></select></label>
          <label class="field"><span>搜索</span><input v-model.trim="filters.search" type="search" placeholder="代码 / 名称"></label>
          <label class="field"><span>PE ≤ <strong>{{ filters.peMax }}</strong></span><input v-model.number="filters.peMax" type="range" min="5" max="120" step="1"></label>
          <label class="field"><span>PB ≤ <strong>{{ filters.pbMax }}</strong></span><input v-model.number="filters.pbMax" type="range" min="0.5" max="20" step="0.5"></label>
          <label class="field"><span>量比 ≥ <strong>{{ filters.volumeMin.toFixed(2) }}</strong></span><input v-model.number="filters.volumeMin" type="range" min="0.2" max="8" step="0.1"></label>
          <label class="field"><span>涨幅 ≥ <strong>{{ filters.changeMin.toFixed(1) }}%</strong></span><input v-model.number="filters.changeMin" type="range" min="-10" max="10" step="0.1"></label>
        </div>
        <div class="filter-footer">
          <span class="filter-hint"><i data-lucide="info" aria-hidden="true"></i>实时字段缺失时不会用模拟值补齐</span>
          <button class="button button-secondary" type="button" @click="resetFilters">重置</button>
        </div>
      </section>

      <section class="results-panel surface">
        <div class="surface-heading results-heading">
          <div>
            <span class="section-kicker">RESULTS</span>
            <h3><span>{{ filteredRows.length }}</span> 只股票符合条件</h3>
          </div>
          <div class="results-actions">
            <span class="muted-count">候选池 {{ screenTotal.toLocaleString() }} 只</span>
            <button class="icon-button" type="button" aria-label="导出筛选结果" data-tooltip="导出结果" @click="exportResults">
              <i data-lucide="download" aria-hidden="true"></i>
            </button>
          </div>
        </div>
        <div class="result-insight">
          <div class="insight-icon"><i data-lucide="lightbulb" aria-hidden="true"></i></div>
          <div><strong>{{ presetName }}</strong><span>{{ presetDescription }}</span></div>
        </div>
        <div class="table-responsive results-table-wrap">
          <table class="data-table data-table-dense">
            <thead><tr><th>股票</th><th class="text-end">现价</th><th class="text-end">涨跌幅</th><th class="text-end">PE</th><th class="text-end">PB</th><th class="text-end">量比</th><th class="text-end">换手率</th><th>信号</th><th class="text-end">操作</th></tr></thead>
            <tbody>
              <tr v-for="stock in filteredRows" :key="stock.code" class="clickable-row" @click="selectStock(stock.code)">
                <td><div class="stock-cell"><span class="stock-dot stock-dot-blue">{{ stock.name.slice(0, 1) }}</span><div class="stock-cell-copy"><strong>{{ stock.name }}</strong><span>{{ stock.code }} · {{ stock.exchange }} · {{ stock.board }}</span></div></div></td>
                <td class="text-end">{{ formatNullable(stock.price) }}</td>
                <td class="text-end" :class="trendClass(stock.change)">{{ formatPctNullable(stock.change) }}</td>
                <td class="text-end">{{ formatNullable(stock.pe, 1) }}</td>
                <td class="text-end">{{ formatNullable(stock.pb, 2) }}</td>
                <td class="text-end">{{ formatNullable(stock.volumeRatio, 2) }}</td>
                <td class="text-end">{{ formatNullable(stock.turnoverRate, 2) }}%</td>
                <td><span :class="['signal-chip', signalClass(stock)]">{{ signalText(stock) }}</span></td>
                <td class="text-end"><button class="table-action" type="button" :aria-label="isWatched(stock.code) ? '移出自选' : '加入自选'" :data-tooltip="isWatched(stock.code) ? '移出自选' : '加入自选'" @click.stop="toggleWatch(stock.code)"><i :data-lucide="isWatched(stock.code) ? 'star-off' : 'star'" aria-hidden="true"></i></button></td>
              </tr>
            </tbody>
          </table>
        </div>
        <div v-if="loading && !filteredRows.length" class="empty-state"><i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在读取真实行情</strong><span>行情列表返回后会显示筛选结果。</span></div>
        <div v-else-if="!filteredRows.length" class="empty-state"><i data-lucide="search-x" aria-hidden="true"></i><strong>没有找到符合条件的股票</strong><span>可以放宽 PE、PB 或涨幅条件再试一次。</span></div>
      </section>
    </div>

    <div v-else class="all-market-panel surface">
      <div class="surface-heading results-heading">
        <div>
          <span class="section-kicker">FULL MARKET</span>
          <h3><span>{{ screenerAllTotal.toLocaleString() }}</span> 只沪深 A 股</h3>
        </div>
        <div class="results-actions">
          <span class="muted-count">第 {{ screenerPage }} 页 · 每页 50 只</span>
          <button class="icon-button" type="button" aria-label="刷新全市场" data-tooltip="刷新全市场" @click="scanNow">
            <i data-lucide="refresh-cw" aria-hidden="true"></i>
          </button>
        </div>
      </div>
      <div class="table-responsive results-table-wrap">
        <table class="data-table data-table-dense">
          <thead><tr>
            <th class="screener-sort" @click="screenerSort('code')">代码 <span class="sort-arrow">{{ screenerSortIcon('code') }}</span></th>
            <th>名称</th>
            <th class="text-end screener-sort" @click="screenerSort('price')">现价 <span class="sort-arrow">{{ screenerSortIcon('price') }}</span></th>
            <th class="text-end screener-sort" @click="screenerSort('changePct')">涨跌幅 <span class="sort-arrow">{{ screenerSortIcon('changePct') }}</span></th>
            <th class="text-end screener-sort" @click="screenerSort('amount')">成交额 <span class="sort-arrow">{{ screenerSortIcon('amount') }}</span></th>
            <th class="text-end">换手率</th>
            <th class="text-end">量比</th>
            <th class="text-end">PE</th>
            <th class="text-end">PB</th>
            <th class="text-end">总市值</th>
            <th class="text-end">主力净流入</th>
            <th class="text-end">操作</th>
          </tr></thead>
          <tbody>
            <tr v-for="stock in screenerAllRows" :key="stock.symbol" class="clickable-row" @click="selectStock(stock.code)">
              <td>{{ stock.code }}</td>
              <td><div class="stock-cell"><span class="stock-dot stock-dot-blue">{{ stock.name.slice(0, 1) }}</span><div class="stock-cell-copy"><strong>{{ stock.name }}</strong></div></div></td>
              <td class="text-end">{{ formatNullable(stock.price) }}</td>
              <td class="text-end" :class="trendClass(stock.changePct)">{{ formatPctNullable(stock.changePct) }}</td>
              <td class="text-end">{{ formatAmount(stock.amount) }}</td>
              <td class="text-end">{{ formatNullable(stock.turnoverRate, 2) }}%</td>
              <td class="text-end">{{ formatNullable(stock.volumeRatio, 2) }}</td>
              <td class="text-end">{{ formatNullable(stock.peTtm, 1) }}</td>
              <td class="text-end">{{ formatNullable(stock.pb, 2) }}</td>
              <td class="text-end">{{ stock.totalMarketCap != null ? stock.totalMarketCap.toLocaleString() + ' 亿' : '--' }}</td>
              <td class="text-end" :class="trendClass(stock.netMoneyFlow)">{{ stock.netMoneyFlow != null ? stock.netMoneyFlow.toLocaleString() + ' 万' : '--' }}</td>
              <td class="text-end"><button class="table-action" type="button" :aria-label="isWatched(stock.code) ? '移出自选' : '加入自选'" :data-tooltip="isWatched(stock.code) ? '移出自选' : '加入自选'" @click.stop="toggleWatch(stock.code)"><i :data-lucide="isWatched(stock.code) ? 'star-off' : 'star'" aria-hidden="true"></i></button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="screenerLoading" class="empty-state"><i data-lucide="loader-circle" aria-hidden="true"></i><strong>正在读取全市场行情</strong><span>腾讯排名接口返回后会显示结果。</span></div>
      <div v-else-if="!screenerAllRows.length" class="empty-state"><i data-lucide="search-x" aria-hidden="true"></i><strong>暂时没有数据</strong><span>全市场排名接口暂时不可用，请稍后重试。</span></div>
      <div class="pagination">
        <button class="button button-secondary" type="button" :disabled="screenerPage <= 1" @click="screenerPageDown"><i data-lucide="chevron-left" aria-hidden="true"></i>上一页</button>
        <span class="pagination-info">{{ screenerPage }} / {{ Math.max(1, Math.ceil(screenerAllTotal / 50)) }}</span>
        <button class="button button-secondary" type="button" :disabled="screenerPage >= Math.ceil(screenerAllTotal / 50)" @click="screenerPageUp">下一页<i data-lucide="chevron-right" aria-hidden="true"></i></button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted } from 'vue';
import { storeToRefs } from 'pinia';
import { formatNullable, formatPctNullable, formatAmount, trendClass } from '@/modules/format';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { useScreenerStore } from '@/stores/useScreenerStore';
import { usePlansStore } from '@/stores/usePlansStore';

const workspace = useWorkspaceStore();
const quotes = useQuotesStore();
const screener = useScreenerStore();
const plans = usePlansStore();

const {
  screenerUpdatedLabel, screenerMode, presets, presetName, filters, filteredRows, screenTotal,
  presetDescription, screenerAllRows, screenerAllTotal, screenerPage, screenerLoading,
  strategies, strategyName, strategyRunMode, strategyRows, strategyLoading, strategyCached,
  strategyStale, strategyReferenceDate,
} = storeToRefs(screener);
const { loading } = storeToRefs(quotes);
const { signalClass, signalText } = plans;
const {
  switchScreenerMode, applyPreset, resetFilters, exportResults, screenerSort, screenerSortIcon,
  screenerPageUp, screenerPageDown, scanNow, runStrategy, switchStrategyMode, strategyFactorTags, loadStrategies,
} = screener;
const { selectStock, isWatched, toggleWatch } = quotes;
const { renderIcons } = workspace;

const strategyDescription = computed(
  () => strategies.value.find((s: any) => s.id === strategyName.value)?.description || ''
);

/** 切到策略 tab：加载策略列表（幂等），首次进入自动空态提示。 */
function openStrategyTab() {
  if (screenerMode.value === 'strategy') return;
  screenerMode.value = 'strategy';
  if (!strategies.value.length) loadStrategies();
}

onMounted(() => renderIcons());
</script>