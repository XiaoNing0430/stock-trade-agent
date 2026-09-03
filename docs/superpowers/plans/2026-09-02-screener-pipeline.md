# 策略选股管道实施计划（三层分离 + 混合管道）

> **For agentic workers:** Use superpowers:executing-plans (inline) to implement this plan task-by-task.

**Goal:** 在统一数据源接入层之上构建策略选股引擎：候选池（screener 能力）→ 本地因子精筛（history 能力）→ 财务增强（fundamental 能力），策略配置声明式（JSON），结果缓存 30 分钟。生产级要求：无未来函数（reference_date 基准）、缓存击穿防护（互斥锁）、降级兜底（stale 标记）、结构化可观测性（stage_timings + 埋点日志）。

**架构（用户方案落地适配）：**

```
策略定义层  backend/screener/configs/*.json（quick_filters + advanced_factors + top_n）
     ↓
选股引擎层  backend/screener/pipeline.py（ScreenerPipeline）
     ├─ 基准日期：reference_date（默认 = screener 源 calendar.previous_trading_day(today)）
     ├─ 粗筛：Router.route("screener") → load_screener("全部", 500) → 本地 quick_filters
     ├─ 排除：ST（名称含 ST）/*ST、停牌（最新量价缺失）、price=None
     ├─ 精筛（deep）：ThreadPoolExecutor(max_workers=5) 并行 load_history(limit=60) → 因子评分
     │                （bars 统一截断至 reference_date，杜绝未来函数；
     │                  池大小=并发上限 ≤5 + 工作线程内 min-interval 0.1s 限速 ≤10 req/s + 阶段 deadline 45s）
     ├─ 增强：top_n 调 load_fundamentals（fundamental 源）补 ROE/市值
     ├─ 缓存：内存 TTL 30min；key = screener:{strategy_id}:{mode}:{market}；
     │        strategy_id 维度互斥锁（防击穿）；refresh=True 强制重算
     ├─ 降级：全源失败 → 返回过期缓存 + stale=True；无缓存才抛 502
     └─ 观测：stage_timings{screen/history/factor/enrich} + 埋点日志（候选数/排除数/精筛成功数）
     ↓
数据接入层  backend/sources/（既有 Router，零改动）
```

**⚡ 强制落地要求（审核补充，必须执行）：**
1. **缓存键 = `screener:{strategy_id}:{mode}:{market}`** — mode（quick/deep）与 market 必须入键：quick 与 deep 结果互不覆盖；MockUS 与 EastMoney 数据不串缓存。market 取路由选中 screener 源的 `calendar.market`（CN/US）——Router 本身市场无关，不新增 `current_market` 概念。
2. **history 并行拉取的限频与韧性（三层机制，均在管道层）** —
   - **并发上限**：`ThreadPoolExecutor(max_workers=5)`——池大小即并发上限，在途请求 ≤5。**不用 Semaphore**：池已提供该保证，叠加冗余；也**不用 `with` 上下文**（其 `shutdown(wait=True)` 会阻塞等待挂死线程），手动 `shutdown(wait=False, cancel_futures=True)`。
   - **频率上限**：工作线程内**共享 `threading.Lock` + min-interval 0.1s**（每次 HTTP 前 acquire，距上次请求 <0.1s 则等待）——硬上限 ≤10 req/s，匹配东财隐形限频（10-20/s）下沿，200 票约 20s。复用 `data_source._throttle()` 已验证的模式；**同时兜底 EastMoneySource._http_get 无内置限频的问题**（腾讯路径 `_throttle()` 仅覆盖 data_source.py）。
   - **不设 future 级单票超时**：限速队列下 `future.result(timeout=2.5)` 从提交时刻计时，排队 >2.5s 的票会被误杀，深度精选只剩前 ~25 只——语义错误，故移除。单票挂死由适配器内 `requests timeout=10s` 硬兜底（两源均有）。
   - **阶段 deadline（默认 45s）**：`concurrent.futures.wait(fs, timeout=45)` 超时 → `cancel_futures` + `logger.warning` + **部分结果继续管道**（候选多时降级为部分精筛，绝不死锁）。deadline 可由策略配置 `history_deadline_s` 覆盖。
3. **前端极速/深度映射 mode 参数，默认极速** — quick = 粗筛 + 本地 quick_filters，**绝不调 load_history**；deep = 全管道。默认 quick（首屏要快），深度模式用户手动触发。

**🛡️ 生产级韧性（第二轮评审强制要求，Task 3 实现前必须写入）：**

4. **杜绝未来函数（Look-ahead Bias）** — `run(strategy_id, mode, refresh, reference_date=None)`：
   - `reference_date` 默认 = 路由选中 screener 源的 `calendar.previous_trading_day(date.today())`（不是今天）；显式传入时校验 `YYYY-MM-DD` 格式，非法 → 422。
   - deep 模式拉取 `limit+2` 根 bars，**管道层截断** `bar["date"] <= reference_date` 再取末 60 根做因子 —— 不改 DataSource ABC 签名（`load_history` 无 end_date 参数），三适配器零改动。字符串 ISO 日期比较。
   - 响应体携带 `referenceDate`，前端结果表展示基准日期。
5. **缓存击穿防护** — `_locks: dict[cache_key, threading.Lock]`（`setdefault` 原子建锁）+ **双重检查**：锁内再次查缓存，命中即返回；仅持锁者计算。锁粒度 = 完整 cache_key（strategy×mode×market），非仅 strategy_id。
6. **降级兜底** — 过期条目**不删除**（标记过期）；计算抛异常时：有旧条目 → 返回旧结果 + `stale: true` + `logger.warning`；无旧条目 → 才抛错（API 层 502）。响应体增加 `stale: bool`，前端展示"数据可能滞后"横幅。
7. **可观测性** —
   - 每次 `run()` 生成 `trace_id`（uuid4）贯穿日志；用 stdlib `logging` + 结构化 extra 字段（`logger.info("screener.stage", extra={"trace_id":..., "stage":..., "ms":..., "count":...})`）。**不引入 structlog 新依赖**（记录偏差：观测目标用标准库达成，structlog 留作全局日志改造时统一决策）。
   - 响应 `debug` 字段：`{traceId, stageTimings: {screenerMs, historyMs, factorMs, enrichMs}, counts: {raw, afterExclude, afterQuick, scored}}`（生产可用配置开关关闭）。
   - 数据质量告警：粗筛行数异常（如 < 50 而 total 声称数千）→ `logger.warning` 埋点。

**快照时间点一致性的诚实说明（偏差记录）：** 免费行情 API（腾讯排名/东财 clist）只返回**实时快照**，无法请求"昨日收盘快照"——quick_filters 的 PE/PB 按最新快照评估，无法强制回溯到 reference_date。完全的 point-in-time 一致需要自建因子库/时点数据库，超出本阶段范围（列入非目标）。本管道的定位是**当日实盘选股**（用当下信息决策，合法无偏），未来函数风险集中于**时序因子**——该部分已由 reference_date 截断彻底解决；两者在响应中分别以 `referenceDate`（因子基准）与快照时间戳标注，不混同。回测场景须等 point-in-time 数据层就绪后再做（见非目标）。

**对原方案的三点适配（记录偏差理由）：**
1. 粗筛 = API 拉取候选池 + 本地过滤（纯 Python 毫秒级），不在 ABC 加 filters 参数 —— 避免改动三个适配器签名；东财 clist 服务端过滤留作后续增强。
2. 并行用 `ThreadPoolExecutor(max_workers=5)` + 工作线程内 min-interval 0.1s 限速（≤10 req/s）+ 阶段 deadline 45s，而非 asyncio.gather —— 现有栈是同步 requests，线程池即可且不改事件循环；并发/频率/灾难兜底三层各司其职（详见强制要求 2）。
3. FactorLibrary 编排 `backend/indicators.py` 既有 10 函数（rsi/bollinger/momentum/deviation/ma…），不重复实现。

**Tech Stack:** Python / FastAPI（无新依赖），Vue 3 + Pinia。验证：pytest TDD + vitest + vue-tsc + npm run build。

---

### Task 1: FactorLibrary（TDD）

**Files:** `backend/screener/__init__.py`, `backend/screener/factors.py`, `tests/test_screener_factors.py`

- **Step 1 失败测试：**
  - `test_factor_library_lists_factors` — `FactorLibrary.available_factors()` 含 rsi/ma_slope/ma_arrange/bollinger_pos/momentum/deviation/volume_surge
  - `test_compute_factor_rsi` — 构造单调下跌 bars → rsi(14) < 30 判定为 True
  - `test_compute_factor_unknown_raises` — 未知因子名抛 ValueError
  - `test_evaluate_condition_operators` — `>`, `<`, `>=`, `<=` 四算子
  - `test_score_breakdown` — 多因子加权求和，返回 {score, factors:{name:{value,met,weight}}}
- **Step 2 实现：** `factors.py` 纯函数编排 indicators.py；`score_candidate(bars, advanced_factors) -> dict`。
- **Step 3：** pytest 绿 → 提交 `feat: 选股因子库（编排 indicators 既有指标）`

### Task 2: 策略配置加载（TDD）

**Files:** `backend/screener/configs/oversold_bounce.json`, `backend/screener/configs/trend_breakout.json`, `backend/screener/loader.py`, `tests/test_screener_loader.py`

- **Step 1 失败测试：** `list_strategies()` 返回内置 2 策略；`load_strategy("oversold_bounce")` 校验必填字段（name/quick_filters/advanced_factors/top_n）；非法策略名抛 ValueError。
- **Step 2 实现：** pydantic `ScreenerStrategyConfig`（schemas.py 或 loader 内）；JSON 示例：

```json
{
  "id": "oversold_bounce",
  "name": "超跌反弹",
  "description": "RSI 超卖 + 短期均线走平的反弹候选",
  "quick_filters": {"pe": [0, 25], "pb": [0, 5], "turnoverRate": [0.3, null]},
  "advanced_factors": [
    {"name": "rsi", "period": 14, "operator": "<", "threshold": 30, "weight": 2},
    {"name": "ma_slope", "period": 20, "operator": ">", "threshold": 0, "weight": 1}
  ],
  "sort_by": "changePct",
  "top_n": 10,
  "deep_cap": 200
}
```

- **Step 3：** pytest 绿 → 提交 `feat: 声明式选股策略配置与加载器`

### Task 3: ScreenerPipeline（TDD）

**Files:** `backend/screener/pipeline.py`, `tests/test_screener_pipeline.py`

- **Step 1 失败测试（全 mock Router/源）：**
  - `test_quick_mode_returns_top_n` — quick 模式：mock screener 行 → quick_filters 过滤 → 按 sort_by 排序 → top_n；**断言全程未调 load_history**
  - `test_deep_mode_scores_factors` — deep 模式：mock history bars → 因子评分排序
  - `test_reference_date_truncates_bars` — **传入 reference_date 后，晚于该日的 bars 被剔除再算因子**（构造 bars 中混入未来日期，断言因子值与仅用历史数据算出的一致）；默认 reference_date = calendar.previous_trading_day(today)
  - `test_reference_date_invalid_format_422` — 非法日期格式抛 ValueError（API 层映射 422）
  - `test_cache_lock_prevents_stampede` — **并发 10 线程同参调用，load_screener 只被执行 1 次**（计数器断言；锁内双重检查）
  - `test_degraded_returns_stale_cache` — **重算抛异常 + 存在过期缓存 → 返回旧结果且 stale=True**；无旧缓存 → 抛错
  - `test_excludes_st_and_suspended` — 名称含 ST、price=None、volume=0 的行被排除
  - `test_result_cached_30min_and_refresh_bypasses` — 二次调用走缓存；refresh=True 重算
  - `test_cache_key_distinguishes_mode_and_market` — **同 strategy 不同 mode/不同 market 缓存互不覆盖**（CN 源与 US 源各自独立条目）
  - `test_deep_cap_limits_history_fetches` — 候选 500 时 history 调用数 ≤ deep_cap
  - `test_pool_size_caps_inflight_requests` — **并发探测：包装 load_history 记录在途峰值，断言峰值 ≤5**（池大小=并发上限；200 候选全请求也不超限）
  - `test_rate_limit_enforces_min_interval` — **记录相邻两次 HTTP 请求时间戳，断言间隔 ≥0.1s**（≤10 req/s 硬上限；mock 200 票采样断言）
  - `test_stage_deadline_returns_partial_results` — **mock 部分票 history 挂起 >deadline，concurrent.futures.wait 超时 → 已完成票正常评分返回 + warning**（绝不整体死锁）；策略配置 history_deadline_s 可覆盖默认 45s
  - `test_debug_stage_timings_and_trace_id` — 响应含 traceId、stageTimings{screen/history/factor/enrich}、counts{raw/afterExclude/afterQuick/scored}
- **Step 2 实现：** `ScreenerPipeline(router).run(strategy_id, mode, refresh, reference_date)`；bars 截断至 reference_date；缓存互斥锁 + 双重检查；降级返回 stale；线程池并行 history（**max_workers=5 即并发上限、工作线程内共享锁 min-interval 0.1s ≤10 req/s、阶段 deadline 45s（wait+cancel_futures+部分结果）、shutdown(wait=False, cancel_futures=True)、无 future 级超时**）；fundamental 增强（top_n ≤10 次请求，源缺 fundamental 时静默跳过）；结构化埋点日志（trace_id 贯穿）。
- **Step 3：** pytest 绿 → 提交 `feat: 混合选股管道（粗筛→精筛→增强→缓存）`

### Task 4: API 端点（TDD）

**Files:** `backend/app.py`, `backend/schemas.py`, `tests/test_backend_api.py`

- **Step 1 失败测试：** `GET /api/screener/strategies` 列出策略；`POST /api/screener/strategy`（body: strategy / mode 默认 **"quick"** / refresh 默认 false / referenceDate 可选 "YYYY-MM-DD"）返回 `{rows, total, mode, cached, stale, referenceDate, elapsedMs, provider, debug?}`；未知策略 422；缓存命中 cached=true；降级命中 stale=true；非法 referenceDate 422。
- **Step 2 实现：** Pydantic 模型 + 两端点；provider 取 screener 源 provider_label。
- **Step 3：** pytest 全绿 → 提交 `feat: 策略选股 API（列表 + 运行）`

### Task 5: 前端「策略」标签页

**Files:** `frontend/src/stores/useScreenerStore.ts`, `frontend/src/views/ViewScreener.vue`, `tests/frontend/ViewScreener.test.ts`

- store：`strategyMode`、`strategies`、`strategyName`、`strategyRunMode`（**默认 'quick'**）、`strategyRows`、`strategyLoading`、`strategyCached`、`strategyStale`、`runStrategy()`、`loadStrategies()`
- 视图：第三个 tab「策略」；策略下拉 + **极速/深度切换（默认极速）** + 运行按钮；结果表（代码/名称/评分/关键因子/PE/PB）；结果头部展示**基准日期 referenceDate**；缓存命中提示；**stale=true 时展示"数据可能滞后"警告横幅**；深度模式标注预计耗时较长
- vitest：tab 切换、运行调用 requestJson、结果渲染
- 提交 `feat: 前端策略选股标签页`

### Task 6: 收尾

- `npm run verify` 全量回归
- 观测性验收：本地跑一次 deep 策略，粘贴结构化日志输出（trace_id + stage_timings）作为验收证据；确认 debug 字段可通过配置开关关闭
- ROADMAP 更新（新策略类型下补「策略选股管道」条目，标注 reference_date/降级/观测特性）
- `git flow feature finish screener-pipeline` → push develop

---

## 非目标

- 不做服务端 clist filter 表达式下推（后续增强）
- 不做分钟级/实时选股（日频定位，绝不进入 load_quotes 实时链路）
- **不做回测**（因子评分回测需要 point-in-time 时点数据库——免费快照 API 无法提供历史时点快照，粗筛 PE/PB 存在快照时点偏差；详见"快照时间点一致性的诚实说明"。回测是独立 feature，须等 point-in-time 数据层就绪）
- 不引入 structlog/Prometheus 新依赖（观测性用 stdlib logging 结构化字段达成；全局日志/监控体系是独立工程改造）
- ROE 不进粗筛（仅 top_n 增强展示，避免 N 次财务请求触发限频）
