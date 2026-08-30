// Static configuration and UI constants. Pure data, no dependencies.
export const STORAGE_KEY = 'atlas-stock-desk-v2';
export const DEFAULT_WATCHLIST = ['600519', '300750', '601318', '600036', '000858', '002594'];
export const DEFAULT_FILTERS = {
  exchange: '全部',
  market: '全部',
  search: '',
  peMax: 80,
  pbMax: 12,
  volumeMin: 1.2,
  changeMin: 1,
};
export const DEFAULT_ALERTS = [
  {
    id: 'alert-connection',
    kind: 'info',
    title: '真实行情连接已就绪',
    message: '报价、指数和日线由本地行情代理实时拉取。',
    time: '刚刚',
    read: false,
  },
];

export const PRESETS = [
  {
    name: '趋势突破',
    icon: 'trending-up',
    iconClass: 'preset-icon-coral',
    description: '放量、强势、价格向上',
    filters: { peMax: 80, pbMax: 12, volumeMin: 1.2, changeMin: 1 },
  },
  {
    name: '质量成长',
    icon: 'gem',
    iconClass: 'preset-icon-blue',
    description: '估值适中、量能稳定',
    filters: { peMax: 55, pbMax: 8, volumeMin: 0.8, changeMin: -2 },
  },
  {
    name: '低估修复',
    icon: 'scale',
    iconClass: 'preset-icon-gold',
    description: '低 PE、低 PB、等待修复',
    filters: { peMax: 22, pbMax: 3, volumeMin: 0.5, changeMin: -3 },
  },
];

export const NAV_ITEMS = [
  { id: 'overview', label: '总览', icon: 'layout-dashboard' },
  { id: 'screener', label: '选股器', icon: 'scan-search' },
  { id: 'grid', label: '策略', icon: 'grid-3x3' },
  { id: 'plans', label: '交易计划', icon: 'clipboard-pen-line' },
  { id: 'monitor', label: '盯盘中心', icon: 'radar' },
  { id: 'settings', label: '个人中心', icon: 'user-round' },
] as const;

export const VIEW_META = {
  overview: ['交易总览', '把真实行情、计划与提醒放在同一张桌面上'],
  screener: ['选股器', '从实时市场数据里筛出值得研究的标的'],
  grid: ['策略', '网格、双均线、定投与 MACD 的统一回测实验室'],
  plans: ['交易计划', '把想法写成可以执行的规则'],
  monitor: ['盯盘中心', '添加标的并开启自动扫描，触发结果进入个人中心'],
  settings: ['个人中心', '提醒中心与网站设置的统一入口'],
  'stock-detail': ['个股详情', '报价、走势与操作入口'],
};

export const STRATEGY_TYPES = [
  { id: 'grid', label: '网格', description: '区间网格，跌买涨卖' },
  { id: 'ma_cross', label: '双均线', description: '快线上穿买入，下穿卖出' },
  { id: 'dca', label: '定投', description: '定期定额 + 止盈止损' },
  { id: 'macd', label: 'MACD', description: 'DIF 上穿 DEA 买入，下穿卖出' },
];

export const STRATEGY_SCHEMAS: Record<
  string,
  Array<{
    key: string;
    label: string;
    type: string;
    default?: number;
    min?: number;
    max?: number;
    step?: number;
    suffix: string;
  }>
> = {
  ma_cross: [
    { key: 'fastPeriod', label: '快线周期', type: 'int', default: 5, min: 2, max: 60, suffix: '日' },
    { key: 'slowPeriod', label: '慢线周期', type: 'int', default: 20, min: 3, max: 120, suffix: '日' },
  ],
  dca: [
    { key: 'amountPerPeriod', label: '每期投入', type: 'int', default: 5000, min: 1000, step: 1000, suffix: '元' },
    { key: 'intervalDays', label: '间隔交易日', type: 'int', default: 5, min: 1, max: 60, suffix: '日' },
    { key: 'stopProfitPct', label: '止盈线', type: 'float', default: 20, min: 1, max: 200, suffix: '%' },
    { key: 'stopLossPct', label: '止损线', type: 'float', default: 15, min: 1, max: 100, suffix: '%' },
  ],
  macd: [
    { key: 'fastPeriod', label: '快线周期', type: 'int', default: 12, min: 2, max: 30, suffix: '日' },
    { key: 'slowPeriod', label: '慢线周期', type: 'int', default: 26, min: 5, max: 60, suffix: '日' },
    { key: 'signalPeriod', label: '信号周期', type: 'int', default: 9, min: 2, max: 30, suffix: '日' },
  ],
};

export const SETTINGS_TABS = [
  { id: 'workspace', label: '工作台' },
  { id: 'data', label: '数据获取' },
  { id: 'connection', label: '连接状态' },
];
