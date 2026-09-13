import { defineStore } from 'pinia';
import { ref } from 'vue';
import { requestJson } from '@/api/client';

// ── I13 类型落点：payload TS 接口按 spec §6 顶层键逐字内联于本文件（风格同 ReviewPayload）。──
// r3.2 命名钉死：nav 数组为 gross（values 已废）；gross/net 容忍 null 起点（轴首无值原样透传，不造数）。

export interface PortfolioKpiPlanCount {
  active: number; triggered: number; closedInWindow: number; notEntered: number;
}
export interface PortfolioKpis {
  navNow: number; navNowNet: number; mdd: number; mddNet: number;
  exposurePct: number; cashPct: number;
  planCount: PortfolioKpiPlanCount;
  orphanSellCount: number; pairCount: number; scalingCount: number;
}
export interface PortfolioNav {
  dates: string[];
  gross: (number | null)[];
  net: (number | null)[];
  feeCum: (number | null)[];
  feeSum: number | null;
}
export interface PortfolioExposure {
  plannedPct: number; capPct: number; overCap: boolean; cashPct: number; amountByEquity: number;
}
export interface PortfolioIndustryRow { key: string; label: string; pct: number; }
export interface PortfolioConcentration {
  // hhi/top3 放宽 null：后端现恒为数（sum/Σ），但外部 JSON 不做运行时保证——视图守卫（null→'--'）
  // 与类型面对齐（收尾硬化 L4，终审 low 观察）。
  top3: number | null; hhi: number | null;
  industries: PortfolioIndustryRow[];
  unknownPct: number;
  // 观察池 / 假想线区块（T5 装配，形状由视图按需收窄）；顶层 concentration 亦可整体 null（预热中）。
  watchPool: Record<string, unknown> | null;
  hypothetical: Record<string, unknown> | null;
}
// 列表行（pairs/orphans/signals.items/events）后端为动态结构（spec §5.5/§6 cap 50），
// 显式 any 是既有前端约定（AGENTS.md）；视图任务落地时再按消费字段收窄。
export type PortfolioRow = { [k: string]: any };
export interface PortfolioSignals { items: PortfolioRow[]; note: string; }
// 自选观察组合等权指数（顶层键为 T5 裁定新增，非 spec 原文——见 task-10 勘误队列）。
export interface PortfolioWatchIndex {
  dates: string[]; values: (number | null)[]; equityStart: number; note: string;
}
export interface PortfolioMeta {
  layer: string; windowStart: string; truncatedAt?: string | null;
  industryCoverage: { known: number; total: number; staleCount: number };
  equity: number; feeRate: number;
}
export interface PortfolioPayload {
  kpis: PortfolioKpis;
  nav: PortfolioNav;
  exposure: PortfolioExposure;
  concentration: PortfolioConcentration | null;
  pairs: PortfolioRow[]; pairsTotal: number;
  orphans: PortfolioRow[]; orphansTotal: number;
  signals: PortfolioSignals; signalsTotal: number;
  events: PortfolioRow[]; eventsTotal: number;
  watchIndex: PortfolioWatchIndex | null;
  degraded: string[];
  meta: PortfolioMeta;
}

export type PortfolioDays = 0 | 30 | 90 | 180 | 365;   // 0 = ALL（spec §6 days 白名单）
export type PortfolioLayer = 'core' | 'closed';

// 参数 → 值类型映射：setParam 借泛型索引保持逐键精确类型（杜绝 days 收字符串等串键）。
export interface PortfolioParamTypes {
  days: PortfolioDays;
  start: string;
  layer: PortfolioLayer;
  withWatch: boolean;
  feeRate: string;
}

const PREFS_KEY = 'portfolio_prefs_v1';
const DEFAULT_DAYS: PortfolioDays = 90;
const DEFAULT_LAYER: PortfolioLayer = 'core';
const DAY_VALUES: readonly PortfolioDays[] = [0, 30, 90, 180, 365];
const LAYER_VALUES: readonly PortfolioLayer[] = ['core', 'closed'];

const isDays = (v: unknown): v is PortfolioDays => (DAY_VALUES as readonly unknown[]).includes(v);
const isLayer = (v: unknown): v is PortfolioLayer => (LAYER_VALUES as readonly unknown[]).includes(v);

// 偏好恢复（仅 {days,layer,withWatch} 三键）：坏 JSON 与越界值逐字段回默认，绝不抛错。
// feeRate/start 为一次性分析参数，刻意不读写 localStorage（观察 3 / spec §7）。
function loadPrefs(): { days: PortfolioDays; layer: PortfolioLayer; withWatch: boolean } {
  try {
    const o = JSON.parse(localStorage.getItem(PREFS_KEY) || 'null') as Record<string, unknown> | null;
    return {
      days: isDays(o?.days) ? o.days : DEFAULT_DAYS,
      layer: isLayer(o?.layer) ? o.layer : DEFAULT_LAYER,
      withWatch: typeof o?.withWatch === 'boolean' ? o.withWatch : false,
    };
  } catch {
    return { days: DEFAULT_DAYS, layer: DEFAULT_LAYER, withWatch: false };
  }
}

export const usePortfolioStore = defineStore('portfolio', () => {
  const prefs = loadPrefs();
  const days = ref<PortfolioDays>(prefs.days);
  const layer = ref<PortfolioLayer>(prefs.layer);
  const withWatch = ref<boolean>(prefs.withWatch);
  const start = ref<string>('');
  const feeRate = ref<string>('');

  const payload = ref<PortfolioPayload | null>(null);
  const loading = ref(false);
  // 错误状态（红线：失败可见化，复用 review 错误模式；固定文案不外泄后端 detail）。
  const error = ref<string | null>(null);
  const fetchedOnce = ref(false);

  function persistPrefs() {
    try {
      localStorage.setItem(PREFS_KEY,
        JSON.stringify({ days: days.value, layer: layer.value, withWatch: withWatch.value }));
    } catch { /* 存储不可用（无痕等）→ 偏好保持内存态，不阻断分析 */ }
  }

  function setParam<K extends keyof PortfolioParamTypes>(key: K, value: PortfolioParamTypes[K]) {
    // TS 相关联合不自动收窄 switch 分支——单点写入保持逐键精确类型（唯一 cast 处，读写对称）。
    const targets = { days, layer, withWatch, start, feeRate } as const;
    (targets[key] as unknown as { value: PortfolioParamTypes[K] }).value = value;
    if (key === 'days' || key === 'layer' || key === 'withWatch') {
      persistPrefs();                               // 仅三个偏好键触发即时持久化
    } // start/feeRate 一次性参数：刻意不落盘
  }

  // spec §6 拼参：start 优先且完全忽略 days（终审 R4）；withWatch 字面 true/false；
  // feeRate 非空才带（省略 = 回落服务端 DEFAULT_FEE_RATE）。
  function riskUrl(): string {
    const q: string[] = [];
    if (start.value) q.push(`start=${encodeURIComponent(start.value)}`);
    else q.push(`days=${days.value}`);
    q.push(`layer=${layer.value}`, `withWatch=${withWatch.value}`);
    if (feeRate.value) q.push(`feeRate=${encodeURIComponent(feeRate.value)}`);
    return `/api/portfolio/risk?${q.join('&')}`;
  }

  async function fetchRisk(): Promise<void> {
    loading.value = true;
    try {
      // payload 逐字透传（null 起点/degraded/watchIndex 原样），视图层零加工、绝不造数。
      payload.value = await requestJson<PortfolioPayload>(riskUrl(), { method: 'GET' });
      error.value = null;
      fetchedOnce.value = true;
    } catch {
      // 失败即无可信数据 → 清 payload、复位 fetchedOnce（再入视图可重新拉取，可重试语义）。
      payload.value = null;
      fetchedOnce.value = false;
      error.value = '组合风险计算失败，请稍后重试';
    } finally {
      loading.value = false;
    }
  }

  function reset() {
    // 清分析态；当前参数与已持久化偏好不动（再入视图仍带上次档）。
    payload.value = null;
    error.value = null;
    fetchedOnce.value = false;
  }

  return { days, start, layer, withWatch, feeRate,
           payload, loading, error, fetchedOnce,
           fetchRisk, setParam, reset };
});
