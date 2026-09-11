// 与后端 Pydantic 契约一致的字段（字段名逐字节保持现状，不得改名）
export interface Quote {
  code: string;
  name: string;
  price: number | null;
  change: number | null;
  changePct: number | null;
  volumeRatio?: number | null;
  [key: string]: unknown;
}

export interface StockRow extends Quote {
  pe?: number | null;
  turnover?: number | null;
}

export interface Plan {
  id: string;
  code: string;
  direction: 'buy' | 'sell';
  entry: number;
  stop: number;
  target: number;
  capital: number;
  position: number;
  validity: string;
  note: string;
  status: string;
  triggered: Record<string, boolean>;
  source?: string;
  createdAtMs: number;
}

export interface Alert {
  id: string;
  kind: 'alert' | 'success' | 'info' | 'system';
  title: string;
  message: string;
  read: boolean;
  createdAtMs: number;
  count?: number;
  /** 显示用便捷时间串（HH:MM），仅前端 UX 状态，不入库 */
  time?: string;
  /** 扫描合成项（useScanStore ScanAlertItem）透传字段：仅扫描命中提醒存在（useAlertsStore allAlerts 合成） */
  code?: string;
  strategyId?: string;
  firstSeen?: string;
}

export interface HistoryBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// ---------- 交易辅助（Task 2 契约 PlanDraftOut，字段名逐字保持） ----------

/** POST /api/assist/plan-draft 响应草案（响应包裹 {data: AssistDraft} 由调用方解包）。 */
export interface AssistDraft {
  code: string;
  name: string;
  direction: string;
  entry: number;
  stopAtr: number | null;
  stopMa20: number | null;
  stop: number | null;
  target: number | null;
  stopDistance: number | null;
  atr14: number | null;
  ma20: number | null;
  riskAmount: number | null;
  suggestedShares: number;
  positionPct: number;
  referenceDate: string;
  entryAsOf: number | null;
  stale: boolean;
  fallbackUsed: boolean;
  provider: string;
  warnings: string[];
  disclaimer: string;
  /** 入口归因（前端 openFor 写入，非后端响应字段）：scan:{strategyId} | screener | monitor | manual */
  source?: string;
}
