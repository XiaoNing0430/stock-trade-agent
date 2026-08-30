<template>
  <section class="view-panel is-active">
    <div class="view-heading">
      <div><span class="section-kicker">STRATEGY LAB</span><h2>{{ strategyType === 'grid' ? '让区间交易有数据依据' : (strategyTypeLabel + '策略回测') }}</h2><p class="heading-note">{{ strategyType === 'grid' ? '基于复权日线测算区间并回测。结果仅用于研究，不代表未来收益。' : ('基于复权日线回测' + strategyTypeLabel + '策略。结果仅用于研究，不代表未来收益。') }}</p></div>
      <div v-if="strategyType === 'grid'" class="view-heading-actions"><button class="button button-secondary" type="button" :disabled="gridLoading || !hasGridSuggestion" @click="optimizeGrid"><i data-lucide="sliders-horizontal" aria-hidden="true"></i>优化参数</button><button v-if="hasGridResult" class="button button-primary" type="button" :disabled="gridLoading" @click="backtestGrid(true)"><i data-lucide="save" aria-hidden="true"></i>保存策略</button><button v-else-if="hasGridSuggestion" class="button button-primary" type="button" :disabled="gridLoading" @click="backtestGrid()"><i data-lucide="play" aria-hidden="true"></i>开始回测</button><button v-else class="button button-primary" type="button" :disabled="gridLoading" @click="previewGrid"><i data-lucide="sparkles" aria-hidden="true"></i>生成策略建议</button></div>
    </div>
    <div class="strategy-tabs" role="tablist" aria-label="策略类型">
      <button v-for="item in STRATEGY_TYPES" :key="item.id" type="button" role="tab" :class="['strategy-tab', { 'is-active': strategyType === item.id }]" :aria-selected="strategyType === item.id" @click="switchStrategyType(item.id)"><i :data-lucide="item.id === 'grid' ? 'grid-3x3' : item.id === 'ma_cross' ? 'trending-up' : item.id === 'dca' ? 'calendar-clock' : 'activity'" aria-hidden="true"></i><span>{{ item.label }}</span></button>
    </div>
    <div v-if="strategyType === 'grid'" class="grid-strategy-layout">
      <section class="grid-config-panel surface">
        <div class="surface-heading"><div><span class="section-kicker">CONFIGURATION</span><h3>网格参数</h3></div><span class="draft-status">{{ gridLoading ? '计算中' : '日线回测' }}</span></div>
        <div class="form-grid">
          <label class="field field-wide"><span>股票或 ETF 代码</span><input v-model.trim="gridDraft.code" inputmode="numeric" maxlength="6" placeholder="例如 588000" @keydown.enter.prevent="previewGrid"></label>
          <div v-if="gridInstrument" class="grid-instrument field-wide"><span class="stock-dot stock-dot-blue">{{ gridInstrument.name.slice(0, 1) }}</span><div><strong>{{ gridInstrument.name }}</strong><span>{{ gridInstrument.code }} · {{ gridInstrument.exchange }} · {{ gridInstrument.board }}</span></div><b>{{ formatNullable(gridInstrument.price) }}</b></div>
          <div v-else-if="normalizedGridCode" class="grid-instrument grid-instrument-pending field-wide"><i data-lucide="search" aria-hidden="true"></i><span>输入代码后生成建议，系统会读取对应标的的历史日线。</span></div>
          <label class="field"><span>历史窗口</span><select v-model.number="gridDraft.lookback"><option :value="60">60 个交易日</option><option :value="120">120 个交易日</option><option :value="240">240 个交易日</option></select></label>
          <label class="field"><span>网格数量</span><input v-model.number="gridDraft.gridCount" type="number" min="2" max="30"></label>
          <label class="field"><span>执行模式</span><select v-model="gridDraft.mode"><option value="classic">经典：跌买涨卖</option><option value="trend">趋势：涨买跌卖</option></select></label>
          <label class="field"><span>交收规则</span><select v-model.number="gridDraft.settlementDays"><option :value="1">T+1（A股默认）</option><option :value="0">T+0</option></select></label>
          <label class="field"><span>回测频率</span><select v-model="gridDraft.schedule"><option value="daily">每日盘后 15:20</option><option value="manual">仅手动回测</option></select></label>
          <label class="field"><span>区间下沿</span><div class="number-input"><input v-model.number="gridDraft.lower" type="number" min="0.01" step="0.01"><span>元</span></div></label>
          <label class="field"><span>区间上沿</span><div class="number-input"><input v-model.number="gridDraft.upper" type="number" min="0.01" step="0.01"><span>元</span></div></label>
          <label class="field"><span>投入资金</span><div class="number-input"><input v-model.number="gridDraft.capital" type="number" min="1000" step="1000"><span>元</span></div></label>
          <label class="field"><span>双边费率</span><div class="number-input"><input v-model.number="gridDraft.feeBps" type="number" min="0" step="0.1"><span>BP</span></div></label>
          <label class="field"><span>单边滑点</span><div class="number-input"><input v-model.number="gridDraft.slippageBps" type="number" min="0" max="100" step="0.1"><span>BP</span></div></label>
          <label class="field field-wide"><span>策略名称</span><input v-model.trim="gridDraft.name" placeholder="例如 科创50ETF 区间网格"></label>
        </div>
        <div class="form-footer"><span class="form-footnote"><i data-lucide="info" aria-hidden="true"></i>生成建议后可回测，回测完成后才可保存策略</span><button v-if="!hasGridSuggestion" class="button button-primary" type="button" :disabled="gridLoading" @click="previewGrid"><i data-lucide="sparkles" aria-hidden="true"></i>生成策略建议</button><button v-else class="button button-primary" type="button" :disabled="gridLoading" @click="backtestGrid()"><i data-lucide="play" aria-hidden="true"></i>运行回测</button></div>
      </section>
      <section class="grid-result-panel surface">
        <div class="surface-heading"><div><span class="section-kicker">BACKTEST RESULT</span><h3>回测表现</h3></div><button class="icon-button" type="button" aria-label="运行网格回测" data-tooltip="运行回测" :disabled="gridLoading || !hasGridSuggestion" @click="backtestGrid()"><i data-lucide="play" aria-hidden="true"></i></button></div>
        <div v-if="gridResult" class="grid-result-body">
          <p v-if="gridProvenance" class="grid-provenance"><i data-lucide="database" aria-hidden="true"></i>{{ gridProvenance }}</p>
          <div class="grid-metrics"><div><span>区间收益</span><strong :class="trendClass(gridResult.metrics.returnPct)">{{ formatPct(gridResult.metrics.returnPct) }}</strong></div><div><span>最大回撤</span><strong>{{ gridResult.metrics.maxDrawdownPct.toFixed(2) }}%</strong></div><div><span>成交次数</span><strong>{{ gridResult.metrics.tradeCount }}</strong></div><div><span>期末权益</span><strong>{{ formatMoney(gridResult.metrics.endEquity) }}</strong></div></div>
          <div class="grid-metrics grid-metrics-secondary"><div><span>基准收益</span><strong :class="trendClass(gridResult.metrics.benchmarkReturnPct)">{{ formatPct(gridResult.metrics.benchmarkReturnPct) }}</strong></div><div><span>超额收益</span><strong :class="trendClass(gridResult.metrics.excessReturnPct)">{{ formatPct(gridResult.metrics.excessReturnPct) }}</strong></div><div><span>年化波动</span><strong>{{ gridResult.metrics.annualizedVolatilityPct != null ? gridResult.metrics.annualizedVolatilityPct.toFixed(2) + '%' : '--' }}</strong></div><div><span>夏普比率</span><strong>{{ gridResult.metrics.sharpeRatio != null ? gridResult.metrics.sharpeRatio.toFixed(2) : '--' }}</strong></div><div><span>总费用</span><strong>{{ formatMoney(gridResult.metrics.totalFees) }}</strong></div><div><span>换手倍数</span><strong>{{ gridResult.metrics.turnoverMultiple.toFixed(2) }}x</strong></div><div><span>胜率</span><strong>{{ gridResult.metrics.winRatePct != null ? gridResult.metrics.winRatePct.toFixed(1) + '%' : '--' }}</strong></div><div><span>最长回撤</span><strong>{{ gridResult.metrics.maxDrawdownDurationDays != null ? gridResult.metrics.maxDrawdownDurationDays + ' 天' : '--' }}</strong></div><div><span>单格收益</span><strong>{{ gridResult.metrics.avgGridReturnPct != null ? gridResult.metrics.avgGridReturnPct.toFixed(2) + '%' : '--' }}</strong></div></div>
          <div class="grid-equity-chart" v-html="compareChartSvg(gridResult)"></div>
          <div class="grid-levels"><span v-for="level in gridResult.levels" :key="level">{{ formatNumber(level) }}</span></div>
          <p class="heading-note grid-assumption">{{ gridResult.assumptions }}</p>
        </div>
        <div v-else-if="gridSuggestion" class="grid-result-body">
          <div class="grid-metrics"><div><span>基准价</span><strong>{{ formatNumber(gridSuggestion.referencePrice) }}</strong></div><div><span>每格金额</span><strong>{{ formatMoney(gridSuggestion.perGridAmount) }}</strong></div><div><span>上涨触发</span><strong>{{ gridSuggestion.upTriggerPct.toFixed(2) }}%</strong></div><div><span>下跌触发</span><strong>{{ gridSuggestion.downTriggerPct.toFixed(2) }}%</strong></div></div>
          <div class="grid-rules"><span>{{ gridSuggestion.buyRule }}</span><span>{{ gridSuggestion.sellRule }}</span><span>每次约 {{ gridSuggestion.lotSize }} 股</span><span>建议投入 {{ formatMoney(gridSuggestion.suggestedCapital) }}</span></div>
          <div class="grid-levels"><span v-for="level in gridSuggestion.levels" :key="level">{{ formatNumber(level) }}</span></div>
        </div>
        <div v-else class="empty-state"><i data-lucide="grid-3x3" aria-hidden="true"></i><strong>先生成策略建议</strong><span>系统会基于历史日线给出区间、每格资金和建议投入。</span><button class="button button-secondary" type="button" :disabled="gridLoading" @click="previewGrid"><i data-lucide="sparkles" aria-hidden="true"></i>生成策略建议</button></div>
      </section>
    </div>
    <div v-else class="grid-strategy-layout">
      <section class="grid-config-panel surface">
        <div class="surface-heading"><div><span class="section-kicker">CONFIGURATION</span><h3>{{ strategyTypeLabel }}参数</h3></div><span class="draft-status">{{ strategyLoading ? '计算中' : '日线回测' }}</span></div>
        <div class="form-grid">
          <label class="field field-wide"><span>股票或 ETF 代码</span><input v-model.trim="strategyDraft.code" inputmode="numeric" maxlength="6" placeholder="例如 600519" @keydown.enter.prevent="backtestStrategy()"></label>
          <div v-if="strategyInstrument" class="grid-instrument field-wide"><span class="stock-dot stock-dot-blue">{{ strategyInstrument.name.slice(0, 1) }}</span><div><strong>{{ strategyInstrument.name }}</strong><span>{{ strategyInstrument.code }} · {{ strategyInstrument.exchange }} · {{ strategyInstrument.board }}</span></div><b>{{ formatNullable(strategyInstrument.price) }}</b></div>
          <div v-else-if="normalizedStrategyCode" class="grid-instrument grid-instrument-pending field-wide"><i data-lucide="search" aria-hidden="true"></i><span>输入代码后可直接运行回测，系统会读取对应标的的历史日线。</span></div>
          <label class="field"><span>历史窗口</span><select v-model.number="strategyDraft.lookback"><option :value="60">60 个交易日</option><option :value="120">120 个交易日</option><option :value="240">240 个交易日</option></select></label>
          <label class="field"><span>投入资金</span><div class="number-input"><input v-model.number="strategyDraft.capital" type="number" min="1000" step="1000"><span>元</span></div></label>
          <label class="field"><span>双边费率</span><div class="number-input"><input v-model.number="strategyDraft.feeBps" type="number" min="0" step="0.1"><span>BP</span></div></label>
          <label class="field"><span>回测频率</span><select v-model="strategyDraft.schedule"><option value="daily">每日盘后 15:20</option><option value="manual">仅手动回测</option></select></label>
          <template v-for="field in strategySchema" :key="field.key">
            <label class="field"><span>{{ field.label }}</span><div v-if="field.type === 'int' || field.type === 'float'" class="number-input"><input v-model.number="strategyDraft.config[field.key]" :type="'number'" :min="field.min" :max="field.max" :step="field.step || (field.type === 'float' ? 0.1 : 1)"><span>{{ field.suffix || '' }}</span></div></label>
          </template>
          <label class="field field-wide"><span>策略名称</span><input v-model.trim="strategyDraft.name" :placeholder="'例如 ' + normalizedStrategyCode + ' ' + strategyTypeLabel + '策略'"></label>
        </div>
        <div class="form-footer"><span class="form-footnote"><i data-lucide="info" aria-hidden="true"></i>运行回测后即可保存策略</span><button class="button button-primary" type="button" :disabled="strategyLoading" @click="backtestStrategy()"><i data-lucide="play" aria-hidden="true"></i>运行回测</button></div>
      </section>
      <section class="grid-result-panel surface">
        <div class="surface-heading"><div><span class="section-kicker">BACKTEST RESULT</span><h3>回测表现</h3></div><button v-if="hasStrategyResult" class="button button-primary" type="button" :disabled="strategyLoading" @click="backtestStrategy(true)"><i data-lucide="save" aria-hidden="true"></i>保存策略</button></div>
        <div v-if="strategyResult" class="grid-result-body">
          <p v-if="strategyProvenance" class="grid-provenance"><i data-lucide="database" aria-hidden="true"></i>{{ strategyProvenance }}</p>
          <div class="grid-metrics"><div><span>策略收益</span><strong :class="trendClass(strategyResult.metrics.returnPct)">{{ formatPct(strategyResult.metrics.returnPct) }}</strong></div><div><span>最大回撤</span><strong>{{ strategyResult.metrics.maxDrawdownPct.toFixed(2) }}%</strong></div><div><span>成交次数</span><strong>{{ strategyResult.metrics.tradeCount }}</strong></div><div><span>期末权益</span><strong>{{ formatMoney(strategyResult.metrics.endEquity) }}</strong></div></div>
          <div class="grid-metrics grid-metrics-secondary"><div><span>基准收益</span><strong :class="trendClass(strategyResult.metrics.benchmarkReturnPct)">{{ formatPct(strategyResult.metrics.benchmarkReturnPct) }}</strong></div><div><span>超额收益</span><strong :class="trendClass(strategyResult.metrics.excessReturnPct)">{{ formatPct(strategyResult.metrics.excessReturnPct) }}</strong></div><div><span>年化波动</span><strong>{{ strategyResult.metrics.annualizedVolatilityPct != null ? strategyResult.metrics.annualizedVolatilityPct.toFixed(2) + '%' : '--' }}</strong></div><div><span>夏普比率</span><strong>{{ strategyResult.metrics.sharpeRatio != null ? strategyResult.metrics.sharpeRatio.toFixed(2) : '--' }}</strong></div><div><span>总费用</span><strong>{{ formatMoney(strategyResult.metrics.totalFees) }}</strong></div><div><span>换手倍数</span><strong>{{ strategyResult.metrics.turnoverMultiple.toFixed(2) }}x</strong></div><div><span>胜率</span><strong>{{ strategyResult.metrics.winRatePct != null ? strategyResult.metrics.winRatePct.toFixed(1) + '%' : '--' }}</strong></div><div><span>最长回撤</span><strong>{{ strategyResult.metrics.maxDrawdownDurationDays != null ? strategyResult.metrics.maxDrawdownDurationDays + ' 天' : '--' }}</strong></div></div>
          <div class="grid-equity-chart" v-html="compareChartSvg(strategyResult)"></div>
          <p class="heading-note grid-assumption">{{ strategyResult.assumptions }}</p>
        </div>
        <div v-else class="empty-state"><i data-lucide="activity" aria-hidden="true"></i><strong>运行{{ strategyTypeLabel }}回测</strong><span>系统会基于历史日线按参数模拟买卖并给出权益曲线与指标。</span></div>
      </section>
    </div>
    <div v-if="strategyType !== 'grid' && strategies.length" class="grid-lists">
      <section class="surface grid-candidates-panel"><div class="surface-heading"><div><span class="section-kicker">SAVED STRATEGIES</span><h3>已保存策略</h3></div></div><div class="strategy-list"><div v-for="strategy in strategies" :key="strategy.id" class="strategy-row"><div><strong>{{ strategy.name }}</strong><span>{{ strategy.code }} · {{ strategyTypeLabel }} · {{ strategy.schedule === 'daily' ? '每日盘后回测' : '手动回测' }}</span><span v-if="strategy.latestMetrics">最近收益 {{ formatPct(strategy.latestMetrics.returnPct) }} · 回撤 {{ strategy.latestMetrics.maxDrawdownPct.toFixed(2) }}%</span></div><div class="strategy-row-actions"><button class="text-button" type="button" @click="loadStrategy(strategy)">载入</button><button class="text-button" type="button" @click="toggleStrategy(strategy)">{{ strategy.status === '启用' ? '暂停' : '启用' }}</button><button class="text-button strategy-delete" type="button" @click="deleteStrategy(strategy)">删除</button></div></div></div></section>
    </div>
    <div v-if="strategyType === 'grid' && (gridCandidates.length || gridStrategies.length)" class="grid-lists">
      <section v-if="gridCandidates.length" class="surface grid-candidates-panel"><div class="surface-heading"><div><span class="section-kicker">OPTIMIZATION</span><h3>候选参数</h3></div></div><div class="table-responsive"><table class="data-table"><thead><tr><th>网格</th><th>区间</th><th class="text-end">收益</th><th class="text-end">样本外超额</th><th class="text-end">回撤</th><th class="text-end">成交</th><th>稳健性</th></tr></thead><tbody><tr v-for="candidate in gridCandidates.slice(0, 5)" :key="candidate.gridCount + '-' + candidate.lower"><td>{{ candidate.gridCount }} 格</td><td>{{ formatNumber(candidate.lower) }} - {{ formatNumber(candidate.upper) }}</td><td class="text-end" :class="trendClass(candidate.metrics.returnPct)">{{ formatPct(candidate.metrics.returnPct) }}</td><td class="text-end" :class="trendClass(candidate.metrics.excessReturnPct)">{{ formatPct(candidate.metrics.excessReturnPct) }}</td><td class="text-end">{{ candidate.metrics.maxDrawdownPct.toFixed(2) }}%</td><td class="text-end">{{ candidate.metrics.tradeCount }}</td><td><span v-if="candidate.flag" class="signal-chip signal-chip-watch">{{ candidate.flag }}</span><span v-else-if="candidate.recommended" class="signal-chip signal-chip-buy">推荐</span><span v-else class="signal-chip signal-chip-neutral">保持观察</span></td></tr></tbody></table></div></section>
      <section v-if="gridStrategies.length" class="surface grid-candidates-panel"><div class="surface-heading"><div><span class="section-kicker">SAVED STRATEGIES</span><h3>已保存策略</h3></div></div><div class="strategy-list"><div v-for="strategy in gridStrategies" :key="strategy.id" class="strategy-row"><div><strong>{{ strategy.name }}</strong><span>{{ strategy.code }} · {{ strategy.mode === 'trend' ? '趋势网格' : '经典网格' }} · {{ strategy.gridCount }} 格</span><span>{{ formatNumber(strategy.lower) }} - {{ formatNumber(strategy.upper) }} · {{ strategy.schedule === 'daily' ? '每日盘后回测' : '手动回测' }}</span><span v-if="strategy.latestMetrics">最近收益 {{ formatPct(strategy.latestMetrics.returnPct) }} · 回撤 {{ strategy.latestMetrics.maxDrawdownPct.toFixed(2) }}%</span></div><div class="strategy-row-actions"><button class="text-button" type="button" @click="loadGridStrategy(strategy)">载入</button><button class="text-button" type="button" @click="toggleGridStrategy(strategy)">{{ strategy.status === '启用' ? '暂停' : '启用' }}</button><button class="text-button strategy-delete" type="button" @click="deleteGridStrategy(strategy)">删除</button></div></div></div></section>
    </div>
  </section>
</template>

<script setup lang="ts">
import { inject, onMounted } from 'vue';
import { APP_CTX } from '@/modules/views/context';

const ctx = inject(APP_CTX)!;
const {
  strategyType,
  strategyTypeLabel,
  STRATEGY_TYPES,
  switchStrategyType,
  gridDraft,
  gridLoading,
  gridSuggestion,
  gridResult,
  gridInstrument,
  normalizedGridCode,
  hasGridSuggestion,
  hasGridResult,
  gridCandidates,
  gridStrategies,
  gridProvenance,
  previewGrid,
  backtestGrid,
  optimizeGrid,
  loadGridStrategy,
  toggleGridStrategy,
  deleteGridStrategy,
  strategyDraft,
  strategySchema,
  strategyLoading,
  strategySuggestion,
  strategyResult,
  strategyProvenance,
  normalizedStrategyCode,
  strategyInstrument,
  hasStrategyResult,
  strategies,
  loadStrategy,
  toggleStrategy,
  deleteStrategy,
  backtestStrategy,
  formatNullable,
  formatNumber,
  formatPct,
  formatMoney,
  trendClass,
  compareChartSvg,
  renderIcons,
} = ctx;

onMounted(() => renderIcons());
</script>