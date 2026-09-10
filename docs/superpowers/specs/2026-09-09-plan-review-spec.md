# P1 计划绩效复盘 — Spec（评审稿 r2）

日期：2026-09-09 ｜ 状态：待评审（r2，含第一轮评审修订）｜ 上游：`ROADMAP.md` 辅助交易主线 P1（P1 定时扫描已交付）
评审记录：r1 → r2 修订 10 项（复权口径 bfq 全链路、回放起点对齐、跳空/涨跌停停牌规则、统计口径 v2、成本常数、sell 语义澄清、计划版本披露、source 列宽、免责行；驳回 3 项见 §9 决议 13/10/14）

## 1. 背景 / 目标

交易辅助闭环 = 研究 → 决策 → **复盘**。P0 草案与 P1 定时扫描交付后，系统已能产生建议指令并推送，但指令质量无法验证：没有胜率、盈亏比、期望值，用户不知道"哪类来源的计划值得继续生成"。

本功能对已创建计划做**设计口径回算**（决议 1）：用**不复权日线**回放每份计划"如果按计划执行会怎样"，聚合成胜率/盈亏比/期望值，按**来源**（决议 2：scan:{策略}/screener/monitor/manual）分组，回答"哪个策略产生的指令质量高"。

**口径定位（生产诚实声明）**：本模块是**设计口径复盘**——评估"价格是否触及计划位"与"计划参数的设计质量"，不代表实际成交（系统无成交记录），不构成投资建议。定位为内部单用户工具的 P1；对外 SaaS 化所需能力（鉴权/租户隔离/SLA/合规体系）在 ROADMAP 非目标中明确排除。

**闭环定位**：`scan_history`（P1 定时扫描预留的运行留痕表）在本功能中首次被消费——扫描留痕与计划绩效同屏，构成"扫描 → 计划 → 结局"的完整观测。

## 2. 用户故事

1. 作为交易者，我在计划页打开「绩效复盘」，看到全部已了结计划的胜率与平均盈亏比，知道这套草案生成规则整体靠不靠谱。
2. 作为交易者，我按**来源**分组看绩效：趋势突破扫描命中的计划胜率 62%、手动计划胜率 38% → 我更信任扫描草案。
3. 作为交易者，我点开明细表看到某计划回放 R = −1（同日双触保守记败）与回放窗口，理解每个数字怎么来的。
4. 作为交易者，我在来源分组卡下看到该策略近 30 天扫描留痕（跑了多少次、命中多少），把扫描行为和计划结果关联起来。

## 3. 功能需求

- **FR-1 来源归因**：`trade_plans` 加可空列 `source VARCHAR(64)`（`scan:{strategyId}` 防截断，决议 14）；`Plan` 类型加可选 `source?: string`。取值：`scan:{strategyId}`（提醒中心代码片）/ `screener`（策略命中行草案按钮）/ `monitor`（盯盘信号入口）/ `manual`（计划页手动新建）；存量计划读取时归为 `legacy`。链路：`openFor` 签名加可选 `source?: string` → PlanDraftDialog 透传 → 确认时写入计划 → workspace PUT 同步携带（只增不改）。字段缺失/空 → `legacy`，前端展示「早期计划」。
- **FR-2 回放引擎（后端纯函数 + 数据面）**：对每份计划，回放窗 = **创建日（Asia/Shanghai）之后的第一个可交易 bar** → `validity` 过期日当日 bar（参与且为最后回放 bar；决议 9）——创建当日 bar 一律不参与（无论盘中/收盘后创建，统一保守，杜绝前视偏差）；非交易日自然跳过（bars 按交易日索引）。bars 为**不复权原始价序列**（决议 8，FR-2a）：
  - **FR-2a 复权口径（r2 修订）**：`load_history` 全链路增加 `adjustment` 参数——data_source 腾讯 K 线 param 尾字段 `qfq` → 可传空串返回原始价 `day` 行（现有 `or symbol_data.get("day")` 兜底已兼容）；`sources/base.py` + 腾讯/东财/MockUS 适配器 + Router 透传；storage `market_bars.adjustment=""` 列现成。回放**只用原始价**。理由：计划的 entry/stop/target 是创建时看到的**原始实时价**（原始价格指令），触及判定必须用原始序列——除权跳空击穿 stop 是真实订单行为，如实判定为触及；R 公式三价同源（原始价）内部一致。已知限制：R 不含分红补偿（除权缺口按原始价触发判定）。
  - buy：先判入场——日内触及 `entry`（low ≤ entry ≤ high，且该日可成交，FR-2c）后开始计结局；随后先到 `target` 记**胜**、先到 `stop` 记**败**、**同日双触保守记败**（决议 3，AGENTS 回测保守纪律）；入场未触（窗内全日 low > entry）记**未入场**。
  - **sell 语义澄清（r2 修订，决议 10）**：本仓库 `direction='sell'` = **已持仓平仓单，非做空**（AGENTS.md 关键约定：sell 计划 `price >= target` 止盈卖出、`price <= stop` 止损卖出；`usePlansStore.checkPlanTriggers` 两方向同一阈值）。几何恒为 `stop < entry < target`（与 buy 相同）。回放规则 = buy 但**无未入场判定**（已持仓）：先到 target 记胜、先到 stop 记败、同日双触保守记败。**R 公式双向统一、不翻向**：`R = (exit − entry) / (entry − stop)`——胜 exit=target（R>0）、败 exit=stop（R=−1）、平出 exit=窗口末收盘。评审建议的 `direction×(exit−entry)/|entry−stop|`（sell=−1）与本仓库语义冲突，驳回。
  - **跳空成交模型（r2 修订）**：离场触发日的实际成交价——stop 触发且 `bar.open < stop`（向下跳空）→ `exit = open`（更劣，如实）；target 触发且 `bar.open > target`（向上跳空）→ `exit = open`（更优，如实）；无跳空则 exit = 触发位。触发行带 `gapFill` 标记。
  - **涨跌停/停牌（r2 修订，FR-2c）**：复用 AGENTS 网格回测规则——停牌（`volume ≤ 0`）当日跳过（无成交可能）；一字板（`high == low`，`volume > 0`）按 `classify_code()` 板块涨跌幅判定（北交所 30%、创业板/科创板 20%、其他 10%）：**买入方向不可成交**于涨停一字板日、**卖出方向不可成交**于跌停一字板日——受影响事件（入场/离场）**顺延到下一可成交 bar**；窗口闭合仍未成交入场 → 未入场；已入场但无法离场且窗口闭合 → 平出（exit = 窗口末收盘）。
  - 窗口闭合仍未决 → **进行中**（不算胜负）；入场后窗口内 target/stop 均未触 → **平出**（exit = 窗口末收盘，R 按实际值）。
  - 首个触及入场价当日若同时触及 target/stop → 该日即计入双触裁定（不延迟到次日）。
- **FR-3 聚合 API**：`GET /api/plans/review?days=30|90|0&costR=`（0=全部，默认 90；costR 可选默认 0.02，决议 12）→ 顶层键 `{kpis, groups, items}`：
  - **净 R（r2 修订）**：`netR = R − costR`（costR 为常数摊销近似，≈5% 止损距离下的双边佣金+印花税+过户费+滑点；AGENTS 网格回测费用纪律的简化版，已披露）。
  - `kpis`：`{total, settled, winRate, avgWinR, avgLossR, payoffRatio, expectancyR, notEnteredRate, openCount, invalidCount, breakevenCount}`。**统计口径 v2（决议 11）**：胜 = 触及 target；`winRate = 胜 / (胜 + 败)`（平出移出胜率分母）；`expectancyR = mean(netR | 已了结全体 = 胜+败+平出)`（公式显式）；`payoffRatio = mean(netR | 胜) / |mean(netR | 败)|`（平出不计入两侧）；未入场/进行中/invalid 剔除一切比率但计数展示。
  - `groups`：按 `source`、`direction`、`validity`、`createdMonth`（YYYY-MM）四维各一列，行含 `{key, label, settled, wins, winRate, expectancyR, smallSample}`——`settled < 5` → `smallSample=true`，前端标注「样本不足」徽标且不渲染结论色（置信区间/多重比较校正 → 非目标 v1）。
  - `items`：明细行 `{planId, code, source, direction, entry, stop, target, validity, status, outcome(win|loss|breakeven|notEntered|open|invalid), rValue?(毛), netR?, entryDate?, exitDate?, ambiguous?(同日双触标记), gapFill?(跳空成交标记)}`，按 createdAtMs 降序；名称由前端 join 行情渲染（API 不回 name）。**回放使用计划当前参数（决议 15）**——参数修改过的计划按修改后口径回放，结果不承诺历史可复现；明细行内披露。
  - 只读计算，**零写计划/零写 plans 表**（红线）；回放结果不落库（每次现算，bars 有 DB 缓存）。
- **FR-4 留痕 API**：`GET /api/screener/scan/history?strategyId=&limit=`（limit 可选，默认 30）→ `{history: [list_scan_history 行（camelCase）]}`——把 P1 已有的 `list_scan_history` 助手首次接到端点。
- **FR-5 UI（ViewPlans 扩展「绩效」区块，决议 5）**：计划页下方新增可折叠「绩效复盘」面板：
  - KPI 卡行（FR-3 kpis 主要项 + 总数）；分组 Tab（来源/方向/有效期/月份）切换分组表；
  - 明细表（可按结局/R 值排序；同日双控行标「保守裁定」角标、跳空成交行标「跳空」角标、参数修改披露于明细）；
  - 来源为 `scan:{strategyId}` 的分组行展开显示近 30 天扫描留痕摘要（FR-4 数据：运行次数/命中数均值/最近运行）；
  - 入口默认折叠 + 顶部摘要一句话（如「近 90 天 23 份已了结计划，胜率 52%」）；
  - **固定免责行（r2 修订）**：面板底部常驻——「设计口径回放，非实际成交；历史回放不代表未来；不构成投资建议。」
  - data-testid：`review-toggle`、`review-kpis`、`review-group-tab`、`review-items`、`review-trace`、`review-disclaimer`。
- **FR-6 观测**：回放计算记结构化日志（logger `atlas.review`：计划数/窗口/唯一代码数/上游拉取次数/costR/elapsed_ms）；复盘为只读端点，失败如实 502（复用 `ERR_UPSTREAM_UNAVAILABLE`，历史拉取失败时）。

## 4. 数据模型 / 算法

- **迁移**：Alembic 前向迁移——`trade_plans ADD COLUMN source VARCHAR(64) NULL`（纯增量；downgrade drop column）。模型同步加列。
- **回放引擎**：`backend/plan_review.py` 新模块——`review_plans(plans, days, cost_r, router, settings_getter) -> dict` 纯计算 + bars 获取委托；bars 获取按唯一 code 去重批量预取（`load_market_bars(code, adjustment="")` 查 DB，缺口走 router `load_history(adjustment="")` + `save_market_bars(adjustment="")` 落缓存），**原始价序列**。
- **状态解耦**：回放不读计划 status（决议 4）——status 是人工操作痕迹，回放窗只由 createdAtMs + validity 决定；UI 明细仍显示当前 status 供对照。
- **参数快照口径（决议 15）**：回放读取计划**当前** entry/stop/target（无版本表）；已知限制披露于 UI 明细。
- **除零/缺参**：`entry−stop ≤ 0` 或 entry/stop/target ≤ 0 的残缺计划 → 结局 `invalid` 单列不计入胜率（计数进 kpis `invalidCount`）。
- **规模假设（披露）**：本地单用户计划量级 ≤ 数百份；同步端点 + bars DB 缓存，首次冷跑受唯一 code 数 × 上游拉取影响（每个 ~1s），此后命中缓存秒级；分页/异步预计算 → P2 非目标。

## 5. 边界表

| 场景 | 行为 |
|---|---|
| 计划无来源字段（存量） | source='legacy'，UI「早期计划」，参与全局指标、来源分组单列 |
| validity = 长期/无过期 | 窗口终点 = 今天；未决 → 进行中 |
| 创建当日即为交易日 | 当日 bar 不参与回放（起点 = 下一可交易 bar，决议 9） |
| 复权 | 全链路原始价（bfq）；除权跳空按原始价如实触发；R 不含分红补偿（披露） |
| 跳空越过 stop/target | 按跳空成交模型取 open 成交价（gapFill 标记） |
| 停牌（volume ≤ 0） | 当日跳过，无任何事件 |
| 一字板不可成交方向 | 事件顺延下一可成交 bar；窗口闭合未了结 → 平出@末收盘 |
| bars 不足（次新股/停牌长） | 窗口内可用 bars 回放；起点前无数据 → notEntered；无 bars → invalid |
| 同日触及 entry 且 target/stop | 双触裁定当日生效（保守记败 + ambiguous 标记） |
| 上游历史拉取失败 | 任一 code 拉取失败 → 整体 502 ERR_UPSTREAM_UNAVAILABLE（如实报错；bars 已 DB 缓存的下次直接用，不重试风暴） |
| days/costR 参数非法 | 422 ERR_VALIDATION_ERROR |
| 计划数 0 | 空态：kpis 全零 + 「暂无已了结计划」 |
| 回放中 | 同步端点（规模假设见 §4），前端 loading 态 |
| 浮点 | R 保留 3 位；比率百分比 1 位 |

## 6. 前端交互

- ViewPlans 挂载 `useReviewStore`（新 store）：`fetchReview(days)` / `review` / `loading` / `activeGroup`；days 切换（近 30/近 90/全部）重拉。
- 折叠面板展开时首次拉取；后续手动刷新按钮（复用 `refresh-cw` 图标惯例）。
- 明细行展开显示回放细节（entryDate/exitDate/ambiguous/gapFill 角标）；不做行内编辑（非目标）。
- scan 留痕摘要：来源分组行展开态内嵌 `review-trace` 列表（run_at 降序前 10 条 + 汇总）。
- 免责行常驻面板底部（FR-5）。

## 7. 测试与验收

1. 回放引擎纯函数单测：胜/败/平出/未入场/进行中/invalid 六态 + 同日双触保守裁定 + sell 方向（平仓语义，非做空）+ R 公式双向（含 R=−1 与正 R 数值断言，**手工推演核对**）+ 跳空成交价（gap up/down 各一）+ 停牌跳过 + 一字板顺延（涨停买入/跌停卖出各一）+ **回放起点排除创建当日**（反前视回归）。
2. bfq 链路：data_source param 尾字段/响应 day 行解析；adapter 透传；storage adjustment="" 存取往返。
3. source 链路：openFor 各入口传 source → 计划落 source；存量无 source → legacy 归一；workspace PUT 同步往返保留 source；`scan:{strategyId}` 长度上限内不截断。
4. 聚合 API：days/costR 校验 422；统计口径 v2（winRate 分母 = 胜+败；expectancyR = 已了结全体；payoffRatio 平出不计入）；smallSample 徽标；四维分组键；空计划空态；costR 默认 0.02 与净 R 计算。
5. 迁移：upgrade/downgrade 往返 + source 列可空（VARCHAR(64)）。
6. 前端：折叠展开首次拉取、分组 Tab 切换、明细排序、角标渲染、testids 全部存在（含 `review-disclaimer`）、scan 留痕摘要渲染。
7. 验收：真实冒烟——造 3 份不同 source 计划（含 1 份 scan:{id}）→ GET review 返回一致聚合 → ViewPlans 面板渲染截图级描述。

## 8. 非目标

- 方案 C 手动登记实际成交（后续独立增强；本 spec 的回放结果不代表实际成交）
- 盘中/分钟粒度回放（P2 分钟级 K 线前置依赖）、卖空回测、组合层风险（独立 P1 组合风险视图）
- 计划版本/审计表（P3 独立功能；v1 当前字段口径 + UI 披露，决议 15）
- 置信区间/多重比较校正/Profit Factor/最大回撤/R 分布图表（统计 v2，P2）
- 分页/游标/异步预计算（本地单用户规模假设下 YAGNI，P2）
- 回放结果落库/缓存端点结果（bars 已有 DB 缓存，聚合每次现算）
- 自动改写/终止计划；基于绩效的自动策略调参
- 多租户/鉴权/SLA/合规体系（ROADMAP 非目标红线，决议 13）

## 9. 决议表

| # | 决议点 | 结论 |
|---|---|---|
| 1 | 回算口径 | 方案 A 设计口径回算（日线回放），方案 C 手动登记留作后续增强 |
| 2 | 来源归因 | 方案 A 引入 source 字段（scan:{strategyId}/screener/monitor/manual/legacy），策略粒度保留 |
| 3 | 同日双触 | 保守记败 + ambiguous 标记（AGENTS 回测保守纪律） |
| 4 | 回放窗口 | createdAtMs → validity 过期日，与 status 解耦；不可靠时间戳不参与 |
| 5 | UI 落点 | ViewPlans 扩展绩效区块（可折叠），无新视图 |
| 6 | sell 计划 | 同 buy 回放但无未入场判定；R 通式 |
| 7 | 其余实现细节 | 授权控制者裁定（bars 缓存复用、502 整体语义、legacy 归一、指标集） |
| 8 | 复权口径（r2） | **原始价（bfq）全链路**：load_history 加 adjustment 参数，回放只用原始序列；R 不含分红补偿（披露）——r1 的 qfq 口径系评审修订 |
| 9 | 回放起点（r2） | 创建日之后的第一个可交易 bar；创建当日 bar 不参与（反前视）；过期日 bar 参与 |
| 10 | sell 语义（r2） | 已持仓平仓单（非做空），AGENTS 语义引用进 spec；R 公式不翻向——评审建议的 direction×R 驳回（与本仓库语义冲突） |
| 11 | 统计口径（r2） | 胜=触及 target；winRate 分母=胜+败；expectancyR=已了结全体 mean(netR)；payoffRatio 平出不计入；settled<5 样本不足徽标；置信区间等 P2 |
| 12 | 成本模型（r2） | 常数 costR（默认 0.02，query 可覆盖），netR=R−costR；常数摊销近似披露 |
| 13 | 生产级范围（r2） | 多租户/鉴权/分页/Prometheus/SLA/合规体系驳回——ROADMAP 非目标红线（本地单用户工具）；跳空/涨跌停停牌/免责行接受 |
| 14 | source 列宽（r2） | VARCHAR(64)（防 scan:{strategyId} 截断）；不加索引（聚合内存分组） |
| 15 | 计划版本（r2） | 回放用当前参数口径 + UI 披露；版本/审计表 P3 非目标 |
