# Atlas P0 可靠性修复设计

## 背景

六角色（UI / 产品经理 / 网站用户 / 量化交易员 / 架构师 / 资深开发工程师）头脑风暴确认了 5 个已核实的正确性与可靠性缺陷，以及一个废弃分支带来的双实现混淆源。本设计是分阶段推进方案（P0 修复 → P1 UX 落地 → P2 量化增强 → P3 架构工程）中的第一个子项目，只修正确性，不改产品行为。

## 目标

1. 恢复前端轮询并发守卫，消除慢网络下请求堆积。
2. 修复选股器涨跌幅排序对 0.00% 的错误处理。
3. 修复网格回测把"一字板"误判为停牌的问题，实现一字涨停/一字跌停/停牌三态。
4. 修正交易计划持久化文案失实。
5. 为 workspace 同步增加版本乐观锁，杜绝多标签页静默互相覆盖。
6. 删除已决定放弃的 `feature/unified-trading-desk` worktree 与分支。
7. 同步 AGENTS.md 中已失真或需要补充的约定。

## 非目标

- 不做任何 UX 改版（总览指挥台、手机导航、设置标签页属于 P1）。
- 不新增量化指标体系、不改回测模型参数（属于 P2）。
- 不引入前端测试框架（`node:test` 属于 P3）。
- 不接入券商、不扩候选池、不加新策略类型。
- 除本设计明确列出的字段外，不改动任何既有 API 字段名。

## 修复项设计

### 1. `refreshInFlight` 轮询守卫（frontend/app.js）

- 模块级（setup 作用域内）`refreshInFlight` 布尔标记。
- `refreshAll` 入口处：若 `refreshInFlight` 为真则直接返回；进入时置真，`finally` 中复位。
- 守卫只对定时轮询路径（`options.silent` 为真）生效；用户主动刷新（`scanNow`、`saveSettings` 后的 `refreshAll`）不受影响。
- 恢复后 AGENTS.md 中"`refreshAll()` guards against concurrent runs via `refreshInFlight`"的描述重新为真。

### 2. 选股器排序修复（backend/data_source.py）

- 现状：`rows.sort(key=lambda row: (row["change"] is not None, row["change"] or -999), reverse=True)`，`0.0` 为假值被替换为 `-999`，导致涨跌幅 0.00% 的股票排在负涨幅之后（已实测复现）。
- 修复：排序键第二项改为显式 None 判断 `row["change"] if row["change"] is not None else -999`。
- 排序语义不变：有涨跌幅者在前、按涨跌幅降序，无涨跌幅者殿后。

### 3. 一字板三态处理（backend/grid_strategy.py）

现状：`backtest_grid` 中 `if high <= low or (volume is not None and float(volume) <= 0)` 即整日跳过并计入 `skippedSuspensionDays`。一字板（开盘即封板、全天 `high == low` 且成交量大于 0）被误判为停牌，漏记了本可成交的委托，回测偏保守且 `skippedSuspensionDays` 失真。

修复后的日内三态：

1. **停牌**：`volume is not None and volume <= 0`。整日跳过，计入 `skippedSuspensionDays`（行为不变）。
2. **一字涨停**：非停牌且 `high == low` 且 `low >= previous_close * (1 + price_limit_pct) - 0.005`。允许卖出（在既有 `limit_down` 才禁卖的规则之外额外说明：此日买单清空），禁止买入。
3. **一字跌停**：非停牌且 `high == low` 且 `high <= previous_close * (1 - price_limit_pct) + 0.005`。允许买入，禁止卖出。

实现要点：

- 一字涨停日本身满足既有 `limit_up` 判定（买入清空）、一字跌停日满足既有 `limit_down` 判定（卖出清空），"涨停只可卖、跌停只可买"的语义由既有规则自然产生；本修复的唯一改动是这类日子不再整日 `continue`，让可成交的一侧正常触发。
- 修复点：停牌判定收窄为仅 `volume is not None and volume <= 0`，不再把 `high <= low` 当作停牌条件；执行价沿用现有滑点模型（触发价受当日 high/low 约束）。
- metrics 新增 `onePriceLimitUpDays`、`onePriceLimitDownDays` 两个计数字段（纯新增，不改既有字段）。
- `assumptions` 披露文案追加一句："一字涨停日仅可卖出、一字跌停日仅可买入，停牌日整日跳过。"

### 4. 持久化文案修正（frontend/index.html）

- "计划只保存在本地浏览器" 改为 "计划保存在本地浏览器与服务器，换设备打开自动同步"。

### 5. workspace 乐观锁（backend/storage.py + backend/app.py + frontend/app.js）

现状：workspace 同步是全量快照 PUT，无版本检测。两个标签页各自持有全量状态，后写覆盖先写，计划与提醒静默丢失。

设计：

- 新增表 `workspace_state(workspace_id VARCHAR(64) PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0, updated_at TIMESTAMPTZ)`，纳入 `initialize_storage()` 的 `CREATE TABLE IF NOT EXISTS` 前向迁移机制，不引入 Alembic。
- `GET /api/workspace` 响应新增 `revision` 字段（整数，从 0 开始）。
- `PUT /api/workspace` 接受可选查询参数 `baseRevision`（整数）与 `force`（布尔）：
  - 未提供 `baseRevision`：照常保存（兼容现有调用与首次写入），保存后 `revision += 1`；
  - 提供 `baseRevision` 且等于当前值：保存，`revision += 1`；
  - 提供 `baseRevision` 且不等于当前值、且未 `force`：返回 **409**，响应体为 `{ "error": "其他页面已更新工作区数据", "revision": <当前值>, "workspace": <服务器最新快照> }`；
  - 提供 `force=true`：无条件保存，`revision += 1`。
- 前端 `scheduleWorkspaceSync`：保存时携带内存中记录的最新已知 `revision`；收到 409 时：
  - 不做任何破坏性动作，显示可关闭的警告条："检测到其他页面更新了数据"；
  - 提供"采用服务器版本"（用响应体 workspace 快照覆盖本地状态）与"用本地覆盖"（带 `force=true` 重发当前快照）两个动作。
- `loadWorkspace` 与 409 后的"采用服务器版本"动作均同步更新本地记录的 `revision`。

## 配套清理

- `git worktree remove --force .worktrees/unified-trading-desk` 并删除 `feature/unified-trading-desk` 分支（用户已明确决定放弃该分支、按设计文档在新基线重新实现）。
- AGENTS.md 补充：一字板三态语义、workspace 乐观锁约定（PUT 携带 `baseRevision`、409 契约）。

## 数据与接口变化

- 新增：`GET /api/workspace` 响应字段 `revision`；`PUT /api/workspace` 查询参数 `baseRevision`、`force`；回测 metrics 字段 `onePriceLimitUpDays`、`onePriceLimitDownDays`。
- 修改：无既有字段改名或删除；409 为 PUT 的新增失败分支。
- 新表 `workspace_state` 只服务版本号，不改变 workspace 数据本身的存取结构。

## 测试与验证

自动测试（全部离线，pytest + monkeypatch）：

1. 排序修复：构造 change 为 `[0.0, 2.0, -1.0, None]` 的行情行，断言排序结果为 `[2.0, 0.0, -1.0, None]`。
2. 一字涨停日：构造 volume>0、`high == low == prev×1.1`（10% 板）的日线，断言卖单成交、买单为 0、`onePriceLimitUpDays == 1`、`skippedSuspensionDays == 0`。
3. 一字跌停日：对称断言买单成交、卖单为 0、`onePriceLimitDownDays == 1`。
4. 真停牌日（volume=0）：断言整日跳过、`skippedSuspensionDays == 1`（回归既有行为）。
5. workspace 乐观锁：不带 `baseRevision` 保存成功且 revision 递增；带过期 `baseRevision` 返回 409 且响应含服务器快照；带 `force=true` 保存成功。

前端验证：

- `node --check frontend/app.js` 语法通过。
- 浏览器手动验证：双开标签页分别修改自选，后保存者收到 409 警告条，两个动作各自生效且数据无损；选股器中 0.00% 股票排序位置正确；对近期出现一字板的标的回测，检查 metrics 新字段与 assumptions 文案。

## Git 流程

按仓库强制的 Git Flow：`git flow feature start p0-reliability-fixes`（off develop）→ 按逻辑分小提交（轮询守卫；排序修复；一字板三态；乐观锁与文案与文档同步）→ `git flow feature finish`（`--no-ff` 合入 develop）。废弃 worktree 与分支的清理在 feature 开始前完成。
