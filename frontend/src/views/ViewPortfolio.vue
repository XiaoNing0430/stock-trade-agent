<template>
  <section class="view-panel is-active pf-root">
    <div class="view-heading">
      <div>
        <span class="section-kicker">PORTFOLIO RISK</span>
        <h2>组合风险模拟回放</h2>
        <p class="heading-note">多份计划在同一资金池上的设计口径回放：毛/净净值、敞口与行业集中度。</p>
      </div>
      <div class="view-heading-actions">
        <button class="button button-secondary" type="button" @click="reload">
          <i data-lucide="refresh-cw" aria-hidden="true"></i>刷新
        </button>
      </div>
    </div>

    <!-- 状态条：错误红线（固定文案）→ 降级黄条（含代码，降级不得静默） -->
    <p v-if="store.error" class="plan-draft-error" data-testid="portfolio-error" role="alert">{{ store.error }}</p>
    <p v-if="degradedCodes.length" class="pf-degraded" data-testid="portfolio-degraded">
      以下代码使用本地历史兜底，净值与行业分布可能陈旧：{{ degradedCodes.join('、') }}
    </p>

    <!-- ① 控制行：回看 chips → 层 chips → 高级三区（默认关） -->
    <div class="pf-controls surface">
      <div class="review-days pf-days">
        <button
          v-for="chip in DAY_CHIPS"
          :key="chip.value"
          type="button"
          data-testid="portfolio-day-chip"
          :class="{ active: chip.value === store.days && !store.start }"
          @click="pickDays(chip.value)"
        >
          {{ chip.label }}
        </button>
      </div>
      <div class="review-tabs pf-layers">
        <button
          type="button"
          data-testid="portfolio-layer-core"
          :class="{ active: store.layer === 'core' }"
          @click="pickLayer('core')"
        >
          主层
        </button>
        <button
          type="button"
          data-testid="portfolio-layer-closed"
          :class="{ active: store.layer === 'closed' }"
          @click="pickLayer('closed')"
        >
          闭环层
        </button>
      </div>
      <button class="pf-adv-toggle" type="button" data-testid="portfolio-adv-toggle" @click="advOpen = !advOpen">
        <span>高级</span>
        <i data-lucide="chevron-down" aria-hidden="true" :class="{ flipped: advOpen }"></i>
      </button>
      <div v-if="advOpen" class="pf-adv-zone">
        <label class="pf-adv-field" data-testid="portfolio-adv-start">
          <span>起始日（指定后覆盖回看档）</span>
          <input type="date" :value="store.start" @change="onStartChange" />
        </label>
        <label class="pf-adv-field" data-testid="portfolio-adv-watch">
          <span>自选观察（等权指数叠线）</span>
          <input type="checkbox" :checked="store.withWatch" @change="onWatchChange" />
        </label>
        <label class="pf-adv-field" data-testid="portfolio-adv-hypo">
          <span>假想线（集中度卡内展示）</span>
          <input v-model="showHypo" type="checkbox" />
        </label>
      </div>
    </div>

    <!-- ② KPI 行：null → '--'（不造数） -->
    <div class="review-kpis pf-kpis" data-testid="portfolio-kpis">
      <div class="kpi">
        <b>{{ formatAmount(kpis?.navNow) }}</b
        ><span>毛净值</span>
      </div>
      <div class="kpi">
        <b>{{ formatAmount(kpis?.navNowNet) }}</b
        ><span>净净值</span>
      </div>
      <div class="kpi">
        <b>{{ ratioPct(kpis?.mdd) }}</b
        ><span>毛最大回撤</span>
      </div>
      <div class="kpi">
        <b>{{ ratioPct(kpis?.mddNet) }}</b
        ><span>净最大回撤</span>
      </div>
      <div class="kpi">
        <b>{{ ratioPct(kpis?.exposurePct) }}</b
        ><span>期末敞口（市值/毛净值）</span>
      </div>
      <div class="kpi">
        <b>{{ ratioPct(kpis?.cashPct) }}</b
        ><span>现金占比</span>
      </div>
      <div class="kpi">
        <b>{{ planText }}</b>
        <span>计划 执行中/已触发/已了结/未入场</span>
      </div>
      <div class="kpi">
        <b>{{ numText(kpis?.pairCount) }}</b
        ><span>交易对</span>
      </div>
      <div class="kpi">
        <b>{{ numText(kpis?.orphanSellCount) }}</b
        ><span>孤儿卖单</span>
      </div>
      <div class="kpi">
        <b>{{ numText(kpis?.scalingCount) }}</b
        ><span>加仓缩量</span>
      </div>
      <div class="kpi">
        <b>{{ formatAmount(feeSum) }}</b
        ><span>窗口费用合计</span>
      </div>
      <span class="kpi-note" data-testid="portfolio-fee-note">
        毛=不计费参考线；净=双边费率逐日计提。本次费率 {{ feeRateText }}
      </span>
    </div>

    <!-- ③ NAV 曲线（multiLineSvg：gross 主实 / net 灰虚 / withWatch 自选灰虚第二线） -->
    <section class="pf-nav surface">
      <div class="surface-heading">
        <div>
          <span class="section-kicker">NAV CURVE</span>
          <h3>组合净值曲线</h3>
        </div>
        <span v-if="store.loading" class="muted">计算中…</span>
      </div>
      <div v-if="!hasNavPoints" class="empty-state" data-testid="portfolio-empty">
        <i data-lucide="chart-line" aria-hidden="true"></i>
        <strong>暂无计划持仓</strong>
        <span>窗口内还没有可回放的买入计划——先创建并触发买入计划，再回到这里查看毛/净净值曲线。</span>
      </div>
      <template v-else>
        <div class="pf-chart" data-testid="portfolio-nav-chart" v-html="navSvg"></div>
        <p class="muted" data-testid="portfolio-cash-note">
          现金不计入曲线（不绘 0 基线，现金水平见「现金占比 / 期末现金」）；费用后净值见灰色虚线。
        </p>
        <p v-if="watchIndex" class="muted" data-testid="portfolio-watch-note">
          {{ watchIndex.note || '自选观察组合（等权指数，非持仓）' }}——已按首个非空毛净值折算叠加，仅作走势对比
        </p>
      </template>
    </section>

    <!-- ④ 敞口卡：Σ计划仓位 vs 上限，overCap 红 -->
    <section
      class="pf-exposure surface"
      data-testid="portfolio-exposure"
      :class="{ 'pf-over': Boolean(exposure?.overCap) }"
    >
      <div class="surface-heading">
        <div>
          <span class="section-kicker">EXPOSURE</span>
          <h3>计划敞口</h3>
        </div>
        <strong v-if="exposure?.overCap" class="pf-over-text" data-testid="portfolio-overcap">计划敞口已超上限</strong>
      </div>
      <div class="pf-bar" aria-hidden="true">
        <i :style="{ width: barWidth(exposure?.plannedPct) }"></i>
        <em class="pf-cap" :style="{ left: barWidth(exposure?.capPct) }" title="单只仓位上限"></em>
      </div>
      <p class="pf-exposure-nums">
        <span
          >Σ计划仓位 <b>{{ pctText(exposure?.plannedPct) }}</b></span
        >
        <span
          >上限 <b>{{ pctText(exposure?.capPct) }}</b></span
        >
        <span
          >期末现金 <b>{{ ratioPct(exposure?.cashPct) }}</b></span
        >
        <span
          >折算金额 <b>{{ formatAmount(exposure?.amountByEquity) }}</b></span
        >
      </p>
    </section>

    <!-- ⑤ 集中度卡：横向条 + Top3/HHI + 未知桶 + 观察池行 + 假想线区 -->
    <section class="pf-concentration surface">
      <div class="surface-heading">
        <div>
          <span class="section-kicker">CONCENTRATION</span>
          <h3>行业集中度</h3>
        </div>
        <span v-if="coverage" class="muted">
          行业识别 {{ coverage.known }}/{{ coverage.total }} · 陈旧 {{ coverage.staleCount }}
        </span>
      </div>
      <p v-if="warming" class="pf-warming" data-testid="portfolio-warming">行业数据预热中，稍后自动刷新</p>
      <template v-else-if="concentration">
        <div class="pf-conc-metrics">
          <span
            >Top3 合计 <b>{{ pctText(concentration.top3) }}</b></span
          >
          <span
            >HHI <b>{{ concentration.hhi == null ? '--' : concentration.hhi.toFixed(3) }}</b></span
          >
          <span v-if="concentration.unknownPct > 0" data-testid="portfolio-unknown">
            未知桶 <b>{{ pctText(concentration.unknownPct) }}</b
            ><span class="badge-muted">行业映射缺失</span>
          </span>
        </div>
        <div v-for="row in concentration.industries" :key="row.key" class="pf-ind-row">
          <span class="pf-ind-label">{{ row.label }}</span>
          <span class="pf-ind-bar"><i :style="{ width: barWidth(row.pct) }"></i></span>
          <b class="pf-ind-pct">{{ pctText(row.pct) }}</b>
        </div>
        <div v-if="concentration.watchPool" class="pf-watchpool" data-testid="portfolio-watchpool">
          <p class="muted">{{ concentration.watchPool.note || '观察池仅行业分布，不参竞主指标' }}</p>
          <div v-for="row in watchPoolRows" :key="String(row.key)" class="pf-ind-row pf-ind-row-minor">
            <span class="pf-ind-label">{{ row.label }}</span>
            <span class="pf-ind-bar"><i :style="{ width: barWidth(row.pct) }"></i></span>
            <b class="pf-ind-pct">{{ pctText(row.pct) }}</b>
          </div>
        </div>
        <div v-if="showHypo" class="pf-hypo" data-testid="portfolio-hypo">
          <p class="muted">
            <span class="pf-hypo-tag">假想参考，非真实持仓</span>
            {{ hypo?.note || '若自选按上限等权建仓的假想权重线' }}
          </p>
          <div v-for="row in hypoRows" :key="String(row.key)" class="pf-ind-row pf-ind-row-minor">
            <span class="pf-ind-label">{{ row.label }}</span>
            <span class="pf-ind-bar"><i :style="{ width: barWidth(row.pct) }"></i></span>
            <b class="pf-ind-pct">{{ pctText(row.pct) }}</b>
          </div>
          <p v-if="!hypoRows.length" class="muted">开启自选观察后随下次计算生成假想线。</p>
        </div>
      </template>
      <p v-else class="muted">暂无行业分布数据（窗口内无有效持仓市值）。</p>
    </section>

    <!-- ⑥ 折叠区：交易对 / 孤儿 / 信号看板 / 回放事件（cap 截断披露） -->
    <section class="pf-fold surface">
      <button class="review-toggle" type="button" data-testid="portfolio-pairs-toggle" @click="openPairs = !openPairs">
        <span>交易对（买入 × 关联卖出）</span>
        <span class="muted">{{ pairsTotal }} 组</span>
        <i data-lucide="chevron-down" aria-hidden="true" :class="{ flipped: openPairs }"></i>
      </button>
      <template v-if="openPairs">
        <table v-if="pairs.length" class="review-table" data-testid="portfolio-pairs">
          <thead>
            <tr>
              <th>代码</th>
              <th>买入计划（入场/止损/目标）</th>
              <th>卖出计划</th>
              <th>离场模式</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(pair, i) in pairs" :key="String(pair.buyPlanId ?? i)">
              <td>{{ pair.buy?.code ?? '--' }}</td>
              <td>
                {{ formatNumber(pair.buy?.entry) }} / {{ formatNumber(pair.buy?.stop) }} /
                {{ formatNumber(pair.buy?.target) }}<span class="muted"> · {{ pair.buy?.status ?? '--' }}</span>
              </td>
              <td>
                {{ formatNumber(pair.sell?.entry) }} / {{ formatNumber(pair.sell?.stop) }} /
                {{ formatNumber(pair.sell?.target) }}<span class="muted"> · {{ pair.sell?.status ?? '--' }}</span>
              </td>
              <td>{{ exitModeLabel(pair.exitMode) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">窗内没有已配对的交易对。</p>
        <p v-if="pairsTotal > pairs.length" class="muted pf-truncated" data-testid="portfolio-pairs-more">
          共 {{ pairsTotal }} 条，已截断
        </p>
      </template>
    </section>

    <section class="pf-fold surface">
      <button
        class="review-toggle"
        type="button"
        data-testid="portfolio-orphans-toggle"
        @click="openOrphans = !openOrphans"
      >
        <span>孤儿平仓单（未配对卖出）</span>
        <span class="muted">{{ orphansTotal }} 单</span>
        <i data-lucide="chevron-down" aria-hidden="true" :class="{ flipped: openOrphans }"></i>
      </button>
      <template v-if="openOrphans">
        <table v-if="orphans.length" class="review-table" data-testid="portfolio-orphans">
          <thead>
            <tr>
              <th>代码</th>
              <th>计划</th>
              <th>信号日</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in orphans" :key="String(row.planId ?? i)">
              <td>{{ row.code ?? '--' }}</td>
              <td class="muted">{{ row.planId ?? '--' }}</td>
              <td>{{ row.signalDate ?? '--' }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">没有孤儿平仓单。</p>
        <p v-if="orphansTotal > orphans.length" class="muted pf-truncated" data-testid="portfolio-orphans-more">
          共 {{ orphansTotal }} 条，已截断
        </p>
      </template>
    </section>

    <section class="pf-fold surface">
      <button
        class="review-toggle"
        type="button"
        data-testid="portfolio-signals-toggle"
        @click="openSignals = !openSignals"
      >
        <span>信号看板</span>
        <span class="muted">{{ signalsTotal }} 条</span>
        <i data-lucide="chevron-down" aria-hidden="true" :class="{ flipped: openSignals }"></i>
      </button>
      <template v-if="openSignals">
        <p v-if="signals?.note" class="muted pf-signal-note" data-testid="portfolio-signals-note">
          {{ signals.note }}
        </p>
        <table v-if="signalRows.length" class="review-table" data-testid="portfolio-signals">
          <thead>
            <tr>
              <th>代码</th>
              <th>信号日</th>
              <th>基准价</th>
              <th>后5日</th>
              <th>后10日</th>
              <th>后20日</th>
              <th>最大反弹</th>
              <th>最大回撤</th>
              <th title="费用估算：双边费率折算的估算收益率">费用估算</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in signalRows" :key="String(row.planId ?? i)">
              <td>{{ row.code ?? '--' }}<span v-if="row.paired" class="badge-muted">已冗余配对</span></td>
              <td>{{ row.signalDate ?? '--' }}</td>
              <td>{{ formatNumber(row.basePrice) }}</td>
              <td>{{ ratioPct(row.chg5) }}</td>
              <td>{{ ratioPct(row.chg10) }}</td>
              <td>{{ ratioPct(row.chg20) }}</td>
              <td>{{ ratioPct(row.maxRebound) }}</td>
              <td>{{ ratioPct(row.maxDrawdown) }}</td>
              <td>{{ ratioPct(row.feeEstPct) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="muted">没有产生锚点信号的孤儿/冗余卖单。</p>
        <p v-if="signalsTotal > signalRows.length" class="muted pf-truncated" data-testid="portfolio-signals-more">
          共 {{ signalsTotal }} 条，已截断
        </p>
      </template>
    </section>

    <section class="pf-fold surface">
      <button
        class="review-toggle"
        type="button"
        data-testid="portfolio-events-toggle"
        @click="openEvents = !openEvents"
      >
        <span>回放事件</span>
        <span class="muted">{{ eventsTotal }} 条</span>
        <i data-lucide="chevron-down" aria-hidden="true" :class="{ flipped: openEvents }"></i>
      </button>
      <template v-if="openEvents">
        <p class="muted pf-event-note" data-testid="portfolio-events-note">事件流保证可解释，不承诺可复现</p>
        <ul v-if="events.length" class="pf-events" data-testid="portfolio-events">
          <li v-for="(row, i) in events" :key="i">
            <span class="pf-event-type">{{ eventLabel(row.type) }}</span>
            <span>{{ row.date ?? '--' }}</span>
            <span class="muted">{{ row.code ?? '' }}</span>
            <span class="muted">{{ eventDetail(row) }}</span>
          </li>
        </ul>
        <p v-else class="muted">窗口内没有冲突、冗余、加仓缩量或悬空计划事件。</p>
        <p v-if="eventsTotal > events.length" class="muted pf-truncated" data-testid="portfolio-events-more">
          共 {{ eventsTotal }} 条，已截断
        </p>
      </template>
    </section>

    <!-- 底部红线（spec §3 D6）：整串逐字 -->
    <p class="review-disclaimer pf-disclaimer" data-testid="portfolio-disclaimer">
      虚拟组合为设计口径模拟回放，非真实成交，不构成投资建议。孤儿平仓单仅作信号统计，不纳入 NAV。
    </p>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { multiLineSvg, type MultiLineSeries } from '@/modules/chart';
import { formatAmount, formatNumber } from '@/modules/format';
import {
  usePortfolioStore,
  type PortfolioDays,
  type PortfolioLayer,
  type PortfolioRow,
} from '@/stores/usePortfolioStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';

const store = usePortfolioStore();
const workspace = useWorkspaceStore();
const { renderIcons } = workspace;

// store.setParam 只写参数不 fetch（已读 store 现状）→ 视图在 chip/输入 handler 里显式 fetchRisk，
// 不引入参数 watch（避免双路径竞态；参数即点即算，语义与 review 面板同款）。
const DAY_CHIPS: Array<{ value: PortfolioDays; label: string }> = [
  { value: 30, label: '近 30 天' },
  { value: 90, label: '近 90 天' },
  { value: 180, label: '近 180 天' },
  { value: 365, label: '近 365 天' },
  { value: 0, label: '全部' },
];

const advOpen = ref(false); // 高级三区（起始日/自选观察/假想线）默认关
const showHypo = ref(false); // 假想线展示开关（视图本地态，后端数据仍由 withWatch 门控）
const openPairs = ref(false);
const openOrphans = ref(false);
const openSignals = ref(false);
const openEvents = ref(false);

const payload = computed(() => store.payload);
const kpis = computed(() => payload.value?.kpis ?? null);
const feeSum = computed(() => payload.value?.nav?.feeSum ?? null);
const exposure = computed(() => payload.value?.exposure ?? null);
const concentration = computed(() => payload.value?.concentration ?? null);
const coverage = computed(() => payload.value?.meta?.industryCoverage ?? null);
const watchIndex = computed(() => payload.value?.watchIndex ?? null);
const degradedCodes = computed(() => payload.value?.degraded ?? []);
const pairs = computed<PortfolioRow[]>(() => payload.value?.pairs ?? []);
const orphans = computed<PortfolioRow[]>(() => payload.value?.orphans ?? []);
const signals = computed(() => payload.value?.signals ?? null);
const signalRows = computed<PortfolioRow[]>(() => payload.value?.signals?.items ?? []);
const events = computed<PortfolioRow[]>(() => payload.value?.events ?? []);
const pairsTotal = computed(() => payload.value?.pairsTotal ?? 0);
const orphansTotal = computed(() => payload.value?.orphansTotal ?? 0);
const signalsTotal = computed(() => payload.value?.signalsTotal ?? 0);
const eventsTotal = computed(() => payload.value?.eventsTotal ?? 0);

// —— 数值渲染红线：null/undefined 一律 '--'，绝不造数 ——
function ratioPct(v: number | null | undefined): string {
  return v === null || v === undefined || Number.isNaN(Number(v)) ? '--' : `${(Number(v) * 100).toFixed(2)}%`;
}
function pctText(v: number | null | undefined): string {
  return v === null || v === undefined || Number.isNaN(Number(v)) ? '--' : `${Number(v).toFixed(2)}%`;
}
function numText(v: number | null | undefined): string {
  return v === null || v === undefined || Number.isNaN(Number(v)) ? '--' : String(Number(v));
}
function barWidth(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || Number.isNaN(Number(pct))) return '0%';
  return `${Math.min(100, Math.max(0, Number(pct)))}%`;
}
const feeRateText = computed(() => {
  const rate = payload.value?.meta?.feeRate;
  return rate === null || rate === undefined ? '--' : ratioPct(rate);
});
const planText = computed(() => {
  const k = kpis.value?.planCount;
  if (!k) return '-- / -- / -- / --';
  return `${k.active} / ${k.triggered} / ${k.closedInWindow} / ${k.notEntered}`;
});

// —— 预热空卡（终审 R3）：有成分但行业零识别 → 整卡预热文案，不误导为「全是未知行业」；
// concentration 整体 null（store 注释 = 预热态）同样走预热。 ——
const warming = computed(() => {
  const c = coverage.value;
  if (!c) return false;
  return c.known === 0 && c.total > 0;
});

// —— NAV 曲线：gross 主实线 / net 灰虚线 / watchIndex 灰虚第二线（存在且 dates 与净值轴等长才叠，等权指数按首个非空 gross 折算） ——
const NAV_COLORS = { gross: '#ef6d53', net: '#7d8798', watch: '#9aa6b8' };
const navHasData = computed(() => {
  const nav = payload.value?.nav;
  return Boolean(nav?.dates?.length && (nav.gross?.some((v) => v !== null) || nav.net?.some((v) => v !== null)));
});
const hasNavPoints = computed(() => navHasData.value || Boolean(watchIndex.value));
const navSeries = computed<MultiLineSeries[]>(() => {
  const nav = payload.value?.nav;
  if (!nav?.dates?.length) return [];
  const out: MultiLineSeries[] = [];
  if (nav.gross?.some((v) => v !== null)) {
    out.push({ label: '毛净值', points: nav.gross, style: 'solid', color: NAV_COLORS.gross });
  }
  if (nav.net?.some((v) => v !== null)) {
    out.push({ label: '净净值', points: nav.net, style: 'dash', color: NAV_COLORS.net });
  }
  const watch = watchIndex.value;
  const base = nav.gross?.find((v) => v !== null && Number.isFinite(Number(v)));
  // F3 对齐守卫：watch.dates 与 nav.dates 长度不一致 → 时间轴会静默错位，不叠该线。
  if (
    watch &&
    watch.dates?.length === nav.dates.length &&
    watch.values?.some((v) => v !== null) &&
    base !== undefined &&
    base !== null
  ) {
    out.push({
      label: '自选观察指数',
      points: watch.values.map((v) => (v === null ? null : v * Number(base))),
      style: 'dash',
      color: NAV_COLORS.watch,
    });
  }
  return out;
});
const navSvg = computed(() =>
  multiLineSvg(navSeries.value, { height: 220, ariaLabel: '组合净值毛净对比（含自选观察叠线）' })
);

// —— 观察池 / 假想线行（形状后端为 Record<string, unknown>，视图按 T5 装配形状收窄） ——
type ConcRow = { key: string; label: string; pct: number };
function rowsOf(block: Record<string, unknown> | null | undefined): ConcRow[] {
  const rows = block?.industries;
  return Array.isArray(rows) ? (rows as ConcRow[]) : [];
}
const watchPoolRows = computed(() => rowsOf(concentration.value?.watchPool ?? undefined));
const hypo = computed(() => concentration.value?.hypothetical ?? null);
const hypoRows = computed(() => rowsOf(hypo.value ?? undefined));

// —— 事件四类型（conflict/redundant/scaling/danglingRelatedPlan） ——
const EVENT_TYPES: Record<string, string> = {
  conflict: '同日双触冲突',
  redundant: '冗余信号',
  scaling: '加仓缩量',
  danglingRelatedPlan: '悬空关联计划',
};
function eventLabel(type: unknown): string {
  return EVENT_TYPES[String(type)] ?? String(type ?? '--');
}
function eventDetail(row: PortfolioRow): string {
  const d = row.detail ?? {};
  const parts: string[] = [];
  const ids = [d.buyPlanId, d.sellPlanId, d.planId, d.pairedWith].filter((v) => typeof v === 'string' && v);
  if (ids.length) parts.push(ids.join(' ↔ '));
  if (typeof d.executed === 'string') parts.push(`执行 ${d.executed}`);
  if (d.allocatedNotional != null && d.requestedNotional != null) {
    parts.push(`拟 ${formatAmount(d.requestedNotional)} → 实 ${formatAmount(d.allocatedNotional)}`);
  }
  if (typeof d.reason === 'string') parts.push(`原因 ${d.reason}`);
  return parts.join(' · ');
}
function exitModeLabel(mode: unknown): string {
  if (mode === 'race') return '同日竞速';
  if (mode === 'stop_first') return '止损优先';
  if (mode === 'target_first') return '止盈优先';
  return mode == null ? '--' : String(mode);
}

// —— 参数交互：chip/输入即 setParam + fetch（store 不自动 fetch，视图单点驱动） ——
function pickDays(days: PortfolioDays) {
  store.setParam('days', days);
  if (store.start) store.setParam('start', ''); // 点档 = 放弃自定义起始日（start 优先会吞掉 days）
  void store.fetchRisk();
}
function pickLayer(layer: PortfolioLayer) {
  store.setParam('layer', layer);
  void store.fetchRisk();
}
function onStartChange(event: Event) {
  store.setParam('start', (event.target as HTMLInputElement).value);
  void store.fetchRisk();
}
function onWatchChange(event: Event) {
  store.setParam('withWatch', (event.target as HTMLInputElement).checked);
  void store.fetchRisk();
}
function reload() {
  void store.fetchRisk();
}

onMounted(() => {
  renderIcons();
  void store.fetchRisk(); // fetch 时机：进入视图即算一次（失败态可经 chip/刷新重试）
});
</script>
