# 真实执行台账（成交 / 资金流水 / 持仓 / 真实 NAV）— spec r1

日期：2026-10-25 ｜ 状态：r1 待用户复审（复审通过前不开发）

## 定位与验收标准

本设计的验收标准 = **单用户本地工具**（与 `ROADMAP.md` 非目标红线一致）。红线不变：
**不连接券商、不自动下单、不导入交割单**；所有成交与出入金由用户人工录入，系统只做记账、推导与对账。

本批要解决的产品缺口：现有复盘与组合风险都写明「设计口径回放，不代表实际成交（无成交记录）」，
工具因此无法回答「我这套打法**实际**赚不赚钱」。本设计补上「研究 → 计划 → 实际执行 → 真实绩效」的最后一段。

## 冻结决策

- **范围（用户裁定）**：全量四层——成交台账与持仓 → 资金流水与真实 NAV → 复盘「实际 vs 计划」对账 → 组合风险真实口径。
- **价格口径（用户裁定）**：**双轨**。收益/净值曲线用「真实成交价 × 前复权收益率」推进（总收益口径，分红拆股隐含，
  与现有回测/复盘一致）；持仓市值/浮动盈亏用「实时不复权价 + 真实成交价」，UI 明示两种口径。
- **录入粒度（用户裁定）**：**全开放**——支持无计划的自由成交、同一计划分批成交、部分卖出；费用手填总额，
  另给「按费率估算」按钮只填建议值、不自动覆盖。
- **交易规则（用户裁定）**：按 A 股真实规则校验（见 §3 规则表）。
- **作废（用户裁定）**：**保留审计**——作废写 `voided_at`/`void_reason`，不参与派生，列表灰显，**不可恢复**（重新录一笔即可）。
- **存储形态**：独立表 + 独立端点，**绝不并入 workspace 全量同步**。workspace PUT 是「不在 payload 里就删」的快照语义，
  真实资金记录不能因一次陈旧 PUT 消失。
- **派生量不落库**：持仓、现金、NAV 全部由成交与流水重放得到（纯函数），避免第二份事实源。
- **默认口径不变**：`/api/portfolio/risk` 默认仍 `virtual`；`/api/plans/review` 旧字段一字不改，只新增 `actual` 块。
- **不造数**：行情缺失、复权基准缺失、初始资金未设时，一律如实披露并给 `--`，不插值、不猜。

## 1. 数据模型

### 1.1 `trade_fills`（成交，Alembic 前向迁移）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | String(64) PK | 客户端生成（`fill_<hex>`），幂等重试沿用 |
| `client_request_id` | String(64) 唯一可空 | 防重复提交双写；重复提交返回既有记录（幂等，不报冲突） |
| `workspace_id` | String(64) index，默认 `default` | 与既有表一致 |
| `code` | String(32) index | 复用 `classify_code()` |
| `direction` | String(8) | `buy` / `sell`（DB CheckConstraint 兜底） |
| `price` | Float | 成交价，> 0 |
| `qty` | Integer | 股/份，> 0（DB CheckConstraint 兜底） |
| `fee` | Float 默认 0 | **手填总费用**（佣金+印花税+过户费），≥ 0 |
| `traded_at_ms` | BigInteger index | 成交时刻（毫秒 epoch；录入按上海时区解释）。**2026-10-25 实现更正**：原定 `DateTime(timezone)`，改为毫秒整数——与全仓 `createdAtMs` 约定一致，且 SQLite 测试库/PostgreSQL 行为逐字相同、排序无时区陷阱 |
| `plan_id` | String(96) 可空 index | 关联计划；**不加外键**（计划随 workspace 快照增删，与既有 `related_plan` 同风格） |
| `note` | String(500) 默认 '' | 备注 |
| `voided_at_ms` | BigInteger 可空 | 作废时间（毫秒 epoch） |
| `void_reason` | String(200) 可空 | 作废原因 |
| `created_at_ms` / `updated_at_ms` | BigInteger | 重放次序的第二排序键（`(traded_at_ms, created_at_ms, id)`），**同日多笔不靠 DB 时间戳** |

索引：`(workspace_id, code, traded_at_ms)`、`(plan_id)`、`UNIQUE(client_request_id)`。DB 兜底约束：`qty > 0`、`direction IN ('buy','sell')`。

### 1.2 `cash_flows`（出入金）

| 列 | 类型 | 说明 |
| --- | --- | --- |
| `id` | String(64) PK | `cf_<hex>` |
| `client_request_id` | String(64) 唯一可空 | 同上 |
| `workspace_id` | String(64) index | 同上 |
| `amount` | Float | **正=入金，负=出金**，≠ 0 |
| `occurred_at_ms` | BigInteger index | 发生时刻（毫秒 epoch，同 fills 口径） |
| `note` | String(200) 默认 '' | 备注 |
| `voided_at_ms` / `void_reason` | 同上 | 作废保留审计 |
| `created_at_ms` / `updated_at_ms` | BigInteger | 同上 |

### 1.3 设置

初始资金进既有 `workspace_settings.data.initial_capital`（JSON 列，**无需迁移**），默认 `0`。
未设置（=0）且已有成交时：现金为负 → 面板黄标「未设初始资金或漏录入金」，NAV 曲线返回 `NAV_UNAVAILABLE`。

## 2. 派生口径：持仓、成本、已实现盈亏

按 `(traded_at, created_at)` 升序重放未作废成交（同日多笔按录入顺序）：

- **买入**：`qty += q`；`cost_basis += q × price + fee`（**买入费用计入成本**，摊薄口径）；
  `avg_cost = cost_basis / qty`。
- **卖出**：`realized += q × (price − avg_cost) − fee`；`cost_basis -= q × avg_cost`；`qty -= q`（`avg_cost` 不变）。
- **清仓**（`qty` 归零）时把残留浮点尾差归零（`|qty| < 1e-9`），不做四舍五入到价格。
- **硬约束**：`q > 可用持仓` → 422 `SELL_EXCEEDS_POSITION`（中文文案给出可用数量），**绝不允许负持仓**。
- **现金**：`initial + Σ入金 − Σ出金 − Σ(买入额+费) + Σ(卖出额−费)`；为负只警示，不阻断。

## 3. 交易规则校验（A 股真实规则）

买入单位/递增与零股卖出规则（来源：证监会投教与交易所规则，2026-10 核实）：

| 板块（`classify_code().board`） | 买入最小 | 递增单位 | 卖出余额不足一单位 |
| --- | --- | --- | --- |
| 沪深主板（`6xxxxx`/`0xxxxx`/`3xxxxx` 除外创业板） | 100 股 | 100 股整数倍 | 须一次性全部卖出 |
| 创业板（`30xxxx`） | 100 股 | 100 股整数倍 | 须一次性全部卖出 |
| 科创板（`688xxx`） | 200 股 | 超过 200 股按 **1 股** 递增 | 须一次性全部卖出 |
| 北交所（`4/8/92` 开头） | 100 股 | 超过 100 股按 **1 股** 递增 | 须一次性全部卖出 |

- **股票**（`securityType == "股票"`）：上表**硬校验**（422 `QTY_NOT_LOT`，中文文案直接给出该板块规则）。
- **ETF**：板块内品种申报单位差异大（货币/债券/跨境/科创 ETF 各不同，且系统无品种类型数据）
  → **软校验**（默认按 100 份整数倍检查，不符只回 `warnings[].code = LOT_WARNING`，不阻断），并在面板披露该限制。
- **T+1**：股票卖出数量 > 「该成交日之前（不含当日买入）的可用持仓」→ 422 `T1_VIOLATION`
  （文案：当日买入次日才可卖，请核对成交日期；零股清仓同样适用）。ETF **不判 T+1**（品种差异，披露）。
- **代码支持范围**：`securityType ∈ {股票, ETF}` 且板块非「未知」；其它（可转债等）→ 422 `CODE_UNSUPPORTED`，
  提示「该品种交易规则未建模」，**不猜规则**。
- **不做**：涨跌停/价格笼子/申报上限校验（成交是既成事实）；大宗交易与盘后固定价不单列。

## 4. 双轨数字与真实 NAV

### 4.1 持仓市值（账面口径）

`market_value = qty × 最新不复权价`（实时行情 `quotes`）；行情缺失 → `lastPrice = null`、`marketValue = null`、`--`，
并在 `disclosures` 写明缺哪些码。`unrealized = market_value − cost_basis`。

### 4.2 收益推进（总收益口径，用于 NAV）

对每笔未清仓的买入批次：`value_t = q₀ × price₀ × (bfq_t / bfq₀)`，其中 `bfq` 取 `market_bars` 的前复权收盘，
`bfq₀` = 成交日（无 bar 则取前一交易日）收盘。多批次求和即持仓「收益口径市值」。
- **批次扣减规则（消歧）**：卖出时按 `q_sell / q_总` **等比**从各未清仓批次扣减数量（与移动加权成本同一口径，
  避免「成本用均价、市值用 FIFO」两套账打架）。扣减后批次数量归零即移出。
- 卖出成交额按真实价进现金。
- 该口径把分红/拆股视为再投资 → 与券商账面市值必然分叉，UI 必须并列披露，不给单一数字。

### 4.3 现金与 NAV（单位净值法，剔除出入金影响）

- 出入金按**发生日前一日净值**折算份额：`units ±= amount / nav_prev`（`nav_prev` 首日为 1）；出金使 `units ≤ 0` → 422。
- `nav_t = (收益口径持仓市值_t + 现金_t) / units_t`；时间轴 = 成交日 ∪ 出入金日 ∪ **持仓码**在 `market_bars`
  有 bar 的交易日（并集升序）。全市场 ETL 的其它码不进入时间轴。
- bar 缺失的持仓沿用最近可得收盘（`staleDays` 披露），不插值；从未有过 bar 的码 → 该持仓不参与 NAV，
  并在 `disclosures` 点名（不猜价格）。
- 指标只给**区间收益**（`nav_last/nav_first − 1`）与**最大回撤**（`max(1 − nav_t/peak_t)`）；**不年化**（样本短必误导）。

### 4.4 已知偏差（写进 UI 脚注与响应 `disclosures`）

1. 前复权序列在除权后会整体改写 → 历史 NAV 曲线会随复权重算而变化（与 PIT 快照的「不可变」不同）。
2. 总收益口径把分红当再投资 → 净值与券商账户「现金+市值」不完全一致。
3. ETF 的 T+0/T+1 与申报单位未建模。

## 5. API 契约

沿用全仓错误契约 `{"detail": {"error": 中文, "code": 机器码}}`；写端点全部 `workspace_id='default'`。

| 端点 | 语义 |
| --- | --- |
| `GET /api/fills?code=&planId=&includeVoided=&limit=` | 台账（默认排除已作废，按 `traded_at` 倒序） |
| `POST /api/fills` | 新建。`id` 可省略（服务端生成 `fill_<uuid>`）；`clientRequestId` 命中既有记录 → 同 payload 返回该记录（200，幂等）；payload 不同 → 422 `IDEMPOTENCY_MISMATCH` |
| `PUT /api/fills/{id}` | 改正价格/数量/费用/时间/计划/备注（改后重新校验规则；已作废 → 422 `FILL_VOIDED`） |
| `POST /api/fills/{id}/void` | 作废（`{"reason": "..."}` 可选）；重复作废幂等返回当前状态 |
| `GET /api/cash-flows` / `POST /api/cash-flows` / `POST /api/cash-flows/{id}/void` | 出入金（同上；`PUT` 改正金额/时间/备注同 fills 语义） |
| `GET /api/positions` | 派生持仓 + 现金 + 合计 + `warnings[]` + `disclosures[]`（持仓码数量很小，行情总是拉取，不做开关） |
| `GET /api/account/nav?from=&to=` | NAV 曲线点 + 区间收益 + 最大回撤 + `disclosures[]`；不可算 → 422 `NAV_UNAVAILABLE`（中文说明缺什么） |

错误码：`VALIDATION_ERROR`（既有）、`FILL_NOT_FOUND`、`FILL_VOIDED`、`CASH_FLOW_NOT_FOUND`、`QTY_NOT_LOT`、
`SELL_EXCEEDS_POSITION`、`T1_VIOLATION`、`CODE_UNSUPPORTED`、`IDEMPOTENCY_MISMATCH`、`NAV_UNAVAILABLE`。
`POST/PUT /api/fills` 响应带 `warnings[]`（ETF 申报单位软校验、T+1 之外的提示等）。
`planId` **不校验计划是否存在**（计划可能已被删除，历史成交必须留得住），仅在响应里标 `planMissing: true`。

## 6. 复盘「实际 vs 计划」对账（`GET /api/plans/review` 只增字段）

新增 `actual` 块（旧字段零改动）：

- `byPlan[]`：`planId/code/direction/plannedQty（= 建议股数，复用 planMetrics 口径）/filledQty/execRate/
  avgFillPrice/slippagePct/realizedPnl/fillCount`。
  - `slippagePct = (avgFillPrice − plan.entry) / plan.entry`（buy 取正为不利；**sell 反向取负号**，统一为「正=不利」）。
- `summary`：`plansTriggered`、`plansFilled`、`execRate`、`abandonRate`（已触发但零成交/已触发）、
  `avgSlippagePct`、`sellCount`、`winRate`（盈利卖出笔/卖出笔）、`profitFactor`（总盈利/总亏损）。
- `unlinked`：未关联计划的自由成交单独一档（同指标）。
- 披露三条：胜率/盈亏比按**卖出笔**计（移动加权平均无法唯一配对持仓周期）；`slippagePct` 用成交加权均价；
  `plannedQty` 沿用既有 `planMetrics` 的 100 股整手口径（科创板/北交所建议股数可能偏小，属既有行为，本批不改）。

**不做**：「触发 → 成交延迟」（`trade_plans.triggered` 只有布尔，无时间戳，改结构代价大）。

## 7. 组合风险真实口径（`/api/portfolio/risk` 增 `source=actual`）

- 默认 `virtual`（既有 payload 与 679 项测试零改动）。
- `actual`：用真实成交重放（新纯函数 `replay_actual_positions`，复用同一批微结构与 NAV 组合逻辑），
  payload 形状与 virtual 一致，`meta.source='actual'`，并附 `meta.pendingPlansWithoutFills`（执行中计划里未录成交的份数）。
- **不混算**：actual 模式只含真实持仓，未录成交的计划不进仓、不猜；差异数量如实展示。
- **等价性验收（可判定）**：`replay_actual_positions` 与 M1/M2 的 `derive_positions` **共用同一重放内核**；
  用例对同一组成交断言「期末持仓（码/数量/成本）+ 现金 + 期末 NAV」逐项相等（浮点用 1e-9 容差），
  并断言 virtual 模式 payload 与既有快照逐字一致。

## 8. 前端落点（不动 `NAV_ITEMS` 顺序与数字键 1–7）

- **ViewPlans 新增面板「持仓与成交」**：持仓表（数量/摊薄成本/现价/浮动盈亏/已实现/权重）+ 成交台账（行内编辑、作废、灰显）
  + 录入对话框（方向/代码/价格/数量/费用/时间/关联计划/备注，含「按费率估算」按钮）+ CSV 导出（复用 `modules/csv.ts` 防公式注入）。
- **计划行「确认成交」**：预填代码/方向/计划入场价/建议股数，用户改实际价与数量后提交；成功后行内显示滑点角标。
- **设置页**：初始资金（≥0，为 0 时明确提示「未设置将无法计算真实净值」）。
- **组合风险视图**：顶部口径切换（虚拟回放 / 真实成交，默认虚拟），actual 时显示未录成交计划条数与披露。
- **复盘绩效面板**：真实口径与设计口径并列（滑点/执行率/放弃率/真实胜率），缺数据显 `--`。
- 新增 store `useLedgerStore`（fills/cashFlows/positions/nav 的拉取与本地缓存）；`usePlansStore` 只加「确认成交」桥接，
  不改变既有计划状态机。

## 9. 里程碑（每个独立可验收）

| M | 交付 | 验收标准 |
| --- | --- | --- |
| **M1** | 迁移（`trade_fills`）+ fills CRUD/作废/幂等 + 持仓与已实现盈亏派生 + 台账/持仓面板 + 计划确认成交 | 纯函数用例覆盖分批/部分卖出/零股/超卖/作废重放；API 201/200/422 中文；面板真实数据可读；既有 679 测试零改动 |
| **M2** | `cash_flows` + 现金 + 单位净值 NAV + 区间收益/最大回撤 + 初始资金设置 | 出入金份额法用例（含出金超额 422）；缺 bar/缺资金披露；NAV 不可算时 422 中文 |
| **M3** | 复盘 `actual` 块（执行率/滑点/放弃率/真实胜率/盈亏比）+ 前端并列展示 | 旧字段快照不变；滑点方向符号用例（buy/sell）；自由成交单独归口 |
| **M4** | 组合风险 `source=actual`（`replay_actual_positions`）+ 前端口径切换 | 默认 virtual payload 与既有测试逐字一致；actual 与引擎等价性用例；未录成交计划披露 |

## 10. 测试策略

- **纯函数矩阵**：板块规则（4 板 × 买/卖 × 零股）、ETF 软校验、T+1、加权成本、分批买入/部分卖出、
  作废后重放、幂等、现金为负、NAV 份额法（入金/出金/首日）、分红除权（构造 bfq 序列验证 NAV 不跳空）、缺失 bar、清仓浮点尾差。
- **API**：状态码 + 中文文案 + 错误码 + 幂等 + 校验矩阵（含越界/负数/非整数/未知代码/已作废改写）。
- **回归**：`/api/plans/review` 旧字段快照；`/api/portfolio/risk` 默认 virtual 逐字不变；pytest 全量 + 覆盖率门禁 ≥80%。
- **前端**：store CRUD、面板渲染（`--` 与披露）、录入校验拦截、CSV 注入防护、计划确认成交桥接。

## 11. 非目标

券商对接/自动下单、交割单导入或 OCR、分红税与融资融券、多账户与多币种、税务申报、
修改历史 PIT 快照、T+1 以外的停牌/涨跌停成交校验、触发到成交的延迟指标、年化收益口径、
并发编辑的乐观锁（单用户本地，`PUT` 末次写入生效）。
