# 规格（Spec）：研究 → 决策最小闭环（trade-assist-loop）

> 状态：**待评审**。评审通过后据本 spec 撰写实施计划（plans 文档），再进入实施。
> 定位依据：`ROADMAP.md` 「辅助交易：研究 → 决策闭环」P0 三项；`AGENTS.md` 定位——
> **交易辅助决策工具，非自动执行系统**：指令只到用户，人工执行；从不连接券商，从不自动下单。

---

## 1. 目标与非目标

### 1.1 目标
让用户在策略选股命中一只票后，**三步内**拿到可执行的交易指令草案：
① 看到命中 → ② （可选）对该票回测验证 → ③ 拿到带止损 / 目标 / 建议仓位的计划草案，一键转入既有计划体系人工盯触发。

### 1.2 本 feature 非目标（防蔓延）
- sell（持仓卖出）草案——需持仓台账，属 P1 组合风险视图之后
- 基于真实绩效的 Kelly 仓位——依赖 P1 计划绩效复盘产出的胜率 / 盈亏比；本 feature 仅提供**手动输入参数**的凯利参考值
- 盯盘信号自动生成草案 / 定时扫描推送——P1 策略定时扫描
- 组合敞口校验——P1 组合风险视图
- 自动下单 / 券商对接——永久非目标

## 2. 用户旅程（三条主线）

| # | 旅程 | 动作链 |
|---|------|--------|
| J1 | 策略命中 → 草案 → 计划 | 「策略」tab 命中行点「生成草案」→ 草案对话框（预填可编辑）→ 确认 → 计划落入既有计划体系（执行中，盯盘中心接管触发） |
| J2 | 策略命中 → 回测验证 | 命中行点「回测」→ 跳转策略回测视图，代码预填 → 用户选引擎（默认双均线）→ 手动运行 |
| J3 | 个股详情 → 草案 | 个股详情页「生成计划草案」→ 同 J1 对话框 |

## 3. 功能需求（FR，逐条可验收）

- **FR-1 草案计算（无状态）**：`POST /api/assist/plan-draft` 只做计算**不写库**；写入由前端走既有 `PUT /api/workspace`（复用 409 修订锁语义）。理由：计划属于工作区载荷，绝不能出现第二条绕过修订锁的写入路径。
- **FR-2 入场价**：默认取该票实时快照价（screener 行已携带；个股详情走既有 `/api/market` 缓存）；请求可显式覆盖 `entryPrice`。
- **FR-3 止损**：同时计算两种并返回——`stopAtr = entry − 2×ATR14`、`stopMa20 = MA20 收盘价`；默认采用 `stopMode` 设置（`atr` / `ma20`，默认 `atr`）。仅取**已收盘数据**计算（见 §5）。
- **FR-4 目标**：`target = entry + (entry − stop) × rrRatio`，`rrRatio` 默认 2.0（盈亏比 ≥ 2:1）。
- **FR-5 仓位**：`riskAmount = accountEquity × riskPct`；`suggestedShares = floor(riskAmount ÷ (entry − stop) ÷ 100) × 100`；`positionPct = shares×entry ÷ accountEquity`。资金不足一手 → `shares = 0` + warning（**绝不凑数**）。
- **FR-6 单票市值上限**：`shares×entry > accountEquity × positionCapPct` 时截断至上限对应手数 + warning（防单票过度集中；组合级敞口属 P1）。
- **FR-7 Kelly 参考**：对话框内可选展示——用户手输胜率 `W`、盈亏比 `R`，`kelly = W − (1−W)/R`，展示**半凯利**仓位比例；仅参考值，不参与默认仓位。
- **FR-8 回测联动**：命中行「回测」→ 策略回测视图代码预填，引擎选择留给用户（默认双均线 ma_cross），**不自动运行**（成本意识）。
- **FR-9 免责声明**：API 响应与对话框固定文案：「算法生成的建议，非投资建议；止损 / 目标 / 仓位均基于公开行情计算，请自行判断」。后端字段 `disclaimer`，前端渲染不可省略。
- **FR-13 客户端调参重算（零 API）**：服务端一次返回指标原值（atr14/ma20/stopAtr/stopMa20）与设置默认值后，对话框内调整 rrRatio / stopMode / entry 覆盖 / 权益的重算（止损选择、target、shares、positionPct）由**前端纯函数**完成（`frontend/src/modules/assistCalc.ts`，与后端公式逐字段一致），调参不产生任何 API 调用——限频配额仅被「打开草案」消耗，从结构上规避输入风暴（评审提醒的防抖由此不再需要）。

## 4. API 契约

### 4.1 `POST /api/assist/plan-draft`

**请求** `PlanDraftIn`：

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| code | str | 必填 | 六位代码，`classify_code` 校验 |
| entryPrice | float \| null | null | 覆盖实时价（主路径由前端快照携带，**后端不额外调实时接口**） |
| entryAsOfMs | int \| null | null | 入场价快照时间戳（epoch ms）；用于 stale 判定（§7） |
| stopMode | "atr" \| "ma20" \| null | null | 不传用设置 |
| rrRatio | float \| null | null | 1–10，不传用设置 |
| accountEquity | float \| null | null | >0，不传用设置（复用既有 `defaultCapital`） |
| riskPct | float \| null | null | 0.1–5（%），不传用设置 |

**响应** `PlanDraftOut`（200）：

| 字段 | 类型 | 说明 |
|---|---|---|
| code / name | str | 名称来自快照，缺失如实为 "--" |
| direction | "buy" | 本期仅买入草案 |
| entry | float | FR-2 |
| stopAtr / stopMa20 | float \| null | FR-3；**bars 不足时为 null，绝不造数** |
| stop | float \| null | 按 stopMode 选定值；两种都缺 → null |
| target | float \| null | FR-4；stop 为 null → null |
| stopDistance | float \| null | entry − stop |
| atr14 / ma20 | float \| null | 展示用原始指标值 |
| riskAmount | float \| null | FR-5 |
| suggestedShares | int | FR-5/6（0 = 资金不足） |
| positionPct | float | 建议仓位占权益 %（shares=0 → 0） |
| referenceDate | str | 指标锚定的已收盘交易日（YYYY-MM-DD） |
| entryAsOf | int \| null | 入场价快照时间戳（epoch 毫秒，请求透传或后端拉取时刻；评审决议） |
| stale | bool | 入场价快照过旧（age > 60s）或时间未知时为 true（§7） |
| fallbackUsed | bool | Router 降级到备用源时 true（对话框小黄标提示；二轮评审加固） |
| provider | str | 行情 / 历史源 provider_label |
| warnings | str[] | 见 §7，非阻断提示 |
| disclaimer | str | FR-9 固定文案 |

**错误**：`422 VALIDATION_ERROR`（代码无法分类 / 停牌股 / 参数越界）；`429 RATE_LIMITED`（限频超限，携带 Retry-After，见 §4.2）；`502 UPSTREAM_UNAVAILABLE`（行情或历史拉取失败且无过期缓存可兜底，**不返回造数草案**——指令草案对数据新鲜度的要求高于选股展示）。

### 4.2 限频护栏（评审加固）

`POST /api/assist/plan-draft` 施加**用户级滑窗限频：30 次/分钟**（单用户本地部署即进程级）。
理由：草案是交互调参场景（反复改盈亏比重算），10 次/min 会误伤正常使用；30/min 仍将失控
前端循环压至 0.5 req/s，较数据源底层 ≥10 req/s 的承受能力留 20 倍边际。超限返回
`429` + `Retry-After`。实现为进程内滑动窗口（与单进程现实一致；Redis 接管属 P2 数据中台项，
不在本 feature 引入）。**已知限制：多进程部署（多 uvicorn worker）下限频为近似值
（实际配额 = worker 数 × 30）；单用户本地部署单进程内精确，ROADMAP 收尾时如实标注。**

## 5. 数据需求与无未来函数纪律

- **指标数据**：经 Router（`historySource` + 降级）拉取 `limit=62` 根日线，**截断至 `reference_date` = 上一交易日**（复用 screener pipeline 的截断规则，实现时抽公共 helper 避免两份拷贝）。ATR14 需 ≥15 根、MA20 需 ≥20 根，否则对应字段 null + warning。
- **入场价**：实时快照（当下决策，用当下信息，合法无偏）；指标锚定已收盘数据。响应同时携带 `referenceDate` 标注，延续双时间戳透明原则。
- **单票单次请求**：1 次 history（经限频 gate）+ 0~1 次实时（命中行已带价则 0 次），目标 P95 < 1s。

## 6. 设置项新增（workspace settings）

| 键 | 类型 / 默认 | 约束 |
|---|---|---|
| `riskPerTradePct` | float，1.0 | 0.1–5 |
| `rrRatio` | float，2.0 | 1–10 |
| `stopMode` | "atr" \| "ma20"，"atr" | 白名单校验 |
| `positionCapPct` | float，25 | 5–100 |

账户权益**复用既有 `defaultCapital`**（storage.py 已存在，默认 100000，语义即账户权益；避免两个"资金"设置项）。`_normalize_workspace_settings` 扩展校验（越界回退默认值，模式同现有 source 校验）；设置页「交易辅助」分区展示。

## 7. 边界与降级（绝不造数纪律的延续）

| 场景 | 行为 |
|---|---|
| 停牌 / price 为 None / volume=0 | 422，拒绝生成买入草案 |
| bars < 15 | stopAtr=null；bars < 20 → stopMa20=null；均缺 → stop/target=null，前端允许手填止损 |
| 资金不足一手 | shares=0 + warning「权益不足一手，无法按该风险比例建仓」 |
| 单票超 positionCapPct | 截断手数 + warning |
| 涨跌停提示 | `classify_code` 板块涨幅上限（10/20/30%）：target 距 entry 超单日上限 → warning「目标位需多日达成」（不阻断） |
| T+1 | warning「A 股 T+1：当日买入次交易日方可卖出，止损自次一交易日生效」 |
| 入场价快照过旧 / 时间未知 | `entryAsOfMs` 距今 > 60s → `stale=true` + warning「入场价为过期快照，请核实现价」；缺失 → `stale=true` + warning「入场价快照时间未知」。**主路径前端带价，后端不调实时接口**（v0.5.0 Router 适配器无 stale-aside 缓存，502 硬失败语义保持诚实；Redis 缓存接管属 P2） |
| 触及涨停价 | entry ≥ round(截断末根收盘 × (1+`price_limit_ratio`), 2) → warning「当前价格触及涨停，实际成交可能存在风险」（不阻断；ETF 同样适用，主板 10%/创科 20%/北交 30%） |
| Router 降级 | 实际路由源 ≠ 设置首选源 → `fallbackUsed=true` + 前端小黄标「当前行情源自备用节点，数据延迟可能略高」（日志记录 fallback 事件；二轮评审加固） |

## 8. 前端交互（Vue 3 + Pinia）

- **入口**：① `ViewScreener` 策略 tab 命中行操作列加「草案」「回测」两按钮（现有操作列已含自选星标）；② 个股详情页「生成计划草案」。
- **草案对话框**：预填 FR-2~6 全部字段（均可编辑）+ warnings 列表 + FR-7 Kelly 折叠参考区 + disclaimer；确认后经 `usePlansStore` 追加计划（走 `PUT /api/workspace`）→ toast 确认。
- **提交防抖与 409（评审加固）**：确认按钮提交期间禁用（single-flight，杜绝双击双计划）；409 时**不自动重试**（遵守 AGENTS 修订锁约定）：保留对话框全部已填值，显式 toast「工作区有新变更，请刷新后重试」，由用户手动再次确认。已核实隐患：默认 conflictPolicy=server 下 `adoptServerSnapshot` 会以服务器快照覆盖本地，草案若不保留将静默丢失。
- **回测联动**：复用现有 `quotes.selectedCode` + 视图切换机制预填，不新增 API。
- **新 store 状态**：`useAssistStore`（draft、loading、error）或并入 `usePlansStore`——plans 阶段定。

## 9. 验收标准（节选，全部可自动化）

1. 单调下跌 30 根 bars + entry=10 → `stopAtr ≈ entry − 2×ATR14`（与 `indicators.atr` 直算一致，误差 <1e-6）
2. bars 混入未来日期 → 指标与仅用历史数据一致（无未来函数）
3. equity=100000、riskPct=1、stopDistance=1.0 → shares=1000（整手）；equity=9000 → shares=0 + warning
4. shares×entry 超 cap → 截断 + warning
5. 停牌股 → 422；bars=10 → stopAtr/stopMa20 均 null 且 target=null
6. target 距 entry 超 10%（主板）→ warning 含「多日」
7. 无效 rrRatio=15 → 422；上游行情失败且无过期缓存 → 502 且响应无造数
8. 限频：61 秒内第 31 次请求 → 429 + Retry-After
9. stale 快照：fetch 失败 + 缓存存在 → 草案正常返回且 stale=true + warning 含「过期快照」
10. 前端：草案确认后 `workspace.plans` 增加一条 direction=buy 计划且走 PUT（修订锁语义不变）；双击确认仅产生一条计划；409 后对话框值保留且 toast 提示刷新重试；「回测」跳转后回测表单 code 已预填

## 10. 测试策略

后端 TDD（计算精度 / 截断 / 边界 / 422/429/502，mock Router 与行情，模式同 screener-pipeline）；前端 vitest（对话框预填 / 提交走 workspace PUT / 双击去重 / 409 保留 / 回测跳转预填）；`npm run verify` 全量门禁；观测沿用结构化日志（trace_id + 耗时），一次性单票计算不设缓存，但设限频护栏（§4.2）。

## 11. 评审决议（2026-09-04，已定夺）

| 开放问题 | 决议 |
|---|---|
| 1. entry 默认价 | **实时快照价**——当下决策用当下信息；快照时间戳 `entryAsOf` 随草案返回，便于追溯 |
| 2. 止损默认模式 | **默认 ATR**（动态适应波动率，避免 MA20 震荡市反复穿越止损）；MA20 保留为备选可切 |
| 3. 写入路径 | **草案无状态 + 写入统一走 workspace PUT 修订锁**——绝不开后端直落计划路径（高并发下唯一正确解） |
| 4. 个股详情入口 | **纳入本期**（J3） |

评审加固项（FR-10 限频 / stale 透传 / FR-12 防抖 409）已并入 §4.2、§7、§8、§9——其中两处经代码核实做了修正：限频取 30 次/min（交互调参场景，10/min 会误伤）；不新增 Redis 快照缓存层（现有 `data_source.cached()` 已含 stale-aside，缺口仅在透传，Redis 接管属 P2）。
