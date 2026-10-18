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

/** 应用版本：与 package.json 保持同步（constants.test.ts 守卫）。侧栏底部展示。 */
export const APP_VERSION = '0.7.2';

/** 主导航分区（顺序即侧栏渲染顺序）。总览不属任何分区，置顶展示。 */
export const NAV_GROUPS = [
  { id: 'research', label: '研究' },
  { id: 'validation', label: '验证' },
  { id: 'execution', label: '执行' },
  { id: 'risk', label: '风控' },
  { id: 'system', label: '系统' },
] as const;

export type NavGroupId = (typeof NAV_GROUPS)[number]['id'];

/**
 * 主导航项。顺序与数量是外部契约：app.ts 的数字键快捷键按此顺序映射，不得改动。
 * shortLabel 仅用于手机底部栏（宽度受限）；label 用于桌面侧栏与更多抽屉。
 */
export const NAV_ITEMS = [
  { id: 'overview', label: '总览', icon: 'layout-dashboard', shortLabel: '总览', group: null },
  { id: 'screener', label: '选股器', icon: 'scan-search', shortLabel: '选股', group: 'research' },
  { id: 'grid', label: '策略', icon: 'grid-3x3', shortLabel: '策略', group: 'validation' },
  { id: 'plans', label: '交易计划', icon: 'clipboard-pen-line', shortLabel: '计划', group: 'execution' },
  { id: 'monitor', label: '盯盘中心', icon: 'radar', shortLabel: '盯盘', group: 'execution' },
  { id: 'portfolio', label: '组合风险', icon: 'gauge', shortLabel: '风控', group: 'risk' },
  { id: 'settings', label: '个人中心', icon: 'user-round', shortLabel: '我的', group: 'system' },
] as const satisfies readonly {
  id: string;
  label: string;
  icon: string;
  shortLabel: string;
  group: NavGroupId | null;
}[];

export const VIEW_META = {
  overview: ['交易总览', '把真实行情、计划与提醒放在同一张桌面上'],
  screener: ['选股器', '从实时市场数据里筛出值得研究的标的'],
  grid: ['策略', '网格、双均线、定投与 MACD 的统一回测实验室'],
  plans: ['交易计划', '把想法写成可以执行的规则'],
  monitor: ['盯盘中心', '添加标的并开启自动扫描，触发结果进入个人中心'],
  portfolio: ['组合风险', '计划组合的模拟回放敞口与集中度（设计口径，非真实成交）'],
  settings: ['个人中心', '提醒中心与网站设置的统一入口'],
  'stock-detail': ['个股详情', '报价、走势与操作入口'],
};

export const STRATEGY_TYPES = [
  { id: 'grid', label: '网格', description: '区间网格，跌买涨卖' },
  { id: 'ma_cross', label: '双均线', description: '快线上穿买入，下穿卖出' },
  { id: 'dca', label: '定投', description: '定期定额 + 止盈止损' },
  { id: 'macd', label: 'MACD', description: 'DIF 上穿 DEA 买入，下穿卖出' },
  { id: 'bollinger', label: '布林带反转', description: '跌破下轨买入，上穿上轨卖出（均值回归）' },
  { id: 'donchian', label: '唐奇安突破', description: '通道突破入场，反向突破离场（ADX 确认）' },
  { id: 'momentum', label: '动量', description: 'N 日涨跌幅阈值进出，独立资金管理' },
  { id: 'multi_factor', label: '多因子', description: 'ADX 状态过滤器 + 动态模块切换' },
  { id: 'compare', label: '对比', description: '多策略同标的横向对比' },
];

// 对比 tab 的参与策略勾选集（= 全部回测策略类型，不含 compare tab 自身）
export const COMPARE_STRATEGY_TYPES = STRATEGY_TYPES.filter((item) => item.id !== 'compare');

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
  bollinger: [
    { key: 'period', label: '均线周期', type: 'int', default: 20, min: 5, max: 120, suffix: '日' },
    { key: 'numStd', label: '标准差倍数', type: 'float', default: 2, min: 0.5, max: 4, step: 0.1, suffix: 'σ' },
  ],
  donchian: [
    { key: 'period', label: '通道周期', type: 'int', default: 20, min: 5, max: 120, suffix: '日' },
    { key: 'adxPeriod', label: 'ADX 周期', type: 'int', default: 14, min: 5, max: 60, suffix: '日' },
    { key: 'adxThreshold', label: 'ADX 阈值', type: 'int', default: 25, min: 10, max: 50, suffix: '' },
  ],
  momentum: [
    { key: 'period', label: '动量周期', type: 'int', default: 20, min: 3, max: 120, suffix: '日' },
    { key: 'entryPct', label: '入场阈值', type: 'float', default: 5, min: 0.5, max: 50, step: 0.5, suffix: '%' },
    { key: 'exitPct', label: '退出阈值', type: 'float', default: -3, min: -50, max: 0, step: 0.5, suffix: '%' },
  ],
  multi_factor: [
    { key: 'adxPeriod', label: 'ADX 周期', type: 'int', default: 14, min: 5, max: 60, suffix: '日' },
    { key: 'adxThreshold', label: 'ADX 阈值', type: 'int', default: 25, min: 10, max: 50, suffix: '' },
    { key: 'maxConsecutiveLosses', label: '最大连续亏损', type: 'int', default: 10, min: 2, max: 50, suffix: '笔' },
    { key: 'rangePeriod', label: '震荡MA周期', type: 'int', default: 20, min: 5, max: 120, suffix: '日' },
    { key: 'rangeStd', label: '震荡标准差', type: 'float', default: 2, min: 0.5, max: 4, step: 0.1, suffix: 'σ' },
    { key: 'trendPeriod', label: '趋势通道周期', type: 'int', default: 20, min: 5, max: 120, suffix: '日' },
    { key: 'trendAdxPeriod', label: '趋势ADX周期', type: 'int', default: 14, min: 5, max: 60, suffix: '日' },
    { key: 'trendAdxThreshold', label: '趋势ADX阈值', type: 'int', default: 25, min: 10, max: 50, suffix: '' },
  ],
};

export const SETTINGS_TABS = [
  { id: 'workspace', label: '工作台' },
  { id: 'data', label: '数据获取' },
  { id: 'assist', label: '交易辅助' },
  { id: 'connection', label: '连接状态' },
];
