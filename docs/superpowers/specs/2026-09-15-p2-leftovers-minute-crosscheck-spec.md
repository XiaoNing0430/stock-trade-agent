# P2 遗留包：受保护按需分钟线 + 跨源交叉校验 + universe 护栏拆分（P2.5）— 设计规格 r2

日期：2026-09-15 ｜ 状态：**r2（r1 对抗评审 4P1/1P2 已清偿，⟹ 标记本轮修订）待用户放行** ｜ 上游：P2 spec r3.2 遗留项 + 用户 2026-09-15 方法论裁定（逐字采纳其护栏表）
定位：三块相互独立、可独立交付回滚的 P2 收尾；共享"降级不静默、不造数、不自动改数"纪律。

## 1. 决策记录（用户裁定 + 环境实测）

- **D1 全市场分钟线：挂起。** 原因：腾讯 ifzq ~1500 持续请求即 501 全 IP 惩罚（P2 冒烟实锤），当前数据源+单用户本地定位下不可行。重开条件（写 ROADMAP）：接入带分钟权限的稳定源（Tushare Pro 分钟、券商 Level-1/2、本地行情网关），且具备独立限流、独立 IP/账号、不干扰日线源。验收前置：分钟线请求不得与日线 ETL 共用同一受限链路；必须有独立限流、熔断、缓存、健康暴露。
- **D2 自选/详情按需分钟线：可做，降级为"受保护的交互式行情功能"。** 仅自选/详情、单码、用户触发；不落库、不过 ETL、不后台批量预取、不自动轮询全自选；周期白名单 {m1,m5,m15,m30,m60}，count 上限 320。护栏表逐条采纳：独立令牌桶 1rps/burst3（与日线 `_throttle` 隔离、优先级低于日线）、ETL 运行期互斥、短 TTL（L1 15s；L2 120s 新增 `minute:` 白名单，不改 quotes/history 语义）、上游连败 3 次熔断 900s（501 单次即熔断；熔断期展示 stale/不可用，不重试不造数）、失败最多 1 次重试（501/4xx 零重试）、health 暴露、日志与 fake 源测试。
- **D3 跨源校验：主辅都建，token 缺则降级。** Tushare daily 为主（`TUSHARE_TOKEN` 已配置才启用；当前实测为空）；东财 clist 为辅/降级（只校验最新收盘，接受其实时快照口径与 RST 稳定性局限）。校验失败只告警（日志+health），不阻断 ETL、不自动改数、不自动重拉、不造数。
- **D4 universe 护栏拆分（drain 实测暴露的新缺陷，2026-09-15）**：industry_map 被清空→universe 塌缩至 1→`UNIVERSE_MIN` 护栏把**用户码日补也连带冻结**。护栏本意是防全市场小分母误读，不应伤及关键路径。拆分规则见 §3。
- **D5 mkline 环境事实**：`/appstock/app/kline/mkline` 301→`web3.ifzq.gtimg.cn`，本机 DNS 无法解析（2026-09-15 实测，两次重试同果；`minute/query` 分时走 web 正常 200）。属环境约束非产品缺陷；分钟路径必须把"mkline 不可达/501/超时"全部作为正常降级路径处理，live 冒烟受限时以离线 fake 测试为准，用户网络自验。
- **D6 惩罚窗消退观测**：日线 kline 端点 2026-09-15 实测恢复 200（发作后约 24h）；L8 的预算/节奏/公平序设计维持，回补按 drain+日 cron 继续推进。

## 2. 目标 / 非目标

**目标**：G1 受保护分钟线交互功能（后端端点+前端最小触点）；G2 跨源交叉校验（调度+health+日志面）；G3 universe 护栏拆分（用户码/存量码日补无条件）；G4 ROADMAP 遗留项成文（挂起条件/方法论/待办）；G5 全市场回补推进收尾（运维，drain 已在跑，交付以 deferred 归零或如实结转）。

**非目标**：全市场分钟线、分钟线落库/分区/回放联动、横截面分钟策略、Tushare 分钟权限使用、校验自动修复、任何新表/迁移、UI 重构（仅在既有详情视图加控件）、认证/RBAC/生产化（AGENTS 红线，永久拒绝轴）。

## 3. G3：护栏拆分（先行，最小改动）

- `resolve_universe()` 扩为**两面**：`market_codes`（industry_map 表）与 `user_codes`（watchlist ∪ trade_plans）；`scan_universe = market ∪ user ∪ DISTINCT(market_bars.code WHERE adjustment='bfq')`（库内已有码=存量资产，永远在扫描面内，否则护栏触发时已有数据静默腐烂）。
- 护栏语义修正：`len(market_codes) < UNIVERSE_MIN` 只冻结**新增码深回补**（missing∪stale_deep 中不在 market_bars 的码）；**存量码深回补（在库但落后 >10 工作日）与轻队/日补无条件执行**。⟹ **预算对回补队列两档（存量档+新码档）统一适用 `BACKFILL_CODES_PER_RUN`**——护栏拆分绝不放开 501 惩罚窗的后门：存量档优先占预算（在库资产保鲜），新码档位余。`reason="market_universe_small"` 记入 `bars.abortReason`，`deferred` 如实计数（health 观测不回退）。
- 启动探测维持现状（universe<UNIVERSE_MIN 重排 ≤20×120s）——其目的从"整轮自救"改为"尽早放开全市场深回补"。
- 测试：industry 表空 + 库内码 stale → backfill 仅存量码、新码全 deferred、daily 正常；industry 满 → 与现状行为一致（既有 41 项 ETL 测试零修改全绿，除非语义被本 § 显式改）。

## 4. G1：分钟线后端

**新模块 `backend/minute_path.py`**（组合 data_source 原语 + CacheFacade，防 data_source 继续膨胀）：

- `load_minute_kline(code, period, count)`：period ∈ {m1,m5,m15,m30,m60} 白名单（越界 422 在端点层拦），count clamp [10,320]；上游 `GET https://web.ifzq.gtimg.cn/appstock/app/kline/mkline?param={symbol},{period},,,{count}`；解析行 `[yyyymmddHHMM,o,c,h,l,vol,...]` → `{"date":"YYYY-MM-DD HH:MM","open","close","high","low","volume"}`（与日线 bar 形兼容，前端 chart 通道复用）。ETF/指数支持=同 symbol 规则；北交所 bj 前缀实测若 mkline 无数据按空降级（不造数）。
- **请求路径（顺序即纪律）**：参数校验 → **ETL 互斥**：`bars_etl._RUN_LOCK.locked()` 时不发上游，仅读 L1/L2，皆 miss → 返回 `{bars:[], state:"etl_busy", degraded:true}`（HTTP 200，如实非错误）→ 令牌桶（1rps、burst≤3，非阻塞；空桶 → HTTP 429 + `retryAfterMs`，交互路径不排队）→ 熔断窗内（open → 只读缓存，miss 返回 `{bars:[], state:"circuit_open"}`，不打上游）→ L1（15s）→ L2（`minute:` 前缀，新鲜窗 120s，**无降级读**）→ 上游（重试策略：网络类错误最多 1 次；501/4xx 零重试）。
- **上游熔断**：连续 3 次失败（连接异常/5xx/超时）→ 900s 全局开路；收到 501 → 立即开路 900s（惩罚窗语义）。半开恢复=窗后首请成功即闭路（记 `minute_circuit_open/close` 日志）。Redis facade 熔断（3 败/30s）与本路熔断**互不相干**（两个故障域）。
- **CacheFacade 策略表化（唯一触碰点，I6）**：`WHITELIST_PREFIXES += ("minute:",)`；新鲜窗与 PX 从全局常量改为按前缀策略：`quotes:/history:` 维持现语义（ttl_getter+5 窗、PX≥1860+60 floor）；`minute:` 新鲜窗 120s、PX=(120+60)s、`stale_read/take_stale` 对 minute 键返回 None（陈旧分钟线无意义）。既有键行为逐字不变（I8 纪律延伸）。
- 端点 `GET /api/minute?code=&period=5&count=&index=false` ⟹（`index` 必选面：000001 个股/指数同号歧义与 /api/history 同源，symbol 走 `index_symbol`；分钟线不落库故无桶问题）；period 单位分钟 ∈ {1,5,15,30,60}→m*；count 默认 120 → `MinuteOut {code,period,bars:[MinuteBar],dataSource:"upstream"|"cache_l1"|"cache_l2"|null,state:"ok"|"etl_busy"|"circuit_open"|"unavailable",degraded:bool,updatedAtMs}`⟹（无数据回 null——绝不以 "upstream" 冒充空响应来源）。错误契约沿用现有 API 码（VALIDATION_ERROR 422 / RATE_LIMITED 429）。既有端点零触碰。
- health 附加键（纯增量）：`minuteCache: "connected"|"bypassed"|"down"`（=facade 对 minute 可用态）、`minuteCircuit: "closed"|"open"`。

## 5. G2：跨源交叉校验

**新模块 `backend/cross_check.py`**：

- **Provider 协议**：`fetch_close_map(date) -> dict[code, (close|None, vol|None)]`。
  - `TushareProvider`：单次 `pro.daily(trade_date=YYYYMMDD)` 拉全市场（1 请求/日，配额友好）；映射 `600000.SH→600000`；**单位换算表以 T0 实测校准为准**（Tushare vol=手、amount=千元；腾讯 kline volume 单位实施前用 2 锚码同日双源实测锁定，误差>1% 视为换算错而非数据差异——写进实现注释）。启用条件：`tushare_token` 非空且 `find_spec("tushare")`。
  - `EastmoneyProvider`：push2 ulist.np `secids` 批查（≤100 码/请求）；⟹ **T0 实测锁定（2026-09-15，600000/000001）**：`fltt=2` 时 f2=浮点元价（**无 100 倍缩放**——原假设作废）、f5=手、f6=元；库内 bfq volume 同为手（DB 832461 vs EM 755251 同码同日同单位差异为陈旧水位样本非单位错位，600000 收盘价 9.18 与 EM f2 **分文不差**）；盘后调用=最新收盘快照，**仅校验水位日一根**，不接受历史回溯。Tushare 换算（vol=手→×100=股、amount=千元→×1000=元）**以代码内注释+单测断言为准，token 就绪日执行 live T0 对拍后允许改常数组**（R2 关卡）。
- **抽样**：`CROSS_CHECK_SAMPLE=30` = 锚定码（watchlist∪trade_plans 去重取前 10，必查）+ 日期盐种子随机补足（同日可复现）。全市场日一次批量接口即可覆盖。
- **判据**：对每码——本库水位日 bfq 行 vs provider 行：close 相对差 >0.1% 且绝对差 >0.011 元 → mismatched；vol 差 >1%（双方均非零才比）→ mismatched；库缺行 → missing（回补缺口非校验错）；provider 缺行/停牌（Tushare 无行、东财 f2='-'）→ skipped_suspended（**不计 mismatched**，对齐停牌语义，单独计数）。
- **调度**：`register_jobs` 第四 id `bars-crosscheck`（cron mon-fri **15:35**，日补 15:20 之后；max_instances=1、misfire 300、replace_existing）；**取数前须等日线 ETL 完成或跳过本轮**——`_RUN_LOCK.locked()` 时不并发读（避免校验读到"日线半写"态误报 missing），本轮 `status="deferred_etl_running"` 且不更新 lastRunAt，最多顺延 3×5min（≈15:50 放弃，日志 cross_check_deferred，非 degraded 非风暴）；独立 `_CC_LOCK` 与 `_RUN_LOCK` 不交叉（校验永不阻断/排队 ETL）；provider 异常/双源皆不可用 → `cross_check_degraded` 日志 + health status=degraded，**无告警风暴**（同因 10 分钟内只记一条）。
- **落点**：不建新表（单用户日志即告警面）；`health.bars.crossCheck = {provider,lastRunAt,sampled,mismatched,missing,skippedSuspended,status:"ok"|"degraded"|"disabled"|"deferred_etl_running"} | null`（未启用=disabled 显式，不 null 混淆"没跑"与"没配"）。

## 6. 前端最小触点（不重构）

`ViewStockDetail` 既有图表区加"分钟"周期按钮组（1/5/15/30/60，默认 5）+ 单次拉取（无轮询、仅手动切换/点击触发）；渲染复用 chartSvg 通道（escapeHtml 纪律不变）。状态呈现：`ok`→正常画线；cache_l1/l2 命中或 degraded→黄标"分钟线（缓存，N 分钟前）"；`etl_busy`→灰条"日线同步中，分钟线稍后可用"；`circuit_open/unavailable`→灰条"分钟线暂不可用"；429→toast"请求过于频繁"。字段名全部走新增 schema，零改既有 API 面。

## 7. 日志

`atlas.minute_path`：minute_ok(debug)/minute_fail(warning: code,status)/minute_circuit_open|close(warning/info)/minute_etl_defer(info)/minute_rate_limited(debug)。`atlas.cross_check`：cross_check_ok(info: provider,sampled,mismatched,missing)/cross_check_mismatch(warning: 前 10 码+偏差摘要)/cross_check_degraded(warning: reason, provider)。`bars_etl` 现有行增 `abortReason`。

## 8. 测试纪律（全离线）

fake mkline（含 501/DNS 异常/正常矩阵）、fake 令牌桶与假时钟测 900s 半开、fake ETL lock 断言分钟线零上游、fake Tushare/东财注入断言单位换算/阈值/停牌 skipped/缺行 missing 分账、token 空→eastmoney 路由、双 provider 皆挂→degraded 无风暴、护栏拆分两用例（§3）、health 新键形状；`conftest` facade 隔离纪律沿用。**既有 563 项基线零修改全绿**（facade 策略表改造若触碰既有断言，按 P2 先例修正测试须在 commit message 单列理由）。

## 9. 已知限制 / 风险

R1 mkline web3 DNS 本机不可解析→live 冒烟受限（离线测试为验收基线；用户真实网络首验）；R2 单位/缩放误换算→⟹ 东财面 T0 已实测锁定（§5），Tushare 面 token 就绪日补 live 对拍；校准完成前 cross_check 允许合入但调度注册带 `CROSS_CHECK_ENABLED` 环境开关（默认关→health=disabled），东财 live 冒烟通过后才在 .env 打开；R3 分钟线与日线同主机——令牌桶 1rps 硬顶 + 501 即熔断防放大，接受残余共担风险；R4 东财 RST 前科→degraded 视为常态路径设计；R5 停牌对齐按 skipped 分账，接受"provider 缺行=停牌"假设的长尾误判（日志可查）；R6 分钟键入 L2 后 `atlas:q:minute:*` 数量增长——PX 180s 自清，无残留面；R7 分钟 L1 dict 无逐出——键基数=活跃码×5 周期×少量 count 变体，沿用 data_source.cache 无界先例（进程重启即净），不引入 LRU 复杂度；R8 回补 drain 期（深队列>30min）当日 cross_check 可能顺延失败→次日自然补，观测面如实（status=deferred_etl_running）。

## 10. 接口冻结（I 清单）

I1 `minute_path.load_minute_kline(code:str, period:str, count:int) -> list[dict]`；I2 `GET /api/minute` 查询面 `code,period∈{1,5,15,30,60},count≤320`；I3 `MinuteOut` 字段（§4）；I4 `cross_check.run(provider:str|None=None) -> CrossStats`（None=按 D3 自动路由）；I5 health 附加键 `minuteCache:str|null, minuteCircuit:str|null, bars.crossCheck:dict|null, bars.abortReason:str|null`（既有键零触碰）；I6 CacheFacade 公开签名零变化（仅 `_eligible/_read_envelope/set` 内部策略表化 + WHITELIST 增 minute:）；I7 常量冻结 `MINUTE_L1_TTL=15, MINUTE_L2_FRESH=120, MINUTE_BREAKER=900, MINUTE_RPS=1.0, MINUTE_BURST=3, MINUTE_MAX_COUNT=320, CROSS_CHECK_SAMPLE=30, CROSS_CHECK_CRON=15:35`；I8 market_bars 表零迁移、分钟线零落库；I9 前端仅 ViewStockDetail 增量控件，无新视图。

## 11. 成功判据（单用户本地标准）

1. 分钟线四态端到端（fake 上游验收）：正常回画、连败 3→熔断 900s 半开恢复、501 单次即熔断、ETL lock 持有期零上游请求且 200+etl_busy、令牌桶第 4 连击 429；
2. cross_check 一次真实东财跑通（token 空分支）：health.bars.crossCheck 六字段齐、偏差为 0 或 mismatched 码有日志可查；T0 单位校准记录进实现注释；
3. 护栏拆分：industry 表清空场景下自选/计划码与库内存量码照常日补（live drain 复跑取证），abortReason 如实；
4. 回补推进：本批结束时全库 deferred 归零或给出如实剩余数 + 预计归零日期；
5. 全门禁绿（563 基线零修改 + 新增全绿、ruff/mypy、前端 vitest 基线）+ push develop 成功（网络恢复后）。
