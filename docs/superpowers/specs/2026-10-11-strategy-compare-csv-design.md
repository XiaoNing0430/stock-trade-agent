# 多策略回测对比 + CSV 导出 — 设计 Spec

- **日期：** 2026-10-11
- **状态：** 待用户复审（复审通过前禁止开发）
- **规划来源：** ROADMAP.md「研究体验」P3 项「多策略回测对比 + CSV 导出」
- **计划分支：** `feature/strategy-compare-csv-export`（Git Flow，spec 与实现同分支）

## 1. 背景与目标

策略实验室（ViewGrid）当前一次只能看**一种**策略类型对**一只**标的的回测结果。「多策略回测对比」补上研究闭环的关键一环：**同一只股票、同一份历史、同一套指标下，横向比较多个策略类型谁表现更好**；以及把已保存的网格/普通策略的回测成绩拉到同一张表里存档分析。

对比结果可导出 CSV（指标表 / 权益曲线 / 成交明细），供 Excel 二次分析与存档。

**已裁定的产品决策（2026-10-11 用户确认）：**

1. 对比对象**两者都要**：① 同标的多策略类型横向对比（核心）；② 已保存策略对比。
2. 已保存策略对比：**快照为默认（零成本读 `latestMetrics`），可一键现跑刷新**。
3. CSV 为**全套**：指标对比表 + 归一化权益曲线 + 成交明细。
4. 入口：ViewGrid 现有策略类型 tab 栏末尾新增**「对比」tab**，不新增导航视图。
5. 技术形态：**方案 A** —— 后端统一对比端点（一次取数、同 bars 重放）+ 前端客户端 CSV 生成（复用选股器导出先例）。

## 2. 非目标

- 对比结果**不落库**、不持久化、不进任何新表（刷新即失；存档走 CSV）。
- 已保存策略 rerun **不更新** `latest_metrics` / `last_backtest_at`、**不调度**（对比是只读研究动作；刷新快照请到单策略页跑一次保存）。
- 已保存策略对比**不叠曲线**（各策略标的/日期轴不同，叠加无意义；rerun 响应亦不含曲线字段）。
- 不做多策略组合回测（资金分配/组合权重）——那是另一个功能。
- 不改既有 `/api/grid/backtest` / `/api/strategy/backtest` 的行为与契约（含其 trades `-100` 截断）。
- 不做多语言/主题（ROADMAP 另一项）。

## 3. 后端设计

### 3.1 `POST /api/strategy/compare` — 同标的横向对比

请求模型 `CompareRunIn`：

| 字段 | 类型 | 校验 |
|---|---|---|
| `code` | str | 必填；走 `classify_code`（非法代码由现有分类逻辑报中文错误） |
| `lookback` | int | 服务端 clamp 20..240（与现有回测端点一致） |
| `capital` | float | > 0，否则 422 中文 |
| `feeBps` | float | ≥ 0，否则 422 中文 |
| `strategyTypes` | list[str] | **白名单 = `{"grid"} ∪ STRATEGY_ENGINES.keys()`**；非空、≤ 8；**先去重保序再校验**（重复项不报错）；未知值 422 中文（对齐自定义策略白名单纪律——这些字段写错会静默失效，必须挡在入口） |

流程：

1. `classify_code(code)` → profile（securityType/exchange/涨跌幅限制沿用现有规则）。
2. `_load_history_with_fallback(code, lookback)` **仅调用 1 次**——全部策略共享同一份 bars（live 成功时按既有行为落 `market_bars` 历史缓存，与单策略回测端点一致；除此之外零写库）。
3. 对每个勾选类型在同一份 bars 上回测：
   - **grid**：`suggest_grid(history, grid_count=8, capital, mode="classic")` 自动建议区间 → `backtest_grid(...)`（`priceLimitPct` 按 `classify_code` 现有规则）。
   - **7 个引擎**：从 `STRATEGY_ENGINES[type]["configSchema"]` 的 `default` 补齐默认参数（复用 `/api/strategy/preview` 现行补齐逻辑）+ 公共 `capital` / `feeBps` / `securityType` / `exchange` / `lookback` / `capitalAllocation=1.0` → `engine["backtest"](history, config)`。
4. **单策略异常不拖垮整单**：某类型回测抛错 → 该项置 `{strategyType, label, error: "中文短句"}`，其余照常，HTTP 仍 200。

响应模型 `CompareRunOut`：

```
{
  "code": "...", "profile": {...},
  "dataSource": "live" | "local",
  "dataAsOf": "...",
  "barCount": 120,
  "benchmarkCurve": [{"date": "...", "equity": 1.0}, ...],   # 顶层仅一份（同 bars 同 capital 同费率，基准对所有策略相同）
  "results": [
    {
      "strategyType": "grid" | 引擎 id,
      "label": "网格" | 引擎中文 label,
      "config": {...实际生效参数...},
      "metrics": {...与现有 metrics 同构...},
      "equityCurve": [{"date", "equity"}, ...],   # 归一化净值
      "trades": [...全量，不截断...],
      "assumptions": "...",
      "error": null
    },
    { "strategyType": "macd", "label": "MACD", "error": "回测失败：...", ... 其余键缺省 }
  ]
}
```

**trades 不截断**：bars ≤ 240 决定单策略成交天然有界（每日最多买+卖各一笔 ≈ 480 笔），8 策略最坏响应约数百 KB，本地单用户可接受。这是对比端点与单策略端点（截断最近 100 笔）的**有意差异**——成交明细 CSV 必须完整。

### 3.2 `POST /api/strategy/compare-saved` — 已保存策略对比

请求模型 `CompareSavedIn`：`{ "mode": "snapshot" | "rerun", "ids": [...] }`，`ids` 非空、≤ 10；`workspace` Query 参数默认 `"default"`（与既有端点一致）。

**snapshot（默认模式）— 纯读库：**

按 ids 查 `grid_strategies` 与 `strategies` 两表（≤ 10 次单查，无需新 storage helper），每项返回：

```
{
  "id": "...", "found": true,
  "source": "grid" | "strategy",
  "name": "...", "strategyType": "grid" | 引擎 id,
  "code": "...", "status": "启用" | "暂停", "schedule": "...",
  "capital": ..., "feeBps": ...,
  "lastBacktestAt": "...", "latestMetrics": {...} | null
}
```

三种缺失**逐项如实披露**，绝不静默丢行：

- id 不存在/已删除，或不属于该 workspace → `{ "id": "...", "found": false, "missingReason": "不存在或不属于当前工作区" }`
- 从未回测 → `found: true` + `latestMetrics: null` + `missingReason: "从未回测"`（指标表该行显示 `--`）。

**rerun 模式 — 现跑回测：**

- 对每个 id 按其**保存的参数**在其**各自的 code** 上回测：网格用已保存的 `lower/upper/gridCount/mode/capital/feeBps/settlementDays/slippageBps/lookback`（`priceLimitPct` 按 `classify_code(code)` 现算）；引擎策略用保存的 `config`（含 capital/feeBps/lookback）。
- 历史取数逐个串行走 `_load_history_with_fallback`（天然吃既有 source 节流/熔断/降级链）；live 成功落 `market_bars` 同上。
- 响应每项：`{id, name, source, strategyType, code, config, metrics, trades(全量), assumptions, error?}`——**不含 `equityCurve`/`benchmarkCurve`**（不同标的日期轴不同，叠加无意义；如需单策略曲线去详情页）。
- 单策略失败（取数失败/回测异常）逐项披露 `error`，不整单失败。
- **零副作用**：不写 `strategy_backtests`/`grid_backtests`、不更新 `latest_metrics`、不调度。

`CompareSavedOut` 顶层：`{ "rerun": true|false, "results": [...] }`。

### 3.3 对比口径与公平性声明（写入 UI 脚注与响应披露）

- 同标的对比：全部策略共享同一份 bars、同一 `capital`/`feeBps`/窗口/费率规则 → 指标可比。
- **网格参数是样本内自动建议**（用全窗口 bars 拟合区间，存在参数过拟合偏乐观），引擎默认参数是固定值 → 口径差异在对比结果脚注与 `assumptions` 中如实披露，不宣称「完全公平」。
- 定投（DCA）与网格的 `metrics` 同构（共用 `_compute_metrics`），可同表比较；但 DCA 的资金语义是「每期投入 + 止盈止损全平」，其 `excessReturnPct` 分母与全仓策略含义不同，脚注一并披露。

### 3.4 资源上界 / 并发 / 竞态

- 勾选上界：`strategyTypes` ≤ 8（= 全集，天然封顶）、`ids` ≤ 10；越界 422 中文。
- `lookback` clamp 20..240；`capital`/`feeBps` 数值校验如上表。
- 对比为纯 CPU 计算（240 bars × 8 策略，毫秒级），**无锁需求**；上游取数复用既有节流/熔断/降级护栏。
- 端点无服务端状态（零写库），单用户本地单进程下无竞态面。
- 响应体积上界见 §3.1；不引入分页/流式。

### 3.5 错误契约

- 全部走 `api_error(...)` → `{"detail": {"error": 中文短句, "code": 机器码}}`（2026-10-03 统一契约）。
- 参数校验失败：422 `VALIDATION_ERROR`。
- 整体失败（如 `_load_history_with_fallback` 上游与本地均不可用）：**与既有回测端点对齐，422 + 上游中文错误**。
- 部分策略失败**不是端点失败**：per-item `error` 字段，HTTP 200。
- 新机器码不新增（复用 `VALIDATION_ERROR`）；Pydantic 请求模型校验失败由 app 级 `RequestValidationError` handler 统一转中文契约。

### 3.6 `backend/schemas.py` 新增模型

`CompareRunIn` / `CompareRunOut`、`CompareSavedIn` / `CompareSavedOut`（Pydantic v2，与既有 `GridBacktestIn/Out`、`StrategyBacktestIn/Out` 命名风格一致）。响应模型对 results 内可选键（metrics/trades/…）用 `dict[str, Any] | None` 容纳 error 行。

## 4. 前端设计

### 4.1 入口与布局（ViewGrid.vue）

- `STRATEGY_TYPES` 末尾新增 `{ id: 'compare', label: '对比' }`（lucide 图标 `git-compare`）；`switchStrategyType` / `strategyTypeLabel` 相应适配。
- 对比 tab 内上下两个区块：

**区块 1 — 同标的横向对比**

- 参数表单：代码 / 历史窗口（60/120/240）/ 投入资金 / 双边费率（复用现有 `field` 样式与数值语义）。
- 策略类型勾选：8 个 checkbox（网格 + 7 引擎），默认全选；运行前至少勾 1 个，前端中文内联提示。
- 「运行对比」按钮（loading 态禁用，复用 `draft-status` 文案）。
- 结果区：
  - provenance 行：`dataSource`（live/local 中文文案）+ `dataAsOf` + `barCount`；
  - **指标对比表**（`data-table`）：行 = 策略，核心列 = 区间收益 / 年化收益 / 超额收益 / 最大回撤 / 夏普 / 胜率 / 成交次数 / 总费用；**每列最优值高亮**（收益/超额/夏普取最大，回撤取最小；null 不参与不高亮）；error 行整行显示「失败：原因」；
  - **归一化净值叠图**：复用 `multiLineSvg`（`chart.ts` 现成：任意条数系列 + 图例 + null 断线 + escapeHtml 纪律），各策略实线 + 基准灰虚线；
  - assumptions 脚注：逐策略小字列出；
  - 三个导出按钮（见 §5）。

**区块 2 — 已保存策略对比**

- 合并列出网格策略 + 普通策略（复用 `strategy-row` 样式 + checkbox 前缀），显示名称/类型/代码/最近回测时间；全选/清空快捷按钮；已选计数 `x/10`，超选禁用。
- 「对比快照」按钮（snapshot，默认）与「重新回测并对比」按钮（rerun）并列；rerun 按钮旁小字注明「仅对比，不更新已存快照」。
- 结果：指标对比表（同上，无叠图）；error/缺失行如实披露（`不存在或不属于当前工作区` / `从未回测` / `失败：原因`）。
- 空态：无任何已保存策略时空态文案「暂无已保存策略，先到上方运行并保存」。

### 4.2 `useCompareStore.ts`（第 13 个 Pinia store）

- state：`runLoading` / `runResult: CompareRunOut | null` / `selectedTypes: string[]`（默认全部 8 个）/ `savedLoading` / `savedResult: CompareSavedOut | null` / `savedSelection: string[]`。
- actions：`runCompare()`、`compareSaved(mode)`、`exportRunCsv(kind)` / `exportSavedCsv(kind)`（kind ∈ `metrics | curves | trades`，委托 §5 构建器 + `downloadCsv`，成功 toast）。
- 422/5xx → 中文 toast（沿用 `client.ts` + `showToast(textContent)` 纪律）。
- 对比结果纯内存，不持久化；切换 tab/刷新即失（与 §2 非目标一致）。

### 4.3 `frontend/src/modules/csv.ts`（新模块）

- `csvCell(value: unknown): string` — **CSV 公式注入防护**：`null/undefined` → `''`；字符串且匹配 `/^[=+\-@\t\r]/` → 前缀 `'`（Excel 公式注入标准缓解）；数字/布尔 → `String(value)`（数字不防护，负数正常）；其他 → `String(value)` 后同规则。
- `buildCsv(headers: string[], rows: unknown[][]): string` — 单元格 `csvCell` → `,` join → 行 `\n` join（与选股器导出先例一致）。
- `downloadCsv(filename: string, csv: string): void` — `\ufeff` BOM + `Blob`（`text/csv;charset=utf-8;`）+ `a[download]` 点击 + `revokeObjectURL`（照抄 `useScreenerStore.exportCsv` 先例）。
- 三个组装器：
  - `buildCompareMetricsCsv(rows: CompareCsvRow[])` — 行 = 策略；列 = 策略名 / 来源或类型 / 参数摘要 + **全部 metrics 键**（中文表头映射见 §6）。参数摘要为人类可读关键键值串：grid → `8格 · 0.97-1.13 · classic`；引擎 → `fastPeriod=5, slowPeriod=20`（取 config 全部键按插入序拼接）；
  - `buildCompareCurvesCsv(runOut: CompareRunOut)` — **宽表**：`日期` + 每策略一列（`{label} 净值`）+ `基准净值`（仅同标的模式有此导出；error 策略无曲线则整列省略）；
  - `buildCompareTradesCsv(rows)` — **长表**：`策略 / 日期 / 方向 / 触发价 / 成交价 / 股数 / 费用 / 模块`（grid 无模块 → 空格；引擎 `triggerPrice` 为 null → 空格）。
- 文件名：`atlas-compare-metrics-<ts>.csv` / `atlas-compare-curves-<ts>.csv` / `atlas-compare-trades-<ts>.csv`（`<ts>` = `Date.now()`，先例一致）。

### 4.4 XSS 纪律

- 策略名 / label / error 文案进 DOM 一律 Vue 插值（自动转义）；进 SVG 图例走 `multiLineSvg` 内建 `escapeHtml`；toast 保持 `textContent`；CSV 文件内容本身经 `csvCell` 防公式注入。新增代码不引入 `v-html`。

## 5. CSV 导出规格汇总

| 模式 | 指标表 | 权益曲线 | 成交明细 |
|---|---|---|---|
| 同标的对比 | ✅ | ✅（宽表，含基准列） | ✅ |
| 已保存 snapshot | ✅（latestMetrics） | ❌ | ❌（快照无成交数据） |
| 已保存 rerun | ✅（本次现跑） | ❌ | ✅ |

三个按钮独立触发三张 CSV（不做「一次三连下载」——浏览器会拦截多文件连下，独立按钮交互最清晰且可按需取用）。

## 6. 指标中文表头映射（CSV 用，全集）

`returnPct`→区间收益% · `annualizedReturnPct`→年化收益% · `benchmarkReturnPct`→基准收益% · `excessReturnPct`→超额收益% · `maxDrawdownPct`→最大回撤% · `maxDrawdownDurationDays`→最长回撤天数 · `annualizedVolatilityPct`→年化波动% · `sharpeRatio`→夏普比率 · `winRatePct`→胜率% · `profitFactor`→利润因子 · `avgGridReturnPct`→单格平均收益% · `medianGridReturnPct`→单格收益中位% · `tradeCount`→成交次数 · `buyCount`→买入次数 · `sellCount`→卖出次数 · `totalFees`→总费用 · `turnoverMultiple`→换手倍数 · `startEquity`→期初权益 · `endEquity`→期末权益 · `skippedLimitUpDays`→涨停跳过天数 · `skippedLimitDownDays`→跌停跳过天数 · `skippedSuspensionDays`→停牌天数 · `onePriceLimitUpDays`→一字涨停天数 · `onePriceLimitDownDays`→一字跌停天数

null 值 → 空单元格；列顺序按上表固定。

## 7. 测试计划

### 后端 `tests/test_strategy_compare.py`（monkeypatch 离线，conftest 纪律）

1. **compare 成功**：8 类型全跑 → `results` 长度/键齐全；顶层 `benchmarkCurve` 存在且各策略共享；grid 行 `config` 含 `lower/upper/gridCount`（自动建议生效）；引擎行 `config` 含 schema 默认参数。
2. **校验矩阵**：白名单外 422 中文；空数组 / > 8 / `capital ≤ 0` 422；重复类型去重生效（不 422）；`lookback` 500 → clamp 后 `barCount ≤ 240`。
3. **部分失败**：monkeypatch 某引擎 `backtest` 抛错 → 该行 `error` 中文、HTTP 200、其余正常。
4. **trades 不截断**：monkeypatch 引擎返回 > 100 笔 → 响应全量返回（验证端点不做 `[-100:]`）。
5. **compare-saved snapshot**：seed 网格 + 普通策略各一行（含/缺 `latest_metrics`）、失效 id、跨 workspace id → `found` / `missingReason` / `latestMetrics: null` 逐项如实。
6. **compare-saved rerun**：seed 策略，monkeypatch 历史取数返回固定 bars → 断言 `metrics`/`trades` 返回、**无曲线字段**、且 `strategy_backtests` / `grid_backtests` 行数与 `latest_metrics` 均不变（**零写库断言**）；单策略失败逐项披露。

### 前端 vitest（3 个新文件）

1. `csv.test.ts`（modules）：`csvCell` 注入矩阵（`=` `+` `-` `@` `\t` `\r` 开头加 `'`；正常文本/数字/null 不动）；`buildCsv` join 行为；三个组装器的列数/表头/宽长表形状；`downloadCsv` Blob 参数与文件名（mock URL/createObjectURL）。
2. `useCompareStore.test.ts`：默认勾选 8 类型；`runCompare` 成功组装与 422 toast；导出委托（mock `downloadCsv`）。
3. ViewGrid 对比 tab 冒烟：tab 切换渲染 8 个 checkbox；结果表行数与高亮 class；error 行渲染；叠图图例存在（multiLineSvg 输出注入）。

### 文档收口（实现完成时）

- `AGENTS.md`：views/描述更新（对比 tab）、stores 计数 12→13、模块清单加 `csv.ts`、测试文件与计数更新。
- `ROADMAP.md`：勾选该项并留交付摘要。
- `CHANGELOG.md`：下一版本条目。

## 8. 已知限制（如实披露）

- 网格区间为样本内自动建议，结果偏乐观（UI 脚注 + `assumptions` 披露）。
- 对比结果纯内存不落库，刷新即失；存档走 CSV。
- rerun 不更新 `latest_metrics` / `last_backtest_at`（有意为之，见 §2）。
- snapshot 模式无成交明细可导（快照只有 metrics）。
- rerun 响应不含权益曲线（不同标的日期轴不同，叠加无意义）。
- live 历史取数按既有行为写 `market_bars` 历史缓存（与单策略回测端点一致，非对比功能新增写路径）。
- compare 响应最坏约数百 KB（8 策略 × ~480 笔全量 trades），本地单用户可接受。

## 9. 验收清单

- [ ] `npm run verify` 全绿（后端新增 ≥ 6 类用例、前端新增 3 文件）。
- [ ] compare 端点一次上游取数（无 N 倍放大——代码审查项）。
- [ ] compare-saved rerun 零写库断言在测试中成立。
- [ ] CSV 公式注入防护有测试覆盖。
- [ ] 白名单/上界 422 中文有测试覆盖。
- [ ] UI 中文文案、`--` 空值、error 行如实披露。
- [ ] Git Flow feature 分支全流程，AGENTS/ROADMAP/CHANGELOG 收口。
