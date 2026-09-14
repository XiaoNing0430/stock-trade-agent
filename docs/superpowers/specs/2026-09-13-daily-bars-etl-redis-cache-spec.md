# 全市场日线 ETL + Redis 行情缓存接管（P2 数据中台）— 设计规格 r2

日期：2026-09-13 ｜ 状态：**待用户评审（评审通过前不进入计划/实现）** ｜ 上游：ROADMAP「P2 Redis 行情缓存接管」「P2 全市场日线落库」
评审史：r1 对抗评审判**须修订**（3×P0：指数键污染 / 空响应静默成功 / 日历无时刻粒度；6×P1；2×P2）——r2 全部吸收，修订处以 ⟲ 标记。「生产级量化网站」轴评审（分布式调度/多租户/TLS/Redis HA/Prometheus/备份演练）**依据 AGENTS 红线与单用户本地定位整体拒绝**，理由与边界记入 §9。
定位：数据基础设施两里程碑，M1（日线 ETL）与 M2（Redis 接管）**相互独立、可独立交付回滚**；共享"降级不静默"纪律。
红线不变：绝不造数；ETL/缓存缺口一律如实暴露为回源、degraded 或 stale。

## 0. 术语

| 术语 | 定义 |
|---|---|
| bfq（不复权） | `market_bars.adjustment=''` 口径，真实成交价，永不因新除权漂移；复盘/组合设计口径同源 |
| universe | ETL 维护的代码集合（§3.2），全市场=clist 四段（**无北交所**），另含工作区码（北交所工作区码**入内** ⟲，腾讯 bj 前缀现成） |
| 权威水位 watermark | 最近一个"应已收盘交易日"（**时刻粒度** ⟲，§3.3）；ETL 健康度与冒烟断言的锚 |
| 日补 / 回补 | 日补=只补各码缺失的最近若干交易日；回补=首装/深度缺口时一次拉满 500 根 |
| CacheFacade | M2 的三级缓存门面：L1 进程 dict（现状）→ L2 Redis → loader 上游 |

## 1. 决策（评审已定项）

- **D1 组织**：一份 spec 两里程碑；计划期 M1→M2 依序执行。
- **D2 深度**：每码 bfq 500 根（覆盖组合/复盘 300 bars 窗 + 缓冲）。
- **D3 口径**：ETL 仅维护 bfq。qfq 维持按需缓存现状（其遇新除权整体漂移的性质如实写入 §9）。
- **D4 增量**：日补只补缺失日；bfq 真实价历史永不重写（除权不漂移）。每晚重拉近 30 根替代案已议**拒绝**。
- **D5 消费端零改动**（论证 §3.5）：不改 `fetch_all_bars`/`_counting`/degraded 语义；ETL 新鲜度天然使复盘/组合端点 upstream→0。**唯一例外=附带缺陷修复 A1（§3.7）**。
- **D6 Redis 范围** ⟲：仅 `quotes:*` 与 `history:*` 两 key 族进 L2；**`screener_v2:*` 显式排除**（全市场排名页 payload 大、命中面广、失效策略不同——维持 L1-only 现状），白名单写进 I8 断言。选股中间缓存、行业映射、扫描去重态不进 Redis。
- **D7 降级方向**：Redis 挂→纯 L1 + 上游（即今天的行为），带熔断防打穿；绝不因 Redis 故障返回假数据。
- **D8 存储**：零新表零迁移——复用 `market_bars`；⟲ 但**新增批量 upsert 存储接口**（I10，性能预算所需，§3.4）。
- **D9 拒绝项**：数据仓库层/分区/PIT、akshare 批量入仓（东财 RST 单点 2026-09-13 实证）、分钟线、多 worker/分布式调度（§9 生产级边界）、**指数入 ETL**（⟲ P0：`(code,trade_date,adjustment)` 唯一键无 is_index 维，指数 000001 与平安银行 000001 **同键互覆**，回放个股会静默取到指数价且 7 天判据使其永不回源——指数维持现状 qfq 按需链路）。

## 2. 现状事实（设计依据，读码/实测确认）

- 行情缓存：`data_source.py:79` 进程 dict + `cache_lock`；`cached()`（:131）TTL 下限 2s，loader 抛错时 `STALE_MAX_AGE=1800s` 内回陈旧值并 `mark_stale`。现存 key 族：`quotes:{symbols}`（:312）、`history:{symbol}:{limit}:{fq}`（:333）、`screener_v2:{...}`（:485）。
- 日线表：`market_bars` 现 11 码/1601 行；`fetch_all_bars`（`plan_review.py:202-225`）逐码 DB 优先、近 7 日新鲜不回源、单码容错、`ReviewUpstreamError(codes, partial)`。
- **上游失败形态** ⟲：腾讯限频/坏 payload 时 `load_history` 返回 **`[]` 不抛**（`data_source.py:336-338` 语义），`save_market_bars([])` 零写零异常（`storage.py:692`）——"空=成功"洞必须显式封堵（§3.4）。
- **日历能力边界** ⟲：`CNMarketCalendar.is_trading_day` 实为 weekday<5（`cn_impl.py:20-22`），**无节假日表、无时刻粒度**——水位算法自持 Asia/Shanghai 15:05 规则，假日盲区如实披露（§9-L3）。
- Redis：`redis==5.2.0` 在依赖清单；`settings.py` 已配（192.168.0.114:6379）；现仅 `storage_status()` ping 用于 `/api/health`。
- 调度：`app.py:238` lifespan `scheduler.add_job`（行业预热 30s+24h 样板）；`tencent_symbol` 支持 bj 前缀（`data_source.py:170`）。
- universe 源：industry_map 表 5223 行（前缀实测 0/3/6）；**其首刷依赖东财 clist——恰是本 spec §2 记录的 RST 单点**（软依赖竞态见 §3.2 护栏）。
- 既有隐患 A1 ⟲：`app.py:417` 指数链路以 `adjustment="qfq"` 落库，000001 指数与平安银行个股**共享同桶已属既有污染**（本 spec 不引入，但随 M1 附带修复，§3.7）。

## 3. M1：全市场日线 ETL（`backend/bars_etl.py`）

### 3.1 组件与依赖
纯新模块，只依赖 `storage`、`data_source`（经 `route_with_fallback` 取 history 能力源，端点同源注入面）、scheduler 注册处。被调方零感知。

### 3.2 universe 解析
`resolve_universe() -> list[str]`：industry_map 全表 code ∪ workspace distinct(watchlist.code, trade_plans.code)（**含 4/8 北交所码**，走腾讯 bj 链路逐码可拉 ⟲）。去重升序。⟲ **护栏**：结果 <2000 码 → 本轮 `aborted=True` + `bars_etl_aborted universe_too_small` warning（防 industry 预热未成时小分母假绿；行业预热 30s 首刷 vs ETL 60s 首查存在竞态，护栏即软依赖兜底，最多随下轮自愈）。**不含指数**（D9-⟲ 键污染）。

### 3.3 水位与缺口检测
⟲ `authoritative_watermark(now=None) -> str`：Asia/Shanghai **时刻粒度**——今日为 weekday 且 `now ≥ 15:05` 才取当日，否则回溯最近 weekday；60s 进程缓存；`now` 参数为测试注入面。假日（weekday<5 真节假日）误判为交易日：日补拉回非空历史、全行 ≤ 水位幂等重写、计 `no_new_bar`——**浪费一次上游请求但数据不为错**（§9-L3）。
`detect_gaps()`：单次 `SELECT code, max(trade_date) ... WHERE adjustment='' GROUP BY code`，四档：`missing`（无行）/ `stale_deep`（>10 交易日 → 回补 500）/ `stale_light`（≤10 → 日补 `limit=max(20, 落后数+5)`）/ `up_to_date`（水位当日已齐，零请求）。

### 3.4 执行流（`run_full(force=False, *, fetch=None) -> EtlStats`）
三阶段串行：回补档 → 日补档 → 汇总。
- 限频：复用全局 `_throttle()`（≤10 req/s），顺序拉取（~5223 请求 ≈ 9-15 分钟）；⟲ 写入按 I10 批量 upsert，每 500 码一事务。
- **失败判定** ⟲：单码拉回 **`bars==[]` 即失败**（空响应不是数据）→ 重试 1 次仍空 → 入 `failed[]`、计入熔断率；拉回非空但无新于库内 max 的 bar → 计 `no_new_bar`（正常，休市/假日形态）。失败率 >20% → 本轮熔断 `aborted=True`（防无脑刷完全体）。
- 写入过滤：仅接受 `trade_date ≤ watermark` 的根（盘中半日 K 双保险；15:20 触发时已收盘）。
- `force=True`（脚本/测试）：跳过 up_to_date 判定全量日补。
- 首装=自然特例（全库 missing → 全量回补），无独立路径；调度：启动 60s 首查自愈 + 每交易日 15:20（错开 15:40 扫描）+ 每周六 10:30 审计；注册失败仅日志，绝不影响 API 启动。

### 3.5 消费端对齐（零改动论证）
`fetch_all_bars` 判据=行存在且 `last_date ≥ now−7d`；ETL 日补后恒真 → loader 不被调、upstream=0、degraded 空。ETL 未覆盖码（全市场北交所/新股空窗）自然走现状逐码回源，披露体系不变。ETL 停摆 >7 天=性能退化非正确性退化（health 水位暴露）。

### 3.6 可观测
日志 `bars_etl_ok universe=%d up_to_date=%d backfill=%d daily=%d no_new_bar=%d fetched=%d failed=%d watermark=%s aborted=%d elapsed_ms=%d`（logger `atlas.bars_etl`）；⟲ `/api/health.bars = {watermark, freshCount, universeSize, lastRunAt}|null`，**结果进程缓存 60s**（GROUP BY 不在轮询热路径逐次执行；缓存过期后的首个 GET 承担一次查询，或旁路回 null——不阻塞不造假）。

### 3.7 附带缺陷修复 A1 ⟲（独立提交，先于 ETL 合入）
指数历史链路（`app.py:417` 面）改以 `adjustment="qfq:idx"` 键空间存取，与个股 qfq 隔离；旧混写行不回溯清理（下次 live 自然覆盖；000001 个股在局部兜底窗口的残余污染风险一次性披露，之后 ETL 的 bfq 桶与 idx 桶均无歧义）。测试：指数与个股同码互不读写。

## 4. M2：Redis 行情缓存接管（`backend/redis_cache.py` + `data_source.cached`）

### 4.1 CacheFacade 接口（可注入，离线测试零真连）
```python
class CacheFacade:
    def __init__(self, redis_factory, ttl_getter, log=logger): ...
    def get(self, key) -> Any | None          # L1 命中→L2 命中回填 L1→None；仅白名单前缀查 L2
    def set(self, key, value, ttl)            # L1 恒写；L2 白名单内双写，异常吞+计入熔断
    def take_stale(self, key, max_age) -> Any | None   # L1→L2 降级读
```
`cached()` 内部只换存储层，**外部行为逐字不变**（I8）。⟲ **语义分家**：L2 值封装 `{"ts","v"}`；`get()` 新鲜读按 `ts` 复核（超 `_cache_ttl+5s` 宽限弃用，防双 TTL 漂移取旧）；**`take_stale()` 只按自身 `STALE_MAX_AGE=1800s` 判定，不受 `_cache_ttl` 复核绞杀**（降级能力不得因 L2 而退化——r1 自相残修订）。

### 4.2 键与数据量
L2 白名单前缀 `atlas:quote:quotes:` / `atlas:quote:history:`（⟲ D6 冻结）；`screener_v2:*` 与未知前缀**永不触 L2**。⟲ `quotes:` 键构造改 `sorted()` 归一（同集合不同顺序同键；返回值组装顺序仍按入参 symbols，语义不变）。value JSON 化，>128KB 跳 L2 写 + debug 日志；L2 依赖 Redis TTL 自过期，无 sweep。`history:` 族键基数=bars 拉取时（5223×limit 组合）有界，L1 现状同形。

### 4.3 故障与熔断
连接超时 1s / 读超时 0.5s；连续 3 次失败→旁路熔断 30s（纯 L1=现状），恢复自动闭合；`redis_cache_degraded`/`redis_cache_recovered` 各一条日志。loader 异常链不变（stale 兜底 L1→L2→抛）。`/api/health.redis` 升级三态 `connected|bypassed|down`（storage_status 微扩，前端健康条零改）。

### 4.4 范围守卫
接管面=`cached()` 全部调用点但仅白名单前缀入 L2（§4.2）；不新增 key 族、不给 screener-pipeline/scan/industry 使用；多进程共享不作验收条件（键设计天然无冲突）。

## 5. 接口冻结（计划期唯一执行依据）

| # | 接口 | 签名/语义 |
|---|---|---|
| I1 | `bars_etl.resolve_universe()` | `-> list[str]` 去重升序（clist 段 ∪ workspace 码，含工作区北交所，无指数）；纯查询 |
| I2 | `bars_etl.authoritative_watermark(now=None)` | `-> "YYYY-MM-DD"`；Asia/Shanghai 时刻粒度（weekday 且 ≥15:05 方计当日）；60s 缓存；now 可注入 |
| I3 | `bars_etl.detect_gaps()` | `-> {"missing":[],"stale_deep":[],"stale_light":[],"up_to_date":int}` |
| I4 | `bars_etl.run_full(force=False, *, fetch=None)` | `-> EtlStats{universe,up_to_date,backfill,daily,no_new_bar,fetched,failed[list],watermark,aborted,elapsed_ms}`；`bars==[]` 判失败（§3.4） |
| I5 | `bars_etl.bars_health()` | `-> dict|None`；内部 60s 结果缓存（热路径不逐次 GROUP BY）；异常回 None |
| I6 | `redis_cache.build_facade(settings)` | `-> CacheFacade`；redis 未配置→永久旁路（等价现状） |
| I7 | `CacheFacade.get/set/take_stale` | §4.1；白名单前缀、双 TTL 语义分家、128KB 跳写、熔断计数；测试注入 in-memory fake |
| I8 | `data_source.cached(key, loader)` | 外部行为逐字不变；**断言：仅 quotes:/history: 前缀产生 L2 调用，screener_v2: 零触**；既有 cached 测试零修改全绿 |
| I9 | health `bars`/`redis` 位 | 附加键，零现有字段改名 |
| I10 ⟲ | `storage.upsert_market_bars_batch(code, bars, adjustment)` | 单事务 `INSERT..ON CONFLICT (code,trade_date,adjustment) DO UPDATE`；空 bars 拒绝调用（防御 I4 之外的路径）；返回写入行数 |

## 6. 数据模型与迁移

**零迁移。** `market_bars` 结构不变；容量 5223×500≈260 万行 bfq（<600MB）。唯一约束覆盖 ETL upsert 与检测查询形态。

## 7. 错误与诚实披露矩阵

| 故障 | 行为 | 暴露 |
|---|---|---|
| 单码空响应/异常（重试后） | 计 failed，下轮自愈 | EtlStats.failed + warning |
| 失败率>20% | 本轮熔断 | `bars_etl_aborted` error |
| universe <2000 | 本轮 aborted（防小分母假绿） | warning + health 水位不动 |
| 休市/假日 | 拉回全 ≤ 库内 max → `no_new_bar` 正常档；不判失败 | stats |
| 盘中/未来日 bar | `trade_date > watermark` 逐根拒收 | stats |
| ETL 停摆 >7 天 | 消费端自动回退逐码回源（正确性不变） | health.bars 水位落后 + 冒烟 |
| Redis 挂/慢 | L2 旁路=现状；L1 双写不中断 | health.redis 三态 + 熔断日志 |
| loader 上游失败 | stale 链 L1→L2→抛，现状语义 | mark_stale |

## 8. 测试策略

- **M1 离线**：fake `fetch`/`upsert` 注入——三档路由、`bars==[]` 判失败并计熔断（⟲ 故障注入必测）、`no_new_bar` 正常档、未来 bar 拒收、force 重拉、universe 护栏（<2000 aborted）、批量 upsert 幂等（重放行数不变）；`detect_gaps` 真 PG 预置四档集合相等断言；水位时刻粒度参数化用例（weekday 15:04/15:06、周末、now 注入）。
- **A1 附带修复**：指数与个股同码 000001 互写隔离用例。
- **M1 真实冒烟**（一次性脚本，smoke v2 模式）：`run_full` 实跑 → health.bars fresh 比 ≥95% → 抽 3 码端点回放 vs 直拉对拍 → 复盘/组合冷进程 **upstream 码集合 ⊆ 非 universe 集合**（差集打印，⟲ 判据重钉，北交所工作区码不算豁免面）。
- **M2 离线**：in-memory fake redis（可编程抛错）——L2 命中回填、get 新鲜读 ts 复核弃旧、**take_stale 按 1800s 与 L1 等价（⟲ 专项用例）**、白名单前缀断言（screener_v2 零触 L2）、熔断三态、旁路下 loader 正常、128KB 跳写、quotes 键 sorted 归一命中同键；`cached()` 既有测试**零修改全绿**（I8 机器证明）。
- 门禁七件套沿用；新增预计 +40~50 项。

## 9. 已知限制 / 非目标 / 边界声明

**定位声明**：本 spec 面向**单用户本地工具**（AGENTS 红线）。评审方"生产级量化网站"清单（分布式调度/leader 选举/多实例一致性/Sentinel/TLS/RBAC/租户隔离/Prometheus/告警值班/备份演练/混沌工程）**整体为非目标**：多租户/认证/审计/外部监控栈与券商对接同级，永久拒绝（组合风险 spec D9 先例）；单进程本地环境无对应故障面。**接受其中两项最低成本增强并入设计**：health 三态可观测（§3.6/§4.3 已含）、ETL 失败日志即告警面（无推送通道，本地工具人工看日志）。

限制清单：
- L1 全市场北交所不入 universe（clist 无段且拒扩东财依赖；工作区北交所码例外已纳入逐码拉取）；
- L2 qfq 按需缓存遇新除权漂移（现状维持，D3 理由）；
- **L3 假日盲区** ⟲：日历无节假日表，法定假日将触发一轮空转日补（数据不为错，浪费 ≈5223 请求 × 一年约 7 个非周末假日）；引入日历表/交易日历 API 拒绝（收益/复杂度不匹配，水位判据已保证正确性）；
- L4 500 根之外超长历史仍回源；ETL 停摆 >7 天性能退化无外部告警；
- L5 `quotes:` 组合键的历史 L2 冗余条目靠 TTL 自清（sorted 归一后新增稀释消除）；
- L6 不做分钟线/分区/PIT/多 worker/手动 ETL API（`/api/bars/etl/run` 拒绝——本地工具无需 HTTP 触发面，health 给观测）。

## 10. 成功判据（验收）

1. 连续两交易日 15:20 后：health.bars `watermark==应收盘交易日`、`freshCount/universeSize ≥ 0.95`；
2. 冒烟：复盘/组合冷进程（清 L1）**upstream 码集合 ⊆ 非 universe 码集合**且差集打印为空（universe 内零回源=ETL 传导成立的机器证明）⟲；
3. 重启后端：health.redis=connected，行情轮询上游请求数下降（L2 命中直接证据）；
4. 拔 Redis：轮询无感（L1+上游=现状行为），health.redis→bypassed，恢复自动回 connected；
5. 全量门禁 + `cached()` 既有测试零修改全绿 + A1 隔离用例绿。
