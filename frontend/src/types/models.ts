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
}

export interface HistoryBar {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}
