# 全市场日线 ETL + Redis 行情缓存接管（P2 数据中台）— 设计规格 r3

日期：2026-09-13 ｜ 状态：**用户评审=有条件通过（r2 轮）；r3 清偿全部条件项，视为评审通过进入计划** ｜ 上游：ROADMAP「P2 Redis 行情缓存接管」「P2 全市场日线落库」
评审史：r1 对抗评审 3P0/6P1/2P2 → r2 全吸收；r2 用户评审按单用户本地标准**有条件通过**（3×P1 + 5×P2 待修）→ r3 清偿，修订处 ⟳ 标记；r3 自查新增 I9 兼容修正 ⟳（r2 的 health.redis 三态会破坏既有布尔契约，改附加键）。"生产级量化网站"轴两轮评审均提出，均依 AGENTS 定位整体拒绝（§9）；**本 spec 验收判据仅以单用户本地工具标准为准**。
定位：数据基础设施两里程碑，M1（日线 ETL）与 M2（Redis 接管）相互独立、可独立交付回滚；共享"降级不静默"纪律。
红线不变：绝不造数；ETL/缓存缺口一律如实暴露为回源、degraded、stale 或 rejected。

## 0. 术语

| 术语 | 定义 |
|---|---|
| bfq（不复权） | `market_bars.adjustment=''` 口径，真实成交价，永不因新除权漂移；复盘/组合设计口径同源 |
| universe | ETL 维护的代码集合（§3.2），全市场=clist 四段（无北交所全表），另含工作区码（北交所工作区码入内，腾讯 bj 前缀现成） |
| 权威水位 watermark | 最近一个"应已收盘交易日"（Asia/Shanghai 时刻粒度，§3.3）；ETL 健康度与冒烟断言的锚 |
| 日补 / 回补 | 日补=只补缺失的最近交易日 bar；回补=首装/深度缺口一次拉满 500 根 |
| CacheFacade | M2 三级缓存门面：L1 进程 dict（现状）→ L2 Redis → loader 上游 |
| DQ 拒收 | 写入前逐根合法性断言，坏根不落库、计数暴露（⟳ P1-3） |

## 1. 决策

- **D1 组织**：一份 spec 两里程碑；计划期 M1→M2 依序执行。
- **D2 深度**：每码 bfq 500 根。
- **D3 口径**：ETL 仅 bfq；qfq 维持按需缓存现状（漂移性质披露 §9-L2）。
- **D4 增量**：日补只补缺失日；bfq 历史永不重写。重拉近 30 根替代案拒绝。
- **D5 消费端零改动**（§3.5）：`fetch_all_bars`/`_counting`/degraded 语义不动；唯一例外=附带缺陷修复 A1（§3.7）。
- **D6 Redis 范围**：仅 `quotes:*`/`history:*` 进 L2；`screener_v2:*` 显式排除（I8 断言）；选股管道/行业/扫描态不进。
- **D7 降级方向**：Redis 挂→纯 L1+上游（=今天的行为），熔断防打穿；绝不因 Redis 故障返回假数据。
- **D8 存储**：零新表零迁移；批量 upsert 走新存储接口 I10。
- **D9 拒绝项**：数据仓库层/分区/PIT、akshare 入仓、分钟线、多 worker/分布式调度（§9）、指数入 ETL（键污染，A1 另治）、⟳ 静态法定假日表（年约 7 次空转的成本 < 表维护+公告依赖复杂度，本地工具不划算——拒绝理由成文）。

## 2. 现状事实（读码/实测确认）

- `data_source.py:79` 进程 dict + `cache_lock`；`cached()`（:131）TTL 下限 2s；loader 抛错时 `STALE_MAX_AGE=1800s` 内回陈旧值并 `mark_stale`。**L1 无 TTL 物理删除——陈旧值常驻，这是现状降级能力的来源**（⟳ M2 的 L2 必须同语义，§4.2）。
- 现存缓存 key 族：`quotes:{symbols}`（:312，组合键顺序敏感 ⟳归一）、`history:{symbol}:{limit}:{fq}`（:333）、`screener_v2:{...}`（:485）。
- `fetch_all_bars`（`plan_review.py:202-225`）逐码 DB 优先、7 日新鲜不回源、单码容错、`ReviewUpstreamError(codes, partial)`。
- 上游失败形态：腾讯限频/坏 payload 时 `load_history` 返回 `[]` 不抛；`save_market_bars([])` 零写零异常——空判失败封堵（§3.4）。
- 日历边界：`CNMarketCalendar.is_trading_day` 实为 weekday<5、无假日表——水位算法自持 15:05 时刻规则（§3.3），假日盲区 §9-L3。
- `redis==5.2.0` 在依赖；`settings.py` 已配（192.168.0.114:6379）；`REDIS_PASSWORD` 配置面已存在；现仅 `storage_status()` ping → `/api/health.redis` **布尔**（⟳ I9 兼容：新状态走附加键，布尔位不动）。
- `app.py:238` lifespan 注册样板（行业预热 30s+24h）；`tencent_symbol` 支持 bj（:170）。
- industry_map 5223 行（前缀 0/3/6）；其首刷依赖东财 clist（RST 单点实证）——§3.2 护栏兜底竞态。
- A1 既有隐患：`app.py:417` 指数以 `adjustment="qfq"` 落库，000001 与平安银行同桶混写（§3.7）。

## 3. M1：全市场日线 ETL（`backend/bars_etl.py`）

### 3.1 组件与依赖
纯新模块，依赖 `storage`、`data_source`（`route_with_fallback` 同源注入面）、scheduler 注册处；被调方零感知。

### 3.2 universe 解析
`resolve_universe() -> list[str]`：industry_map 全表 ∪ workspace distinct(watchlist, plans)（含 4/8 北交所工作区码）。去重升序；不含指数。护栏：<2000 码 → `aborted=True` + `bars_etl_aborted universe_too_small` warning（防 industry 预热未成小分母假绿；软依赖靠护栏+下轮自愈，不加显式等待）。

### 3.3 水位与缺口检测
`authoritative_watermark(now=None) -> str`：Asia/Shanghai 时刻粒度——今日 weekday 且 `now ≥ 15:05` 方计当日，否则回溯最近 weekday；60s 进程缓存；now 注入为测试面。
`detect_gaps()`：单次 `SELECT code, max(trade_date) WHERE adjustment='' GROUP BY code`，四档：`missing` / `stale_deep`（>10 交易日→回补 500）/ `stale_light`（≤10→日补 `limit=max(20,落后+5)`）/ `up_to_date`（零请求）。

### 3.4 执行流（`run_full(force=False, *, fetch=None) -> EtlStats`）
- 三阶段：回补档 → 日补档 → 汇总日志；全局 `_throttle()`（≤10 req/s）顺序拉取（≈9-15 分钟），⟳ 写入 I10 批量（每 500 码一事务、**码级 SAVEPOINT**：单码异常仅回滚该码入 failed，同批他码照常提交）。
- 失败判定：`bars==[]` 即失败（重试 1 仍空→failed+计熔断率）；非空但无新根→`no_new_bar` 正常档；失败率>20%→本轮熔断。
- ⟳ **DQ 逐根断言（写前）**：`open/high/low/close` 非空且 ≥0、`low ≤ min(open,close) ≤ max(open,close) ≤ high`、`volume ≥ 0`（0=停牌合法）、`trade_date` 合法日期且 ≤ watermark、批内同 date 去重保后者。坏根**拒收不落库**，计 `rejected`（码级：一码全根被拒→该码入 failed）。消费端因此永不触达畸形行——DQ 失败是数据面诚实，不是静默。
- `force=True`（脚本/测试）：跳过 up_to_date 全量日补。
- ⟳ **调度防重叠**：三处注册（启动 60s 自愈、交易日 15:20、周六 10:30 审计）**共用 job id `bars-etl` + `max_instances=1, coalesce=True, misfire_grace_time=300`**——上一轮未完时新触发合并跳轮，绝不同时两跑；注册函数导出供测试以假 scheduler 断言 kwargs。首装=自然特例（全库 missing→回补）。注册失败仅日志，不影响 API 启动。

### 3.5 消费端对齐
`fetch_all_bars` 的 7 日新鲜判据在 ETL 日补后恒真 → loader 不调、upstream=0、degraded 空。未覆盖码（全市场北交所/新股空窗）走现状逐码回源。停摆>7 天=性能退化非正确性退化（health 暴露）。

### 3.6 可观测
`bars_etl_ok universe=%d up_to_date=%d backfill=%d daily=%d no_new_bar=%d rejected=%d fetched=%d failed=%d watermark=%s aborted=%d elapsed_ms=%d`（`atlas.bars_etl`）；`/api/health` 附加 `bars = {watermark, freshCount, universeSize, lastRunAt}|null`，**结果进程缓存 60s**（热路径不逐次 GROUP BY；缓存不可用时回 null 不阻塞不造假）。

### 3.7 附带缺陷修复 A1 ⟳（独立提交，先于 ETL）
① 指数链路（`app.py:417` 面）以 `adjustment="qfq:idx"` 键空间存取，与个股隔离；② **一次性清理**：脚本 `DELETE FROM market_bars WHERE adjustment='qfq' AND code IN ('000001','399001','399006')`（歧义桶整删——qfq 缓存本就按需重取，代价≈首访一次回源；现库仅 11 码/1601 行，删量个位数行级）；脚本幂等、计划任务内执行并留输出。测试：指数与个股同码互不读写 + 清理后 000001:qfq 桶仅剩个股行（重取后）。

## 4. M2：Redis 行情缓存接管（`backend/redis_cache.py` + `data_source.cached`）

### 4.1 CacheFacade 接口
```python
class CacheFacade:
    def __init__(self, redis_factory, ttl_getter, log=logger): ...
    def get(self, key) -> Any | None          # L1→L2(回填 L1)→None；仅白名单前缀查 L2
    def set(self, key, value, ttl)            # L1 恒写；L2 白名单内双写，任何异常吞+计入熔断
    def take_stale(self, key, max_age) -> Any | None   # L1→L2 降级读
```
`cached()` 只换存储层，外部行为逐字不变（I8）。**新鲜/陈旧完全由封装 `{"ts","v"}` 的 ts 判定**：`get()` 超 `_cache_ttl+5s` 弃用；`take_stale()` 按 `STALE_MAX_AGE=1800s` 判定——与 L1 语义等价。

### 4.2 键、TTL 与序列化 ⟳（P1-1 矛盾清偿）
- **L2 物理 TTL = `STALE_MAX_AGE + 60s`（常量 1860s），与 `_cache_ttl` 解耦**——Redis 键必须活得比"新鲜窗"久，`take_stale` 才有东西可读；新鲜度全交给 ts 判定（与 L1"dict 不物理删除、判读逻辑定生死"同构）。
- 白名单前缀 `quotes:`/`history:` 映射 L2 键 `atlas:q:<原key>`；其余前缀永不触 L2。`quotes:` 键构造 `sorted()` 归一（值按 symbol 字典组装，返回顺序仍按入参，语义不变）。
- **序列化纪律**：`json.dumps` 严格模式（**无 default 钩子**）——非 JSON 原生类型抛 `TypeError` → 视为跳写：L1 正常、L2 跳过、`redis_cache_skip_unserializable` debug 计数；**绝不 `default=str` 型别转换**（数值变字符串=假数据）。读回解码失败同规则弃键。

### 4.3 故障与熔断
连接超时 1s/读超时 0.5s；连续 3 次失败→旁路熔断 30s（纯 L1=现状），恢复自动闭合；`redis_cache_degraded`/`redis_cache_recovered` 各一条日志。loader 异常链不变（stale 兜底 L1→L2→抛）。⟳ **health 兼容**：`/api/health` 既有 `redis: bool`（storage ping）**不动**；新增 `redisCache: "connected"|"bypassed"|"down"` 附加键（前端健康条零改，I9）。

### 4.4 范围守卫
接管面=`cached()` 全部调用点但仅白名单前缀入 L2；不新增 key 族；多进程共享不作验收条件（键天然无冲突）。

## 5. 接口冻结

| # | 接口 | 签名/语义 |
|---|---|---|
| I1 | `bars_etl.resolve_universe()` | `-> list[str]` 去重升序（clist ∪ workspace，含工作区北交所，无指数）；纯查询 |
| I2 | `bars_etl.authoritative_watermark(now=None)` | `-> "YYYY-MM-DD"`；Asia/Shanghai 时刻粒度（weekday 且 ≥15:05 计当日）；60s 缓存；now 注入 |
| I3 | `bars_etl.detect_gaps()` | `-> {"missing":[],"stale_deep":[],"stale_light":[],"up_to_date":int}` |
| I4 | `bars_etl.run_full(force=False, *, fetch=None)` | `-> EtlStats{universe,up_to_date,backfill,daily,no_new_bar,rejected,fetched,failed[list],watermark,aborted,elapsed_ms}`；空 bars=失败；DQ 坏根=rejected |
| I5 | `bars_etl.bars_health()` | `-> dict|None`；60s 结果缓存；异常回 None |
| I6 | `redis_cache.build_facade(settings)` | `-> CacheFacade`；redis 未配置→永久旁路（=现状） |
| I7 | `CacheFacade.get/set/take_stale` | §4.1/4.2：白名单、物理 TTL 1860s+ts 定新鲜、严格序列化跳写、128KB 跳写、熔断计数；测试注入 in-memory fake |
| I8 | `data_source.cached(key, loader)` | 外部行为逐字不变；断言仅 quotes:/history: 触 L2，screener_v2 零触；既有 cached 测试零修改全绿 |
| I9 | health 附加键 | `bars` 对象 + `redisCache` 字符串；**现有 `database`/`redis` 布尔零触碰** |
| I10 ⟳ | `storage.upsert_market_bars_batch(code, bars, adjustment)` | 单事务 INSERT..ON CONFLICT DO UPDATE + **码级 SAVEPOINT**（供上层 500 码组事务内隔离单码失败）；空 bars 拒调（抛 ValueError）；`-> int` 写入行数 |
| I11 ⟳ | `bars_etl.register_jobs(scheduler)` | 显式导出注册函数：三触发共用 id=`bars-etl`，kwargs 含 `max_instances=1, coalesce=True, misfire_grace_time=300`；测试以假 scheduler 捕获断言 |

## 6. 数据模型与迁移

零迁移。`market_bars` 不变；容量 5223×500≈260 万行 bfq（<600MB）。唯一约束覆盖 upsert 与检测形态。A1 清理为一次性 DELETE 脚本非迁移。

## 7. 错误与诚实披露矩阵

| 故障 | 行为 | 暴露 |
|---|---|---|
| 单码空响应/异常（重试后） | failed，下轮自愈 | stats + warning |
| 失败率>20% | 本轮熔断 | `bars_etl_aborted` |
| universe <2000 | aborted（防小分母假绿） | warning |
| 坏 bar（DQ 不过） | **根级拒收不落库**；全码被拒→failed | stats.rejected ⟳ |
| 休市/假日 | `no_new_bar` 正常档 | stats |
| 盘中/未来根 | 拒收（>watermark） | stats.rejected |
| ETL 停摆>7 天 | 消费端自动回退逐码回源 | health.bars 水位 |
| 两轮 ETL 触发重叠 | max_instances=1+coalesce 合并跳轮 ⟳ | APScheduler 语义+注册测试 |
| Redis 挂/慢 | L2 旁路=现状 | health.redisCache + 熔断日志 |
| 值不可序列化 | L2 跳写（L1 正常），不转换类型 ⟳ | debug 计数 |
| loader 上游失败 | stale 链 L1→L2→抛（1800s 窗物理可达 ⟳） | mark_stale |

## 8. 测试策略

- **M1 离线**：fake fetch/upsert 注入——三档路由、空 bars 判失败计熔断、**DQ 坏根矩阵（负价/OHLC 颠倒/volume<0/重复 date/未来 date）**、no_new_bar 档、force、universe 护栏、批量幂等、**SAVEPOINT 隔离（第 3 码坏数据不影响 1/2/4/5 提交）**；detect_gaps 真 PG 四档集合断言；水位参数化（15:04/15:06/周末/now 注入）；**I11 注册 kwargs 断言（假 scheduler 捕获）**。
- **A1**：指数/个股同码隔离 + 清理脚本幂等。
- **M1 冒烟**（一次性脚本）：`run_full` 实跑→health.bars fresh 比≥95%→抽 3 码端点回放对拍→冷进程 **upstream ⊆ 非 universe** 且差集打印。
- **M2 离线**：fake redis（可编程抛错+物理过期时钟）——L2 回填、ts 新鲜复核弃旧、**take_stale 在物理 TTL 内必可达（P1-1 回归锚）**、白名单断言、熔断三态、旁路 loader 正常、128KB 跳写、**不可序列化跳写且 L1 完好（类型不转换）**、quotes 键 sorted 同键命中；`cached()` 既有测试零修改全绿。
- 门禁七件套沿用；新增预计 +50~60 项。

## 9. 已知限制 / 非目标 / 边界声明

**定位声明**：单用户本地工具（AGENTS 红线）。生产级清单（分布式调度/多实例一致性/Sentinel/TLS/RBAC/租户/Prometheus/告警值班/备份演练/混沌）**整体非目标**——多租户/认证/审计与券商对接同级永久拒绝（组合风险 spec D9 先例）；单进程本地无对应故障面。接受的低成本替代已并入设计：health 可观测三态、日志即告警面。⟳ **安全披露**：Redis 位于局域网（192.168.0.114），无 TLS——`REDIS_PASSWORD` 配置面已存在（settings.py），部署侧建议 requirepass+bind/防火墙，属运维选择非本 spec 代码项。

限制：L1 全市场北交所不入 universe（工作区码已纳）；L2 qfq 漂移现状维持；L3 假日空转（≈7 次/年×15 分钟，数据不为错；静态假日表拒绝理由=D9）；L4 500 根外超长历史回源、停摆>7 天无外部告警；L5 历史 `quotes:` 组合键 L2 冗余靠 TTL 自清；L6 不做分钟线/分区/PIT/多 worker/手动 ETL API。

## 10. 成功判据（验收，单用户本地标准）

1. 连续两交易日 15:20 后：health.bars `watermark==应收盘交易日`、`freshCount/universeSize ≥ 0.95`；
2. 冒烟：复盘/组合冷进程 upstream 码集合 ⊆ 非 universe 且差集打印为空；
3. 重启后端：health.redisCache=connected，轮询期上游请求下降（L2 命中证据）；
4. 拔 Redis：轮询无感（=现状行为），redisCache→bypassed，恢复自动闭合；**停 L2 期间上游持续失败时，L1→L2 陈旧兜底链在 1800s 窗内仍可命中**（P1-1 行为级验证）；
5. 全量门禁 + `cached()` 既有测试零修改全绿 + A1 隔离/清理绿 + ETL 双触发不并跑（I11 断言）。
