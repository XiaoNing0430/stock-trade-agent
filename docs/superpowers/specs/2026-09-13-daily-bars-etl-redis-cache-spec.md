# 全市场日线 ETL + Redis 行情缓存接管（P2 数据中台）— 设计规格 r1

日期：2026-09-13 ｜ 状态：**待用户评审（评审通过前不进入计划/实现）** ｜ 上游：ROADMAP「P2 Redis 行情缓存接管」「P2 全市场日线落库」
定位：数据基础设施两里程碑，M1（日线 ETL）与 M2（Redis 接管）**相互独立、可独立交付回滚**；共享"降级不静默"纪律。
红线不变：绝不造数；ETL/缓存缺口一律如实暴露为回源、degraded 或 stale。

## 0. 术语

| 术语 | 定义 |
|---|---|
| bfq（不复权） | `market_bars.adjustment=''` 口径，真实成交价，永不因新除权漂移；复盘/组合设计口径同源 |
| universe | ETL 维护的全市场代码集合（§3.2），**不含北交所**（§9 限制） |
| 权威水位 watermark | 最近一个"应已收盘交易日"（交易日历推算）；ETL 健康度与冒烟断言的锚 |
| 日补 / 回补 | 日补=只补各码缺失的最近若干交易日；回补=首装/深度缺口时一次拉满 500 根 |
| CacheFacade | M2 的三级缓存门面：L1 进程 dict（现状）→ L2 Redis → loader 上游 |

## 1. 决策（评审已定项，来源=本轮问答）

- **D1 组织**：一份 spec 两里程碑；计划期 M1→M2 依序执行。
- **D2 深度**：每码 bfq 500 根（覆盖组合/复盘 300 bars 窗 + 缓冲）。
- **D3 口径**：ETL 仅维护 bfq。qfq 维持按需缓存现状（其遇新除权整体漂移的性质如实写入 §9，不为其建 ETL——bfq 真实价无此问题）。
- **D4 增量**：日补模式=每交易日只补缺失日 bar（含除权日全序列漂移？否——bfq 不漂移，历史永不重写；发现单日缺 bar 逐日自愈）。每晚重拉近 30 根的替代案已议**拒绝**（bfq 无修正需求，上游浪费 ×30）。
- **D5 消费端零改动**（论证 §3.5）：不改 `fetch_all_bars`/`_counting`/degraded 语义；ETL 新鲜度天然使复盘/组合端点 upstream→0。
- **D6 Redis 范围**：仅行情快照缓存（`data_source.cached` 路径）。选股中间缓存、行业映射、扫描去重态**不进 Redis**（各 TTL/一致性策略不同，YAGNI）。
- **D7 降级方向**：Redis 挂→纯 L1 + 上游（即今天的行为），带熔断防打穿；**绝不**因 Redis 故障返回假数据。
- **D8 存储**：零新表零迁移——复用 `market_bars`（唯一键 `code,trade_date,adjustment` 即 upsert 幂等键；per-code max 查询走该索引）。
- **D9 拒绝项**：数据仓库层/分区/PIT 快照归档（P3 领域）、akshare 批量入仓（东财链路单点昨天实证）、分钟线（独立 P2 条目）、多 worker 部署优化（单用户本地定位）。

## 2. 现状事实（设计依据，均实测/读码确认）

- 行情缓存：`data_source.py:79` 进程 dict（TTL 下限 2s）+ `cache_lock` + stale 兜底（`STALE_MAX_AGE` 内 loader 抛错回陈旧值并 `mark_stale`）。
- 日线表：`market_bars` 现仅 11 码/1601 行（bfq 2 码 + qfq 9 码）；`fetch_all_bars`（`plan_review.py:202`）逐码 DB 优先、**近 7 日内视为新鲜不回源**、单码容错收集、失败聚合抛 `ReviewUpstreamError(codes, partial)`。
- Redis：`settings.py` 已配（192.168.0.114:6379），仅 `storage_status()` ping 用于 `/api/health`，零业务键。
- 调度：`app.py:238` lifespan 内 `scheduler.add_job`（APScheduler 单例），行业预热 30s 首刷+24h 间隔模式为样板。
- 交易日历：`CNMarketCalendar`（sources 共用）可推"最近已收盘交易日"。
- universe 源：industry_map 表 5223 行（clist 四段，实测前缀 0/3/6）+ 工作区自选/计划码。
- 上游单点：`push2.eastmoney.com` 域名级 RST 事件（2026-09-13）——日线 ETL 走**腾讯** kline（历史链路本就是腾讯主源），不新增东财依赖。

## 3. M1：全市场日线 ETL（`backend/bars_etl.py`）

### 3.1 组件与依赖
`bars_etl` 纯新模块，只依赖：`storage`（读写 market_bars/industry_map）、`data_source`（经 `DataSourceRouter.route_with_fallback` 取 history 能力源，与端点同源注入面）、`grid_scheduler.scheduler`（注册处）。被调方零感知：lifespan 注册 job + 测试直调。

### 3.2 universe 解析
`resolve_universe() -> list[str]`：industry_map 全表 code ∪ workspace 表 distinct(watchlist.code, trade_plans.code) ∪ 指数三码（`_INDEX_SECID` 同源常量：000001/399001/399006）。排序去重；**北交所（4/8 起）不在 clist 四段**→不强行扩 fs（东财依赖），腾讯 ranking universe 亦不含全量北交所——限制入 §9。指数码走 `is_index=True` 拉取。

### 3.3 水位与缺口检测
`authoritative_watermark() -> str`（日历推算的"应已收盘交易日"，进程缓存 60s）；`detect_gaps() -> dict[str, list[str]]`：单次 `SELECT code, max(trade_date) FROM market_bars WHERE adjustment='' GROUP BY code`（索引覆盖，百万行内 ms 级），对比水位分三档：`missing`（无行）/ `stale_deep`（落后 >10 交易日 → 走回补拉 500）/ `stale_light`（≤10 → 日补拉 limit=max(20, 落后数+5) 重叠写幂等覆盖）。水位当日已齐的码进 `up_to_date` 不请求。**休市日/节假日整轮跳过**（水位==库内多数码水位时 no-op，`skipped_nontrading` 统计）。

### 3.4 执行流（`run_full(force=False) -> EtlStats`）
单 job 串行三阶段：回补档（stale_deep+missing）→ 日补档（stale_light）→ 汇总日志。
- 并发与限频：**复用全局 `_throttle()`（≤10 req/s 纪律）+ 顺序拉取**（单用户环境无需并发；~5223 请求 ≈ 9-15 分钟可接受），每 500 码分批提交。
- 单码失败：重试 1 次（同 loader 自带 retry 面），仍失败→记 `failed[]`（≤50 字截断入日志，全量入 stats），**不阻断**；连续失败占比 >20% 提前熔断本轮（上游疑似整体故障，下轮自愈），防无脑刷 5223 个失败。
- 写入：`storage.save_market_bars(code, bars, adjustment='')` 现成 upsert；仅接受 `trade_date ≤ watermark` 的 bar（防盘中半日 K 入库——腾讯盘中即有当日 kline，**未收盘不落**，15:20 触发时已收盘，防御性再挡一道）。
- `force=True`（手动/测试）：忽略 up_to_date 判定，全量按日补档重拉。
- 首装回补=启动自愈 job 的自然特例（全库 missing → 全量回补一轮），无独立代码路径；启动预热延 60s 首查、其后每交易日 15:20（错开 15:40 扫描）+ 每周六 10:30 自愈审计。注册失败仅日志（同行业样板），**绝不影响 API 启动**。

### 3.5 消费端对齐（零改动的论证与边界）
`fetch_all_bars` DB-fresh 判据=行存在且 `last_date ≥ now−7d`。ETL 日补后该条件恒真 → loader 不被调、upstream=0、degraded 空——**无需任何判据改动**。边界：ETL 未覆盖码（北交所/新股/失败遗留）自然走现状回源+local 兜底语义，披露体系不变。风险自查：ETL 停摆 >7 天时复盘端点悄悄回到全回源（性能退化非正确性退化）——由 health 水位暴露 + 冒烟断言防呆（§8）。

### 3.6 可观测
- 日志：`bars_etl_ok universe=%d up_to_date=%d backfill=%d daily=%d fetched=%d failed=%d watermark=%s elapsed_ms=%d`（logger 复用 `atlas.review` 惯例族，命名 `atlas.bars_etl`）；熔断/注册失败 warning。
- `/api/health` 扩 `bars` 位：`{watermark, freshCount, universeSize, lastRunAt}`（单次 GROUP BY + 日历，ms 级，Redis ping 同款"不造假：查询失败回 null"）。

## 4. M2：Redis 行情缓存接管（`backend/redis_cache.py` + `data_source.cached`）

### 4.1 CacheFacade 接口（可注入，离线测试零真连）
```python
class CacheFacade:
    def __init__(self, redis_factory, ttl_getter, log=logger): ...
    def get(self, key: str) -> Any | None            # L1 命中→L2 命中回填 L1→None
    def set(self, key: str, value: Any, ttl: int)    # 双写；L2 异常吞+计数
    def take_stale(self, key: str, max_age: float) -> Any | None   # L1→L2 的降级读
```
`data_source.cached()` 内部**只换存储层**：现 `cache` dict 成为 L1、Facade 增加 L2；stale 兜底语义（`STALE_MAX_AGE`）在 L1/L2 双层同规则——值内封装修写时间戳 `{"ts": ..., "v": ...}`，Redis `SET PX` 存剩余寿命；L2 读出后**按装修 ts 复核**（超过 `_cache_ttl + 5s` 宽限即弃用，防双 TTL 漂移窗口取到过期值）。

### 4.2 键与数据量
键前缀 `atlas:quote:`；value=现缓存值 JSON（quote dict/list，KB 级）；>128KB 的 value 跳过 L2 写并 debug 日志（防御异常大对象，如全市场 dump 走同 facade 的场景不存在但兜底）。TTL 跟随 `apply_runtime_config` 的 `_cache_ttl`（运行时可配语义不变）。**清理**：L2 依赖 Redis 自身 TTL 过期，无 sweep job。

### 4.3 故障与熔断
Redis 客户端不可达/超时（`socket_connect_timeout=1s`，读超时 0.5s，redis-py 已在依赖）：连续 3 次失败 → **旁路熔断 30s**（期间纯 L1，等价现状），恢复探测自动关闭熔断。熔断期开始/结束各一条 `redis_cache_degraded` / `redis_cache_recovered` 日志。loader 上游异常路径完全不变（stale 兜底优先 L1 再 L2）。`/api/health` 的 `redis` 位升级为反映 facade 实际状态（connected|bypassed|down，storage_status 微扩），前端健康条零改。

### 4.4 范围守卫
`cached()` 的全部现有 key（quotes/kline 短请求）即接管全集；不新增 key 族、不给 screener/scan/industry 使用（D6）。多进程共享效果**不作为验收条件**（单进程现状；但键设计天然多进程安全）。

## 5. 接口冻结（计划期唯一执行依据）

| # | 接口 | 签名/语义 |
|---|---|---|
| I1 | `bars_etl.resolve_universe()` | `-> list[str]` 去重升序，含指数三码；纯查询零副作用 |
| I2 | `bars_etl.authoritative_watermark(now=None)` | `-> "YYYY-MM-DD"` 最近已收盘交易日；60s 进程缓存；`now` 注入为测试面 |
| I3 | `bars_etl.detect_gaps()` | `-> {"missing":[...],"stale_deep":[...],"stale_light":[...],"up_to_date":int}` |
| I4 | `bars_etl.run_full(force=False, *, fetch=None)` | `-> EtlStats`（dataclass：universe/up_to_date/backfill/stale_deep_count/daily/daily_count/fetched/failed(list[str])/watermark/elapsed_ms/aborted——即 §3.6 日志字段化）；`fetch` 注入拉码线单测 |
| I5 | `bars_etl.bars_health()` | `-> dict|None`（§3.6 health 位；查询异常回 None 不造假） |
| I6 | `redis_cache.build_facade(settings)` | `-> CacheFacade`；settings 缺 redis → facade 永久旁路态（等价现状） |
| I7 | `CacheFacade` 四类 | §4.1 签名冻结；测试注入 in-memory fake |
| I8 | `data_source.cached(key, loader)` | **外部行为逐字不变**（TTL/stale/lock 语义），仅内部换存储层 |
| I9 | health `bars` / `redis` 位 | 附加键，零现有字段改名 |

## 6. 数据模型与迁移

**零迁移。** `market_bars` 表结构不变；容量预估：5223 码 × 500 根 ≈ 260 万行（bfq 单基线，行宽 <200B → <600MB）。现有唯一约束 `(code, trade_date, adjustment)` 覆盖 ETL/检测查询形态。北交所/指数入库同表无特例列。

## 7. 错误与诚实披露矩阵

| 故障 | 行为 | 暴露 |
|---|---|---|
| 单码拉取失败（重试后） | 跳过，下轮自愈 | EtlStats.failed + warning |
| 失败率>20% | 本轮熔断 | `bars_etl_aborted` error 日志 + failed 计数 |
| 盘中/未来日 bar | 拒收（trade_date>watermark 丢弃该根） | stats 计数 |
| ETL 长期停摆 | 消费端自动回退逐码回源（≤7d 窗口内仍新鲜） | health.bars 水位落后 + 冒烟断言 |
| Redis 挂 | L2 旁路，行为=现状；不阻断双写 L1 | health.redis=bypassed/down + 熔断日志 |
| Redis 慢（超时） | 0.5s 超时视同失败计入熔断 | 同上 |
| loader 上游失败 | 现 stale 链不变（L1→L2 陈旧值→抛错） | mark_stale/现状 |

## 8. 测试策略

- **M1 离线**：fake `fetch` 注入——回补/日补三档路由、休市 no-op、部分失败收集、熔断阈值、未来 bar 拒收、`force` 重拉、upsert 幂等（同 bar 重放行数不变）；`detect_gaps` 用 tmp 真 PG 预置三档数据断言集合相等。
- **M1 真实冒烟**（一次性脚本，同 smoke v2 模式）：全量 `run_full` → health.bars freshCount/universeSize 比 ≥95% → 抽 3 码逐日对拍端点回放 vs 直接腾讯拉取（真实数据核对）→ 复盘端点 upstream=0 断言（证明 §3.5 传导成立）。
- **M2 离线**：in-memory fake redis（duck-type get/set/keys/ping + 可编程抛错）——L2 命中回填、TTL 过期模拟（fake 时钟）、双写、熔断三态转换、旁路下 loader 正常、>128KB 跳写、`cached()` 既有测试文件**零修改全绿**（I8 行为不变的机器证明）。
- 门禁沿用全量七件套；新增测试预计 +35~45 项。

## 9. 已知限制 / 非目标

北交所不入 universe（clist fs 无该段且拒绝新依赖东财扩段；相关计划/自选标的继续走现状按需回源，degraded 如实）；qfq 缓存遇新除权漂移维持现状 7 天重取缓解（ETL 不做 qfq 的理由即 D3）；500 根深度之外的超长历史回放仍回源；ETL 停摆 >7 天性能退化无告警外手段（单用户本地工具，health+冒烟为界）；不做分钟线/分区/PIT/多 worker 优化（D9）；选股器与扫描中间缓存不进 Redis（D6）；`/api/bars/etl/run` 手动触发 API **不做**（force 走脚本/测试，本地工具无需 HTTP 面；health 已给观测）。

## 10. 成功判据（验收）

1. 连续两交易日 15:20 后：health.bars `watermark==当日`、`freshCount/universeSize ≥ 0.95`；
2. 冒烟：`/api/plans/review` 与 `/api/portfolio/risk` 在冷进程（清 L1）下 `upstream ≤ 1`（指数或北交所零星码允许）且 `degraded=[]`；
3. 重启后端：/api/health redis=connected，行情轮询期上游请求计数较接管前下降（冒烟打印对比，L2 命中的直接证据=进程日志无对应 `_throttle` 触发的请求）；
4. 拔 Redis（停容器/断线）：行情轮询无感（L1+上游现状行为），health.redis 变 bypassed，恢复后自动回 connected；
5. 全量门禁+`cached()` 既有测试零修改全绿。
