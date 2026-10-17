<template>
  <section class="view-panel is-active">
    <div v-if="errorMessage" class="connection-banner">
      <i data-lucide="triangle-alert" aria-hidden="true"></i>
      <span>{{ errorMessage }}</span>
      <button class="text-button" type="button" @click="refreshAll()">重试</button>
    </div>

    <div class="desk-status-strip surface">
      <span class="desk-status-item is-static">
        <span class="desk-status-label">指数</span>
        <strong :class="trendClass(selectedIndex?.change)">{{
          selectedIndex ? formatPct(selectedIndex.change) : '--'
        }}</strong>
      </span>
      <button class="desk-status-item" type="button" @click="switchView('screener')">
        <span class="desk-status-label">候选</span><strong>{{ screenRows.length }}</strong>
      </button>
      <button class="desk-status-item" type="button" @click="switchView('grid')">
        <span class="desk-status-label">策略</span><strong>{{ strategyStats.running }}</strong>
      </button>
      <button class="desk-status-item" type="button" @click="switchView('settings')">
        <span class="desk-status-label">提醒</span><strong>{{ unreadAlerts }}</strong>
      </button>
    </div>

    <div class="desk-workspaces">
      <section class="desk-panel surface">
        <div class="surface-heading">
          <div>
            <h2>发现机会</h2>
          </div>
          <span class="strategy-label">{{ presetName }}</span>
        </div>
        <div class="preset-hits">
          <button
            v-for="preset in presetHits"
            :key="preset.name"
            class="preset-hit"
            type="button"
            @click="
              applyPreset(preset);
              switchView('screener');
            "
          >
            <span :class="['preset-icon', preset.iconClass]"
              ><i :data-lucide="preset.icon" aria-hidden="true"></i
            ></span>
            <span class="preset-hit-name">{{ preset.name }}</span>
            <strong class="preset-hit-count">{{ preset.count }}</strong>
          </button>
        </div>
        <div class="mini-stock-list">
          <div
            v-for="stock in filteredRows.slice(0, 4)"
            :key="stock.code"
            class="mini-stock-item"
            @click="selectStock(stock.code)"
          >
            <span class="stock-dot stock-dot-blue">{{ stock.name.slice(0, 1) }}</span>
            <div class="mini-stock-copy">
              <strong>{{ stock.name }}</strong
              ><span>{{ stock.code }} · 量比 {{ formatNullable(stock.volumeRatio, 2) }}</span>
            </div>
            <span class="mini-stock-change" :class="trendClass(stock.change)">{{
              formatPctNullable(stock.change)
            }}</span>
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
            <h2>执行跟踪</h2>
          </div>
        </div>
        <div class="activity-list">
          <div v-for="alert in alerts.slice(0, 2)" :key="alert.id" class="activity-item">
            <div
              :class="['activity-icon', alert.kind === 'alert' ? 'alert' : alert.kind === 'success' ? 'success' : '']"
            >
              <i
                :data-lucide="
                  alert.kind === 'success'
                    ? 'check-circle-2'
                    : alert.kind === 'alert'
                      ? 'triangle-alert'
                      : alert.kind === 'system'
                        ? 'wrench'
                        : 'bell-ring'
                "
                aria-hidden="true"
              ></i>
            </div>
            <div class="activity-copy">
              <strong>{{ alert.title }}</strong
              ><span>{{ alert.message }}</span>
            </div>
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
          <h2>盘面温度</h2>
        </div>
        <button
          class="icon-button"
          type="button"
          aria-label="打开盯盘中心"
          data-tooltip="盯盘中心"
          @click="switchView('monitor')"
        >
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
      <div v-else-if="loading" class="loading-state compact-empty" role="status">
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
          <span :class="trendClass(selectedIndex?.change)">{{
            selectedIndex ? formatPct(selectedIndex.change) : '--'
          }}</span>
        </div>
        <div
          class="market-chart"
          v-html="
            chartSvg(
              indexHistory.map((item: any) => item.close),
              'var(--coral)',
              '上证指数近 40 个交易日走势'
            )
          "
        ></div>
      </div>

      <div class="market-breadth">
        <div class="breadth-label">
          <span>已加载候选池涨跌</span>
          <strong>{{ breadth.up }} / {{ breadth.down }}</strong>
        </div>
        <div class="breadth-bar" aria-label="已加载候选池上涨家数与下跌家数">
          <span class="breadth-up" :style="{ width: breadth.upRatio + '%' }"></span>
          <span class="breadth-flat" :style="{ width: breadth.flatRatio + '%' }"></span>
          <span class="breadth-down" :style="{ width: breadth.downRatio + '%' }"></span>
        </div>
        <div class="breadth-legend">
          <span><i class="legend-dot up"></i>上涨 {{ breadth.up }}</span>
          <span><i class="legend-dot flat"></i>平盘 {{ breadth.flat }}</span>
          <span><i class="legend-dot down"></i>下跌 {{ breadth.down }}</span>
        </div>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { onMounted } from 'vue';
import { storeToRefs } from 'pinia';
import { chartSvg } from '@/modules/chart';
import { formatNumber, formatPct, formatNullable, formatPctNullable, trendClass } from '@/modules/format';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { useScreenerStore } from '@/stores/useScreenerStore';
import { useStrategyStore } from '@/stores/useStrategyStore';

const workspace = useWorkspaceStore();
const quotes = useQuotesStore();
const screener = useScreenerStore();
const strategy = useStrategyStore();

const { errorMessage, selectedIndex, indices, loading, indexHistory } = storeToRefs(quotes);
const { breadth, screenRows, filteredRows, presetName, presetHits } = storeToRefs(screener);
const { strategyStats } = storeToRefs(strategy);
const { unreadAlerts, alerts, refreshAll, renderIcons } = workspace;
const { applyPreset } = screener;
const { switchView, selectStock } = quotes;

onMounted(() => renderIcons());
</script>
