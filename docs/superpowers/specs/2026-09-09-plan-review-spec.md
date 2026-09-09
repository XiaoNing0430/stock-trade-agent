# P1 计划绩效复盘 — Spec（评审稿）

日期：2026-09-09 ｜ 状态：待评审 ｜ 上游：`ROADMAP.md` 辅助交易主线 P1（P1 定时扫描已交付）

## 1. 背景 / 目标

交易辅助闭环 = 研究 → 决策 → **复盘**。P0 草案与 P1 定时扫描交付后，系统已能产生建议指令并推送，但指令质量无法验证：没有胜率、盈亏比、期望值，用户不知道"哪类来源的计划值得继续生成"。

本功能对已创建计划做**设计口径回算**（方案 A，决议 1）：用日线数据回放每份计划"如果按计划执行会怎样"，聚合成胜率/盈亏比/期望值，按**来源**（方案 A 归因，决议 2：scan:{策略}/screener/monitor/manual）分组，回答"哪个策略产生的指令质量高"。

**闭环定位**：`scan_history`（P1 定时扫描预留的运行留痕表）在本功能中首次被消费——扫描留痕与计划绩效同屏，构成"扫描 → 计划 → 结局"的完整观测。

## 2. 用户故事

1. 作为交易者，我在计划页打开「绩效复盘」，看到全部已了结计划的胜率与平均盈亏比，知道这套草案生成规则整体靠不靠谱。
2. 作为交易者，我按**来源**分组看绩效：趋势突破扫描命中的计划胜率 62%、手动计划胜率 38% → 我更信任扫描草案。
3. 作为交易者，我点开明细表看到某计划回放 R = -1（同日双触保守记败）与回放窗口，理解每个数字怎么来的。
4. 作为交易者，我在来源分组卡下看到该策略近 30 天扫描留痕（跑了多少次、命中多少），把扫描行为和计划结果关联起来。

## 3. 功能需求

- **FR-1 来源归因**：`trade_plans` 加可空列 `source VARCHAR(32)`；`Plan` 类型加可选 `source?: string`。取值：`scan:{strategyId}`（提醒中心代码片）/ `screener`（策略命中行草案按钮）/ `monitor`（盯盘信号入口）/ `manual`（计划页手动新建）；存量计划读取时归为 `legacy`。链路：`openFor` 签名加可选 `source?: string` → PlanDraftDialog 透传 → 确认时写入计划 → workspace PUT 同步携带（只增不改）。字段缺失/空 → `legacy`，前端展示「早期计划」。
- **FR-2 回放引擎（后端纯函数 + 数据面）**：对每份计划，回放窗 = `createdAtMs` → `validity` 过期日（`validityExpiry` 同源逻辑，决议 4）；用日线 qfq bars（`load_history`，DB 缓存 `load_market_bars/save_market_bars` 复用，不足再上游拉取）逐日判定：
  - buy：先判入场——收盘或日内触及 `entry`（low ≤ entry ≤ high）后开始计结局；随后先到 `target`（high ≥ target）记**胜**、先到 `stop`（low ≤ stop）记**败**、**同日双触保守记败**（决议 3，AGENTS 回测保守纪律）；入场未触（窗内全日 low > entry）记**未入场**。
  - sell：无未入场判定（已持仓）；先到 `target`（high ≥ target）记胜、先到 `stop`（low ≤ stop）记败、同日双触保守记败。
  - 窗口闭合仍未决 → **进行中**（不算胜负）；入场后窗口内 target/stop 均未触 → **平出**（exit = 窗口末日收盘，R 按实际值）。
  - **R 公式（双向统一）**：`R = (exit − entry) / (entry − stop)`；胜 exit=target、败 exit=stop（R=−1）、平出 exit=窗口末收盘。买入/卖出方向通式成立（卖出计划 stop < entry）。
  - 首个触及入场价当日若同时触及 target/stop → 该日即计入双触裁定（不延迟到次日）。
- **FR-3 聚合 API**：`GET /api/plans/review?days=30|90|0`（0=全部，默认 90）→ 顶层键 `{kpis, groups, items}`：
  - `kpis`：`{total, settled, winRate, avgWinR, avgLossR, payoffRatio, expectancyR, notEnteredRate, openCount, invalidCount}`（winRate 分母 = settled = 胜+败+平出，**未入场/进行中/invalid 剔除**但计数展示；payoffRatio = avgWinR ÷ |avgLossR|）。
  - `groups`：按 `source`、`direction`、`validity`、`createdMonth`（YYYY-MM）四维各一列，行含 `{key, label, settled, wins, winRate, expectancyR}`。
  - `items`：明细行 `{planId, code, source, direction, entry, stop, target, validity, status, outcome(win|loss|breakeven|notEntered|open|invalid), rValue?, entryDate?, exitDate?, ambiguous?(同日双触标记)}`，按 createdAtMs 降序；名称由前端 join 行情渲染（API 不回 name）。
  - 只读计算，**零写计划/零写 plans 表**（红线）；回放结果不落库（每次现算，bars 有 DB 缓存）。
- **FR-4 留痕 API**：`GET /api/screener/scan/history?strategyId=&limit=`（limit 可选，默认 30）→ `{history: [list_scan_history 行（camelCase）]}`——把 P1 已有的 `list_scan_history` 助手首次接到端点。
- **FR-5 UI（ViewPlans 扩展「绩效」区块，决议 5）**：计划页下方新增可折叠「绩效复盘」面板：
  - KPI 卡行（FR-3 kpis 六项 + 总数）；分组 Tab（来源/方向/有效期/月份）切换分组表；
  - 明细表（可按结局/ R 值排序；同日双控行标「保守裁定」角标）；
  - 来源为 `scan:{strategyId}` 的分组行展开显示近 30 天扫描留痕摘要（FR-4 数据：运行次数/命中数均值/最近运行）；
  - 入口默认折叠 + 顶部摘要一句话（如「近 90 天 23 份已了结计划，胜率 52%」）；
  - data-testid：`review-toggle`、`review-kpis`、`review-group-tab`、`review-items`、`review-trace`。
- **FR-6 观测**：回放计算记结构化日志（logger `atlas.review`：计划数/窗口/唯一代码数/上游拉取次数/elapsed_ms）；复盘为只读端点，失败如实 502（复用 `ERR_UPSTREAM_UNAVAILABLE`，历史拉取失败时）。

## 4. 数据模型 / 算法

- **迁移**：Alembic 前向迁移——`trade_plans ADD COLUMN source VARCHAR(32) NULL`（纯增量；downgrade drop column）。模型同步加列。
- **回放引擎**：`backend/plan_review.py` 新模块——`review_plans(plans, days, router, settings_getter) -> dict` 纯计算 + bars 获取委托；bars 获取按唯一 code 去重批量预取（先 `load_market_bars` 查 DB，缺口走 router `load_history` + `save_market_bars` 落缓存），qfq。
- **状态解耦**：回放不读计划 status（决议 4）——status 是人工操作痕迹，回放窗只由 createdAtMs + validity 决定；UI 明细仍显示当前 status 供对照。
- **除零/缺参**：`entry−stop ≤ 0` 或 entry/stop/target ≤ 0 的残缺计划 → 结局 `invalid` 单列不计入胜率（计数进 kpis 附注）。

## 5. 边界表

| 场景 | 行为 |
|---|---|
| 计划无来源字段（存量） | source='legacy'，UI「早期计划」，参与全局指标、来源分组单列 |
| validity = 长期/无过期 | 窗口终点 = 今天；未决 → 进行中 |
| bars 不足（次新股/停牌长） | 窗口内可用 bars 回放；起点前无数据 → notEntered；无 bars → invalid |
| 同日触及 entry 且 target/stop | 双触裁定当日生效（保守记败 + ambiguous 标记） |
| 上游历史拉取失败 | 任一 code 拉取失败 → 整体 502 ERR_UPSTREAM_UNAVAILABLE（如实报错；bars 已 DB 缓存的下次直接用，不重试风暴） |
| days 参数非法 | 422 ERR_VALIDATION_ERROR |
| 计划数 0 | 空态：kpis 全零 + 「暂无已了结计划」 |
| 回放中 | 同步端点，本地计划量级（≤几百）× DB 缓存 bars，秒级；前端 loading 态 |
| 浮点 | R 保留 3 位；比率百分比 1 位 |

## 6. 前端交互

- ViewPlans 挂载 `useReviewStore`（新 store）：`fetchReview(days)` / `review` / `loading` / `activeGroup`；days 切换（近 30/近 90/全部）重拉。
- 折叠面板展开时首次拉取；后续手动刷新按钮（复用 `refresh-cw` 图标惯例）。
- 明细行展开显示回放细节（entryDate/exitDate/ambiguous 角标）；不做行内编辑（非目标）。
- scan 留痕摘要：来源分组行展开态内嵌 `review-trace` 列表（run_at 降序前 10 条 + 汇总）。

## 7. 测试与验收

1. 回放引擎纯函数单测：胜/败/平出/未入场/进行中/invalid 六态 + 同日双触保守裁定 + sell 方向 + 双向 R 公式（含 R=−1 与正 R 数值断言，**手工推演核对**）。
2. source 链路：openFor 各入口传 source → 计划落 source；存量无 source → legacy 归一；workspace PUT 同步往返保留 source。
3. 聚合 API：days 校验 422；kpis 分母口径（未入场/进行中剔除）；四维分组键；空计划空态。
4. 迁移：upgrade/downgrade 往返 + source 列可空。
5. 前端：折叠展开首次拉取、分组 Tab 切换、明细排序、testids 全部存在、scan 留痕摘要渲染。
6. 验收：真实冒烟——造 3 份不同 source 计划（含 1 份 scan:{id}）→ GET review 返回一致聚合 → ViewPlans 面板渲染截图级描述。

## 8. 非目标

- 方案 C 手动登记实际成交（后续独立增强；本 spec 的回放结果不代表实际成交）
- 盘中/分钟粒度回放；卖空回测；组合层风险（独立 P1 组合风险视图）
- 回放结果落库/缓存端点结果（bars 已有 DB 缓存，聚合每次现算）
- 自动改写/终止计划；基于绩效的自动策略调参

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
