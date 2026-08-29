# 统一策略实验室设计 — 2026-08-30

## 目标

将「网格策略」视图升级为**统一策略实验室**：顶部策略类型切换（网格 / 双均线 / DCA / MACD），共用回测、权益曲线、指标卡、保存与每日调度基础设施。P2 收官大项。

## 非目标

- 不新增 nav tab（6 个 tab 不变，「网格策略」tab 改名「策略」）。
- 不改动现有网格策略的存储（`GridStrategy` 表）与 `/api/grid/*` 端点——网格零回归。
- 不做组合优化、机器学习、多标的组合。
- 不接券商、不下真实订单（保持研究工具定位）。

## 架构

### 1. 策略引擎层（backend/strategy_engines.py，新增）

统一回测输出结构，供前端通用渲染：

```python
# 统一输出
{
  "trades": [...],            # {date, side, triggerPrice?, price, shares, fee}
  "equityCurve": [...],       # [{date, equity(归一化)}]
  "benchmarkCurve": [...],    # 买入持有基准
  "metrics": {...},           # 统一指标（收益/回撤/夏普/胜率/单格收益等）
  "assumptions": "...",       # 策略假设说明（中文，诚实披露）
  "config": {...},            # 回测所用参数
}
```

引擎注册表 + 统一入口：

```python
STRATEGY_ENGINES = {
    "grid": {"label": "网格", "backtest": ..., "suggest": ..., "configSchema": [...]},
    "ma_cross": {...},
    "dca": {...},
    "macd": {...},
}
```

#### 共享指标计算（重构抽取，逻辑不变）

现有 `backtest_grid` 内的指标计算（收益/年化/最大回撤/夏普/胜率/round-trip/利润因子等）硬编码在网格回测里。抽取为公共函数供所有引擎复用：

```python
def compute_metrics(bars, trades, equity_curve, capital, fee_bps, security_type, exchange) -> dict
```

- 从 `backtest_grid` 中剥离出第 190-239 行的指标逻辑为 `compute_metrics(...)`
- 行为完全一致（回归测试 `test_grid_strategy.py` 全绿保障）
- `_round_trip_returns` / `_max_drawdown_duration` 等辅助函数原样保留

#### 引擎 1：双均线（ma_cross）

- 参数：`fastPeriod`（默认 5）、`slowPeriod`（默认 20）
- 信号：快线 MA 上穿慢线 MA → 全仓买入；下穿 → 全仓卖出
- 首次建仓：从持有现金开始，等待首个金叉
- 费用/T+1/停牌/涨跌停语义与网格一致（复用 `transaction_fee`、`buy_and_hold_benchmark`、停牌跳过）
- `suggest()`：基于训练段（前 70%）在 (3,5,8)×(13,20,34) 参数网格中选样本外超额最高者作为建议

#### 引擎 2：DCA（定投）

- 参数：`amountPerPeriod`（每期投入金额，默认 5000）、`intervalDays`（间隔交易日，默认 5）、`stopProfitPct`（止盈 %，默认 20）、`stopLossPct`（止损 %，默认 15）
- 逻辑：初始无仓位；每 `intervalDays` 个交易日投入 `amountPerPeriod` 买入（100 股整数倍）；持仓收益达止盈/止损线时全仓卖出，之后继续按节奏定投
- `suggest()`：按 `capital/lookback` 推算合理每期投入

#### 引擎 3：MACD

- 参数：`fastPeriod`（默认 12）、`slowPeriod`（默认 26）、`signalPeriod`（默认 9）
- 信号：DIF = EMA(fast) − EMA(slow)；DEA = EMA(DIF, signal)；DIF 上穿 DEA → 全仓买入；下穿 → 全仓卖出
- EMA 需要预热（`slowPeriod + signalPeriod` 根内无信号、不交易）
- `suggest()`：在常见参数组合（(8,17,9)/(12,26,9)/(12,26,5)）中选样本外超额最高者

### 2. 存储层（backend/storage.py）

#### 新通用表 `Strategy`（strategies）

网格继续用 `GridStrategy` 表；新策略用通用表（config 为 JSON，避免为每策略造列）：

```python
class Strategy(Base):
    __tablename__ = "strategies"
    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    code: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(String(128))
    strategy_type: Mapped[str] = mapped_column(String(24), index=True)  # ma_cross|dca|macd
    config: Mapped[dict[str, Any]] = mapped_column(JSON)                 # 类型专属参数
    capital: Mapped[float] = mapped_column(Float)
    fee_bps: Mapped[float] = mapped_column(Float, default=3)
    schedule: Mapped[str] = mapped_column(String(32), default="manual")
    status: Mapped[str] = mapped_column(String(32), default="启用")
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_backtest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    latest_metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    created_at / updated_at
```

辅助函数（仿照 `save_grid_strategy`/`list_grid_strategies`/`get_grid_strategy`/`delete_grid_strategy`）：
- `save_strategy(...)`、`list_strategies(workspace_id)`、`get_strategy(id, workspace_id)`、`delete_strategy(id, workspace_id)`、`list_scheduled_strategies()`

`initialize_storage()` 用 `Base.metadata.create_all(engine)` 自动建新表（无迁移脚本）。

### 3. 调度器（backend/grid_scheduler.py → 泛化）

- `run_scheduled_backtest` 改为按 `strategy_type` 分发：`grid` 走原 `backtest_grid`（不动），其余走 `STRATEGY_ENGINES[strategy_type]["backtest"]`
- `schedule_strategy` / `unschedule_strategy`：`job_id` 前缀区分（`grid-backtest:` / `strategy-backtest:`）
- `start_scheduler()` 同时加载 `list_scheduled_grid_strategies()` 与 `list_scheduled_strategies()`
- 新策略回测结果保存：新增 `save_strategy_backtest`（写入 `StrategyBacktest` 通用回测记录表，或复用 `GridBacktest`？——**新建 `StrategyBacktest` 表**避免与网格历史混淆）

### 4. API 层（backend/app.py）

新增通用端点（`/api/grid/*` 全部保留不动）：

```text
POST /api/strategy/preview     # 生成策略建议（按 strategyType 分发 suggest）
POST /api/strategy/backtest    # 统一回测（按 strategyType 分发 backtest），可选 save
GET  /api/strategy/strategies  # 列出已保存策略
PATCH /api/strategy/strategies/{id}  # 暂停/启用
DELETE /api/strategy/strategies/{id} # 删除
```

统一请求结构：

```json
{
  "strategyType": "ma_cross",
  "code": "600519",
  "name": "茅台双均线",
  "capital": 100000,
  "feeBps": 3,
  "schedule": "manual",
  "lookback": 120,
  "config": { "fastPeriod": 5, "slowPeriod": 20 }
}
```

回测流程（复用 `_load_history_with_fallback` + `save_market_bars`）：拉历史 → 分发引擎 → 保存行情 → 返回统一结果（含 `dataSource`/`dataAsOf`）。

### 5. 前端（frontend/app.js / index.html / styles.css / constants.js）

#### 状态

- `strategyType` ref：`'grid' | 'ma_cross' | 'dca' | 'macd'`（默认 `'grid'`）
- `strategyDraft` reactive：通用字段 `{ code, name, capital, feeBps, schedule, lookback, config: {...} }`
- `strategyResult` ref / `strategySuggestion` ref / `strategyLoading` ref
- `strategies` ref（已保存策略列表，按类型筛选展示）
- 网格专用状态（`gridDraft`/`gridSuggestion`/`gridResult`）保留，`strategyType === 'grid'` 时继续走现有 `/api/grid/*` 与现有渲染

#### 导航

- `NAV_ITEMS`：`grid` 的 `label` 从「网格策略」改「策略」，`icon` 保持 `grid-3x3`
- `VIEW_META.grid` 更新为 `['策略', '网格、双均线、定投与 MACD 的统一回测实验室']`

#### 模板（index.html grid 视图改造）

- `view === 'grid'` 视图头部下方加策略类型 tabs：`网格 / 双均线 / 定投 / MACD`
- `strategyType === 'grid'`：渲染现有全部网格 UI（配置表单/建议/回测/候选/已保存），零改动
- `strategyType !== 'grid'`：渲染通用配置表单（按 `configSchema` 动态字段）+ 统一结果（权益曲线/指标卡/成交记录/已保存策略）

#### 通用结果渲染

- 复用现有 `grid-metrics` / `grid-metrics-secondary` 指标卡样式，展示统一 metrics
- 复用 `compareChartSvg(gridResult)` 权益曲线对比图
- 来源角标（`dataSource` 本地缓存/实时）沿用详情页逻辑

### 6. 诚实披露

- 每个引擎 `assumptions` 文案：参数、费用模型（T+1/100 股/佣金/印花税/过户费/滑点/涨跌停/停牌）、样本内/外划分（若 suggest）、"结果仅用于研究，不代表未来收益"
- 技术指标（MA/MACD）不构成投资建议

## 测试（TDD）

- `test_strategy_engines.py`（新增）：
  - 三引擎各自用 `sample_bars()` 跑通，返回结构含 `trades`/`equityCurve`/`metrics`/`assumptions`
  - 双均线：构造明确金叉/死叉序列断言交易方向与数量
  - DCA：断言定投次数 ≈ `lookback/intervalDays`；止盈触发时全仓卖出
  - MACD：assert 预热期内无交易；金叉后有买入
  - `compute_metrics` 抽取后与网格原结果一致（回归）
- `test_backend_api.py`：`/api/strategy/preview|backtest` 返回统一结构；`save` 时写入 `Strategy` 表；monkeypatch 上游失败降级
- `test_grid_strategy.py`：现有 49 项全绿（重构抽取无回归）

## 手动验收

- [ ] nav「网格策略」→「策略」
- [ ] 策略实验室顶部 4 个类型 tabs 可切换
- [ ] 网格类型：全部现有功能正常（建议/回测/优化/保存/调度）
- [ ] 双均线：输入参数 → 生成建议 → 回测 → 权益曲线/指标卡 → 保存
- [ ] DCA：定投参数 → 回测（验证买入次数与止盈逻辑）→ 保存
- [ ] MACD：预热期不交易 → 金叉买入 → 保存
- [ ] 已保存策略列表按类型显示，载入/暂停/删除可用
- [ ] 每日 15:20 调度对新策略生效（`next_run_at` 显示）
- [ ] 断网回测降级到本地缓存（`dataSource: local` + 来源角标）

## 工作分解建议

本项体量较大，实施计划拆分为 3 个 feature：
1. **strategy-engine-core**：`compute_metrics` 抽取 + `strategy_engines.py` 三引擎 + 单测
2. **strategy-storage-api**：`Strategy`/`StrategyBacktest` 表 + 存储函数 + `/api/strategy/*` + 调度器泛化 + API 测试
3. **strategy-lab-ui**：前端策略实验室（类型切换/通用表单/统一结果/已保存列表）+ nav 改名 + 闭包检查 + 手动验收

每步完成即合并 develop，保持可运行。