# 组合风险视图（P1）— 设计规格 r1

日期：2026-09-12 ｜ 状态：**待评审** ｜ 上游：ROADMAP「P1 组合风险视图：自选 + 计划合计敞口、行业集中度、虚拟组合回撤」
定位：研究向**纯计算视图**，读现有计划/自选数据，零写入计划（红线：无券商、无自动执行、绝不造数）。

## 0. 术语

| 术语 | 定义 |
|---|---|
| 建仓组合（主层） | 仅 buy 型计划（执行中/已触发 + 回放窗内已结束者）构成的虚拟 NAV，验证建仓草案质量 |
| 完整交易组合（闭环层） | 主层 + 用户显式关联（sell→buy 交易对）的平仓信号参与离场的 NAV |
| 孤儿平仓单 | 未关联建仓计划的 sell 计划；永不进 NAV，仅信号统计 |
| 自选观察组合 | 自选股等权指数（机会成本参考线）；不叫"虚拟组合"，默认关闭 |
| 名义额分配 | 计划触发日按 当时NAV×positionPct 固定分配资金，此后不再平衡、永不重新归一 |

## 1. 决议登记（评审对话固化）

- **D1 组合定义**：虚拟组合只含计划不含自选（A 为默认）；自选以"自选观察组合"命名做高级可选第二线，默认关闭，不参与主指标。
- **D2 sell 处理（A+ 三层）**：主层不含 sell；闭环层含显式关联交易对；辅助层"平仓信号质量看板"（孤儿+冗余信号）。不编造持仓台账。
- **D3 离场规则（A+）**：默认**先到先平**；**同日固定优先级 止损 > 关联 sell > 止盈**，同日多信号记"冲突事件"可查；sell 触发时仓位已离场 → 记"冗余平仓"进信号看板不执行。用户可对每个交易对**显式选覆盖模式**（四档，见 §5.3），"仅 sell"档需前端二次确认；系统绝不隐式改写。
- **D4 窗口与归一**：回看切换器 1M/3M/6M/1Y/ALL（默认 3M）+ 高级自定义起始日；**名义额静态分配、永不重新归一、不做任何再平衡**（否决触发日重归一与每日动态归一——前者隐含再平衡、后者消灭现金层使回撤变相对强弱）。跨界规则见 §5.2。部分平仓（sell 仓位 < buy 仓位按比例）→ **延期 P2**，v1 交易对平仓恒为全平。
- **D5 敞口/集中度**：敞口卡只算计划（执行中+已触发）ΣpositionPct；行业集中度主指标=计划成分（按当前市值权重×行业）Top3/HHI/分布；自选单列"观察池行业分布"标注不参竞；"若自选按 capPct 建仓"假想参考线默认关闭、虚线呈现+文案声明。行业无数据归"未知"桶，非计划来源标 degraded。
- **D6 红线标注**（面板底部固定）：「虚拟组合为设计口径模拟回放，非真实成交，不构成投资建议。孤儿平仓单仅作信号统计，不纳入 NAV。」

## 2. 方案选型

**Ⅰ（采纳）**：新模块 `backend/portfolio_risk.py`，import `plan_review` 的纯函数（`slice_window`/`validity_expiry_date`/`_limit_prices`/`_board_pct` 语义），新建组合状态机；plan_review 零改动（刚过终审，控制回归面）。
Ⅱ plan_review 加组合模式 —— 否决：双职责纠缠 + 触碰已终审引擎。Ⅲ 前端回放 —— 否决：违背"后端计算/前端渲染"既有分层。

## 3. 数据模型 / 存储（迁移 1）

- `trade_plans` +2 可空列：`related_plan` VARCHAR(64) NULL（sell→buy 的 plan id，仅 sell 使用）、`exit_mode` VARCHAR(16) NULL（NULL≡race 先到先平；枚举 `race | sell_priority | sell_stop_only | sell_only`）。
- `storage._plan_dict` 透传两键；`save_workspace` 映射同 `source` 模式（缺省 None）；`models.ts Plan` + `relatedPlan?: string; exitMode?: 'race'|'sell_priority'|'sell_stop_only'|'sell_only'`。
- 关联约束（后端校验，违反 → 422 `api_error`）：仅 sell 可携带 relatedPlan；目标须存在、为 buy、workspace 内、非归档；**一 buy 至多被一 sell 关联**；禁自引用；悬空 relatedPlan（目标已删）→ 引擎视作孤儿 + degraded 标注 `danglingRelatedPlan`。
- 设置 +1 键：`totalPositionCapPct`（int，默认 **100**，范围 20..300）——敞口卡"上限对比"的分母与 >100% 提示锚。

## 4. 行业映射

- 新模块 `backend/industry_map.py`：`get_industry_map() -> dict[code, str]`，进程内缓存 **TTL 24h**；数据源=东财 clist 全市场分页（`_CLIST_FIELDS` 追加 `f100`，新增分页拉取复用 screener 既有请求构造，≤10 req/s 限频纪律）。
- 失败/无字段：返回上次成功缓存（stale 容忍）或空图；消费侧统一：查不到 → "未知"桶。响应 `meta.industryDegraded: true|false`（全量或降级时面板披露，遵循 degraded 惯例）。
- 腾讯排名接口无行业字段 → 行业模块与 historySource 设置**无关**（固定东财，文档如实写明，同"复盘 bars 走路由源"的披露风格）。

## 5. 回放引擎（`backend/portfolio_risk.py`）

### 5.1 输入/输出
`build_portfolio(plans, watchlist, settings, bars_map, window) -> payload`（纯函数，bars 由端点经 `plan_review.fetch_all_bars` 预取——bfq 口径、degraded 披露自动继承）。

### 5.2 成分与名义额
- 纳入（主层）：`direction=buy`、status ∈ {执行中,已触发,已过期,已归档}，且与窗口有存续交集。
- 入场：复用复盘微结构——entry 触及（跳空穿越恒记计划 entry）、一字板顺延、停牌跳过；执行中/已触发未触发的 buy 在窗尾前入场按实际日，未入场计现金。
- 触发日：`notional = NAV_t × positionPct / 100`；**当日累计分配 > NAV_t → 当日各新分配等比缩放至剩余现金**（既有持仓名义额不动——缩放只作用于新分配，不再平衡存量）。跨界（D4 原文口径）：窗前已结束→不纳入；**窗前已触发且存续→窗起点按 positionPct 分配名义额（NAV_起点×positionPct），收益自窗起点起算，窗前表现不追溯（不编造）**；窗尾未离场→最后 close 记浮动，**持有到"今天"**（open 仓不算结束）。
- sell 计划：主层零参与；闭环层中已关联者作为其 buy 仓位的离场信号源。
- 触发日语义注记：buy 的"触发"=entry 触及（低吸单可能创建后数日才触发），名义额在**触发当日**分配而非创建日——与"按计划执行"一致。

### 5.3 交易对离场（闭环层，仓位状态机）
每日对每个存续仓位求信号集 `S ⊆ {stop, target, relatedSell}`（关联 sell 自身也要先"触发"：sell 的 entry/目标价触及，复用同一微结构），交集日：
| exitMode | 生效信号 | 同日优先级 |
|---|---|---|
| race（默认） | 止损, 止盈, 关联sell | 止损 > 关联sell > 止盈（D3 裁决） |
| sell_priority | 止损, 关联sell（止盈失效；"让利润跑"） | **关联sell > 止损**（模式名即语义：sell 优先） |
| sell_stop_only | 止损, 关联sell（止盈失效，等信号） | **止损 > 关联sell**（风控优先，与 race 同序仅去止盈） |
| sell_only | 仅关联sell | —（前端二次确认） |
- 离场执行价=复盘同款（跳空 open / 触发价 / 一字板顺延），转现金；已离场后到达的关联 sell → `redundant` 事件。
- 冲突事件：同日 |S|≥2 → `{date, code, buyPlanId, signals[], executed}` 入 `conflicts` 列表。

### 5.4 汇总
`NAV 序列（日频）`、`MDD = max(1 − NAV_t / max_{s≤t} NAV_s)`、当前仓位/现金%、计划数量状态分布、行业集中度（**按当前市值权重**，含"未知"桶；HHI=Σw²，Top3=权重前三合计）。信号看板锚点定义：sell（孤儿或已配对但冗余）的**信号日 = 窗口内其 stop/target 任一首次触及日**（同日双触按复盘保守口径取 stop），**基准价 = 该日复盘同款执行价（含跳空 open）**；其后 5/10/20 交易日标的涨跌幅 = close[t+N]/基准价 − 1、区间最大反弹/回撤；数据不足 N 日 → 该列 null（不造数）。

## 6. API

`GET /api/portfolio/risk?days=30|90|180|365|0&start=YYYY-MM-DD&layer=core|closed&withWatch=true|false`
- 校验（越界均 422，同复盘纪律）：days 白名单（0=ALL，默认 **90**→前端 3M）；start 给定时须为合法 ISO、∈ [today−1825d, today−1d] 且**覆盖 days**（二者同给 start 优先）；layer ∈ {core, closed}（默认 core）；withWatch bool（默认 false）。
- 顶层键：`{kpis, nav: {dates[], values[], mdd}, exposure: {plannedPct, capPct, overCap, cashPct, amountByEquity}, concentration: {top3, hhi, industries[{key,label,pct}], unknownPct, watchPool{...}, hypothetical{...}|null}, pairs: [...], orphans: [...], signals: {items[], note}, conflicts: [...], degraded: [codes], meta: {layer, windowStart, truncatedAt?, industryDegraded, equity}}`。
- `kpis`：`{navNow, mdd, exposurePct, cashPct, planCount:{active,triggered,closedInWindow,notEntered}, orphanSellCount, pairCount}`；金额换算锚 `defaultCapital`（meta.equity 如实回显）。
- 上游失败：复用 `ReviewUpstreamError` → 502 `{error,code,detail.failedCodes}` + `atlas.review` 日志（同式）；空计划 → 200 全零态结构。

## 7. 前端

- 新视图 **ViewPortfolio「组合风险」**（第 8 视图）：constants.ts NAV 项 `id:'portfolio'`、main.ts 注册、app.ts 快捷键表追加 `6: 'portfolio'`（现 1-5，不重排既有）。
- `usePortfolioStore`：`days/start/layer/withWatch` 参数态 + `fetch`（URL 拼参、单请求）+ `error` 态（红线：失败可见化，复用 review 错误模式）+ `fetchedOnce`。
- 布局（自上而下）：控制行（回看 chips｜层切换 chips｜自选观察组合开关·高级｜起始日输入·高级｜假想线开关·高级，**三项高级默认关**）→ KPI 行 → NAV 曲线（**复用 chart.ts 自研 svg**，多线：主 NAV + 现金底线；withWatch 时叠加"自选观察组合（等权指数，非持仓）"灰虚线，同图标注文案）→ 敞口卡（Σ vs totalPositionCapPct，超限标红）→ 集中度卡（横向条 + Top3/HHI；观察池单列行 + 假想虚线条注"假想参考，非真实持仓"）→ 折叠区：交易对/孤儿/信号看板/冲突日志。
- **交易对管理入口在 ViewPlans**：sell 行（执行中/已触发）"关联建仓计划"按钮 → 下拉仅列同 code 的未配对 buy；行内 exitMode 四档下拉（选 sell_only 弹二次确认）；解除=置空。写路径复用 workspace PUT 整表同步（现计划编辑唯一通路），保存失败 → toast 错误 + 重拉。
- 空态/单例：无 buy 计划 → 曲线区空态文案；行业全"未知" → 集中度卡整卡降级文案。

## 8. 错误处理与降级

| 故障 | 表现 |
|---|---|
| bars 全/部分拉取失败（无本地兜底） | 502 failedCodes + degraded 面板条（同复盘） |
| 部分 code 走本地持久化兜底 | payload.degraded + 面板黄条"数据可能陈旧"（同复盘文案惯例） |
| 行业源失败 | 全"未知"桶 + industryDegraded 披露，**不影响 NAV 计算**（正交降级） |
| 悬空 relatedPlan | 该 sell 按孤儿处理 + conflicts 注记 |
| 参数越界 | 422 中文 detail |

## 9. 测试策略

- 引擎表驱动单测（主战场）：入场微结构继承、名义额分配与当日缩放、四类跨界窗口、四 exitMode × 同日冲突矩阵、冗余平仓、MDD、HHI/Top3/未知桶、信号看板 5/10/20 截断 null。
- 存储迁移 + 关联校验（422 全分支）+ 悬空关联；industry_map 缓存/降级（fake client）；API 契约（422/502/200 全零态/degraded）。
- 前端：store（拼参、错误态、fetchedOnce）+ ViewPortfolio（高级默认关、degraded 黄条、红线文案存在）+ ViewPlans 关联交互（下拉过滤同 code 未配对、二次确认）。
- 冒烟（真实网络，控制器执行）：播种含 buy/sell/配对/孤儿 → 主层与闭环层 NAV 手推一致 + 行业映射真实返回 + 恢复快照零残留。

## 10. 非目标 / 延期

无真实持仓台账、无自动下单（红线）；部分平仓 P2；组合再平衡策略模拟不做；费用只影响信号解读不进入 NAV 日收益（NAV 用 close-to-close 毛收益，费用口径在面板注记披露）；分红拆股复权漂移与复盘同源限制；行业映射不入库（进程缓存）；分钟级/组合级 VaR、相关性矩阵 → 后续 P2+。

## 11. 已知限制（ROADMAP 行将披露）

设计口径模拟非真实成交；ALL 窗受 300 bars 上限，起点早于最早可得 bar 时按最早 bar 截断并 `truncatedAt` 披露；行业=东财 f100 单源，进程缓存重启即失；NAV 未计交易费用。
