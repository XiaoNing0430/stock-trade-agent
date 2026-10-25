# UI 优化第③a批：布局 IA（信息架构与专注度） — 设计 Spec

- **日期：** 2026-10-15
- **状态：** 待用户复审（复审通过前禁止开发）
- **计划分支：** `feature/ui-layout-ia`（Git Flow，spec 与实现同分支）
- **路线图定位：** 「整体界面优化」三批的第③批拆分为 **③a 布局 IA**（本批）与 **③b 交互一致性**（随后独立成批）。①② 批已合入 `develop`（`6def4d2`、`9a4b1fd`）。
- **行号口径：** 本文所有行号为 2026-10-15 在 `develop`（`9a4b1fd`）上核对所得；实现时以符号/文本定位为准。

## 1. 背景与目标

第①②批解决了**颜色与版式**的统一，但**信息架构与专注度**未动：同一个事实在界面上被写了两遍甚至三遍。用户在本批开始前选定四个方向全做——**删假 UI + 去重、导航分组重构、桌面↔手机导航对齐、首屏密度与入口可达性**。经逐文件核对，问题可以精确定位为**六处「同一事实写两遍」**：

| # | 事实 | 出现处 | 核对结论 |
|---|---|---|---|
| 1 | 未读提醒数 | 顶栏铃铛徽标（`App.vue:150-155` 面板）/ 侧栏「个人中心」项（`App.vue:44-46`）/ 手机「我的」格（`App.vue:292-295`） | 同一 `unreadTotalCount` 三处呈现 |
| 2 | 行情来源与新鲜度 | 顶栏徽标（`App.vue:100-103`）/ 侧栏「数据连接」区块（`App.vue:50-57`）/ 页脚（`App.vue:272`） | 同一事实三处 |
| 3 | 策略三指标 | 总览 KPI③（`ViewOverview.vue:36-43`）/「验证策略」面板（`ViewOverview.vue:109-122`） | **逐字相同** |
| 4 | 执行三指标 | 总览 KPI④（`ViewOverview.vue:44-48`）/「执行跟踪」面板（`ViewOverview.vue:137-147`） | **逐字相同** |
| 5 | 视图名与说明 | 顶栏（`VIEW_META`）/ 视图内抒情 h2（8 个视图） | 例：「交易计划」两处逐字相同 |
| 6 | 装饰性英文标签 | 34 处 `section-kicker`（8 视图）+ 顶栏 eyebrow（`App.vue:97`） | 前端 25 个测试文件**零断言** |

另有两处**假 UI**（无真实数据支撑）：侧栏「林默 / 个人工作区」+ 无行为的「用户菜单」按钮（`App.vue:82-91`）、静态「A股市场 / 实时行情代理」卡（`App.vue:21-30`）。

以及一处**入口可达性断点**：9 处标的人口中有 5 处持有代码却点不动（详见 §9）。

本批目标：**让同一事实只写一遍，让导航按工作流分组且桌面手机同构，让每个持有代码的地方都能下钻**。

## 2. 已裁定决策（2026-10-15 用户确认，视觉伴侣七屏选型）

1. **拆分**：③ 拆成 ③a 布局 IA（本批）+ ③b 交互一致性；先做 ③a，因为 ③b 的对话框/空态要挂在重组后的布局上。
2. **导航分组 = B + B1**：按工作流分 5 组（研究/验证/执行/风控/系统），`总览`独立置顶不分组；桌面侧栏显示分组标题。**通知收件箱留在「系统 · 个人中心」**（现有跳转与徽标接线零改动）。
3. **手机端 = M1**：`总览 · 选股 · 计划 · 盯盘 · 更多`，抽屉用同一套分组标题；未读徽标挂「更多」格。手机格子给「手机场景高频」，重表格（策略/风控）进抽屉。
4. **壳层 = V1 + 两处精修**：行情状态（状态 + 最后更新时间 + 点击刷新）**合成顶栏一个控件**；侧栏底部只留主题开关 + 版本号；页脚**只删重复的 provider，保留免责声明**；状态控件在 stale/error 时的警示强度不得弱于现状。
5. **总览首屏 = O1**：4 张 KPI 卡压成**一行状态带**（各数字带跳转），面板删掉与 KPI 逐字重复的行；「验证策略」卡被状态带吸收，其入口由状态带「策略」数字承担。
6. **标题唯一化 = H1**：顶栏（`VIEW_META` 驱动）是唯一页头；删除 8 个视图的抒情 h2 + 说明与 34 处英文 kicker；卡片 `h3` 升为 `h2` 避免 `h1→h3` 跳级。动态标题例外保留（§8）。
7. **可达性 = R1**：5 处断点全补下钻，全部传 `fromView`；「返回」改为带来源名；个股详情不进主导航。

## 3. 非目标

- **③b 内容**：对话框 Esc/焦点陷阱/滚动锁、加载/空态/骨架规范、Toast 去重与堆叠规则、键盘快捷键增补。
- 多语言（英文 UI）与自定义主题配色（ROADMAP 另一项）。
- 视觉令牌、配色、字号、圆角、阴影调整（①②批已交付，本批不动）。
- 后端与数据结构改动（**零 API / 零 schema / 零迁移**）。
- `VIEW_META` 之外的标题文案体系改造（顶栏标题继续由 `VIEW_META` 单一驱动）。
- `.vue` 组件文件结构重构、`styles.css` 拆分（维持单文件）。
- 个股详情进入主导航（它是上下文相关的详情页，非目的地）。
- 快捷键 `7 → 个人中心` 的增补（属交互行为，③b）。

## 4. 目标信息架构

**分组定义**（新增于 `frontend/src/modules/constants.ts`）：

| 组 id | 组标题 | 成员（`NAV_ITEMS.id`） |
|---|---|---|
| （无） | — | `overview` 总览（置顶，不显示组标题） |
| `research` | 研究 | `screener` 选股器 |
| `validation` | 验证 | `grid` 策略 |
| `execution` | 执行 | `plans` 交易计划 · `monitor` 盯盘中心 |
| `risk` | 风控 | `portfolio` 组合风险 |
| `system` | 系统 | `settings` 个人中心 |

**关键性质：导航项顺序与现状完全一致**（总览/选股器/策略/交易计划/盯盘中心/组合风险/个人中心），本批只**插入组标题**。因此 `app.ts:97` 的数字键快捷键 `{1:overview, 2:screener, 3:grid, 4:plans, 5:monitor, 6:portfolio}` **语义不变、无需改动**（已核对）。

**侧栏构成（自上而下）**：

1. 品牌（`Atlas / 交易工作台`，现状保留）
2. `总览`（无组标题）
3. 5 组：组标题 + 组内导航项（复用现有 `.sidebar-section-label` 作为组标题样式——该样式原服务于被删的「数据连接」标题；它在 ≤680px 已被 `display:none`，与手机端不显示组标题的现状一致）
   - **2026-10-25 更正**：组标题此后只在同组有 **≥2 项**时渲染——研究/验证/风控/系统 各只有 1 项，标题对用户零信息量；仅「执行」（交易计划 + 盯盘中心）保留标题，单成员分区改由首项 `nav-item--section-start` 的上间距保留节奏。契约与用例同步改于 `tests/frontend/AppShell.test.ts`。
4. 侧栏底部：主题开关（现状）+ 版本号（新增静态文本，值取 `package.json` 版本，构建期注入或硬编码并在 CHANGELOG 同步）

**删除**：`market-switcher`（含 `market-state`）、`sidebar-data-note` 区块与「数据连接」标签、`sidebar-note`（「先计划，再执行」卡）、`user-profile`（含用户菜单按钮）。

> **取舍记录**：研究/验证/风控 三组各只有 1 个成员，组标题在此是**语义标签**而非收纳框。保留的理由是它承担「工作流阶段」的读数作用，且为③b及后续新增入口预留结构位；若复审认为啰嗦，可退化为「仅执行组显示标题」，但需在本批内一次定死。

## 5. 手机端（≤680px）

- **底部 5 格**：`总览 · 选股 · 计划 · 盯盘 · 更多`（顺序即上表首项与执行组两项）。
- **「更多」抽屉**：底部 sheet，内容按**同一套分组标题**排列：`验证 → 策略`、`风控 → 组合风险`、`系统 → 个人中心`。关闭方式：点击遮罩（与现有 `.dialog-backdrop` 的 `@click.self` 一致）。**Esc/焦点陷阱/滚动锁不在本批**（§11）。
- **徽标**：`unreadTotalCount` 挂「更多」格（复用 `.nav-count`，`.bottom-nav .nav-count` 定位规则已存在），抽屉内「个人中心」行再显示一次。桌面侧栏仍挂「系统 · 个人中心」项（现状不变）。
- **拆除 `exec` 伪视图**：`view === 'exec'` 分支、`mobile-exec-tabs` 区块、`mobileExecTab/execShowsPlans/execShowsAlerts` 三件套全部删除；`view-plans`/`view-monitor` 的条件简化为 `view === 'plans'` / `view === 'monitor'`。手机格「计划」「盯盘」直接切这两个视图。
- **标签双名规则**：格子用 `shortLabel`（`选股`/`计划`/`盯盘`），抽屉用 `label` 全名（`策略`/`组合风险`/`个人中心`）。这是**沿用既有约定**（今天手机格已是 `选股/网格/执行/我的` 对桌面 `选股器/策略/...`），不靠 CSS 截断。
- **≤680px 现状保留**：侧栏退化为「品牌 + 主题开关」横条（`primary-nav`、`sidebar-section-label`、`sidebar-data-note`、`user-profile` 均已被 `display:none`）。

## 6. 壳层（顶栏 / 页脚）

**行情状态控件（顶栏，唯一事实源）**：

- 位置：`topbar-actions` 内替换现有 `.topbar-date` 按钮（`App.vue:232-235`）；同时删除 `topbar-title-row` 里的 `.demo-badge`（`App.vue:100-103`）。
- 内容：状态点 + 状态文案（`真实行情` / `缓存行情` / `行情连接中`，沿用 `dataState` 语义）+ 最后更新时间 + 刷新图标（`loading` 时转圈，现状）。
- 点击 = `refreshAll()`（现状行为）。
- **日期边界**：删除总览页头的「数据日期」后，当 `market.fetchedAt` 不在今天时，控件须显示 `MM-DD HH:MM`（而非仅 `HH:MM`），避免跨日缓存无从分辨。`fetchedLabel`（`formatDateShort`）与 `lastUpdatedLabel`（`formatTimeShort`）均来自 `market.fetchedAt`，数据已具备，无需新状态。
- **三态不弱化**：`stale`/`error` 下的配色与文案沿用现有警示强度（现 `.demo-badge-stale` 的告警语义迁移到新控件，不得退化为中性灰点）；`dataStatusText`（`接口异常，显示缓存` / `等待行情接口恢复`）与 `providerLabel` 进 tooltip + `aria-label`。
- **全宽度可见**：≤900px 时 `topbar` 变竖排、`topbar-actions` 占满整行（现状 CSS），控件仍可见。这是选择该方案的主因：手机端侧栏已隐藏，若把状态只留侧栏则 ≤680px 完全看不到行情新鲜度。

**页脚**：`行情接口：{{ providerLabel }} · 研究工具不构成投资建议` → 只删前半段重复的 provider，保留 `研究工具不构成投资建议`（合规需要的免责声明，非假 UI）。

## 7. 总览首屏（`ViewOverview.vue`）

- **删除**：`desk-kpis` 四张卡（`ViewOverview.vue:21-49`）。
- **新增**：一行**状态带**，四个数字各带跳转——`指数涨跌%（→ 盘面温度/无跳转）· 候选命中数（→ 选股器）· 运行中策略（→ 策略）· 未读提醒（→ 个人中心）`。各数字来源取现 KPI 的既有字段（`selectedIndex`、`screenRows/filteredRows`、`strategyStats.running`、`unreadAlerts`），**不引入新统计口径**。
- **面板调整**：
  - 「发现机会」保留（预设命中 + 4 只标的 + 进入选股器），删除与状态带重复的表述（KPI② 的 `候选数量` 已被状态带吸收）。
  - **「验证策略」卡整张删除**：其 3 行数字被状态带吸收，入口由状态带「策略」数字承担。
  - 「执行跟踪」保留，删除与状态带逐字重复的 stat rows（活跃计划/触及止损/未读提醒三行），保留「动态 2 条 + 进入盯盘提醒」。
- **保留**：告警黄条（`connection-banner`，错误红线）、`盘面温度`（指数网格 + 40 日线 + 涨跌家数）——它是本页唯一的市场主体，不动。
- `desk-kpis`/`desk-kpi` 相关 CSS 随之删除或改名为状态带样式。

## 8. 标题唯一化（H1）

**规则**：顶栏标题与副标题（`VIEW_META`）是**唯一页头**；视图内删除 `section-kicker`（全部）、装饰性 `h2`、`heading-note`。

**必须保留的例外（属内容，不属页头）**：

| 视图 | 保留内容 | 处理 |
|---|---|---|
| `ViewGrid` | 动态 h2（当前策略类型）+ 回测假设 `heading-note`（`ViewGrid.vue:6-15, 293, 504, 592, 654`） | 降级为内容区标题/说明，不删 |
| `ViewStockDetail` | h2 = 股票名 + 副信息（`ViewStockDetail.vue:6-13`） | 降级为内容区标题，不删 |

**`view-heading-actions` 一律保留**（只删同级的 kicker/h2/note），已核对 8 个视图的 actions 内容均为功能控件：

| 视图 | actions 内容 | 处置 |
|---|---|---|
| 总览 | 数据日期 + 今天日期（`data-updated` / `strategy-label`） | 日期由顶栏控件承担（§6）；**今天日期删除** |
| 选股器 | 行情列表时间 + 「重新扫描」 | 保留 |
| 策略 | 网格模式的生成/回测按钮（`v-if="strategyType === 'grid'"`） | 保留 |
| 交易计划 | `N 份执行中` + 「去盯盘」 | 保留 |
| 盯盘中心 | 盯盘开关 + 「立即扫描」 | 保留 |
| 组合风险 | 「刷新」 | 保留 |
| 个人中心 | 设置子 tab 的动作区（`ViewSettings.vue:112`） | 保留 |
| 个股详情 | 「生成草案」+「返回」 | 保留（返回文案见 §9） |

**层级**：删除 h2 后，内容区卡片标题从 `h3` 升为 `h2`，避免 `h1 → h3` 跳级；`.view-heading` 在只剩 actions 时改为单行布局（动作右对齐，`≤680px` 保留现有竖排规则）。

## 9. 入口可达性（R1）

**现状矩阵（已逐个核对）**：

| 入口 | 持有标识 | 现状 | 本批 |
|---|---|---|---|
| 全局搜索 | `code` | 能下钻 | 不动 |
| 总览 · 发现机会 mini 列表 | `code` | 能下钻 | 不动 |
| 选股器（结果/精选/候选 3 处） | `code` | 能下钻 | 不动 |
| 盯盘中心 · 盯盘列表 | `code` | 能下钻 | 不动 |
| 提醒面板（顶栏铃铛） | `alert.code` | **不能** | 补「查看详情」按钮（与已有 `alert-code-chip`「生成草案」并列） |
| 通知收件箱（个人中心） | `alert` 对象含 `code`（未渲染） | **不能** | 补「查看详情」 |
| 交易计划列表 / 已归档表 | `plan.code` / `item.code` | **不能** | 代码可点 → 详情 |
| 组合风险 · 交易对表 | `pair.buy.code` | **不能** | 代码可点 → 详情（需引入 quotes store） |

**实现要点**：`selectStock(code, fromView)`（`useQuotesStore.ts:147-161`）已支持来源记录（`detailReturnView`），所有新增下钻**必须传 `fromView`**，`backFromDetail()`（`:163-167`）无需改动。

**返回文案**：`ViewStockDetail.vue:19-21` 的泛化「返回」改为 `返回{来源视图名}`（来源名取 `VIEW_META[detailReturnView][0]`，如「返回组合风险」「返回盯盘中心」）。

**个股详情不进主导航**（理由：上下文相关详情页，导航中留它会产生无标的的空壳入口）。

## 10. 状态与数据流改动

| 文件 | 改动 |
|---|---|
| `modules/constants.ts` | `NAV_ITEMS` 每项新增 `group`（`overview` 为 `null`）与 `shortLabel`；新增分组顺序表 `NAV_GROUPS`（`research/validation/execution/risk/system` + 中文标题）。7 项数量不变 |
| `stores/useQuotesStore.ts` | 删除 `mobileExecTab` / `execShowsPlans` / `execShowsAlerts`；**`view` 增加白名单归一**（合法集合 = `NAV_ITEMS.id` + `stock-detail`，未知/已移除即 `exec` → `overview`）；`switchView` 同样校验；删除仅服务于被删页头的 `todayLabel`（导出点一并移除） |
| `App.vue` | 侧栏按组渲染；删假 UI 与重复信息；状态控件合一；底部栏 5 格 + 更多抽屉；页脚免责声明保留 |
| `styles.css` | 新增：侧栏组标题复用 `.sidebar-section-label`、状态带、更多抽屉（sheet/遮罩/行）；删除：`.desk-kpi*`、`.mobile-exec-tabs`、`.mobile-exec-tab`、`.user-profile`、`.market-switcher`、`.sidebar-data-note`、`.sidebar-note`、`.topbar-eyebrow`、`.section-kicker`、`.demo-badge*`、`.data-updated`（`.strategy-label` 仍被 `.presetName` 使用，保留）及 ≤680px 内的死规则（例：`styles.css:3100-3127` 整段失效——它把 `.primary-nav` 设为 `flex` 并隐藏 `.nav-item span`，但 `:3723` 的后续 ≤680px 规则又把 `.primary-nav` 改成 `display:none`） |
| 8 个视图 | 删 kicker/装饰标题与说明；层级调整；`ViewPortfolio` 引入 quotes store 以支持下钻 |

**`VIEW_META` 不改**（唯一页头源，且被 `constants.test.ts` 断言覆盖所有导航项）。

## 11. 错误与降级

- **不造价格红线不变**：状态控件在三态下的如实披露强度不得弱于现状（这正是排除「状态只留侧栏」方案的原因：≤680px 侧栏内容全部 `display:none`，会把行情新鲜度彻底藏起来）。
- **抽屉行为**：本批只实现点击遮罩关闭；**Esc / 焦点陷阱 / 滚动锁显式留给 ③b**，与两个既有对话框的升级在同一次收口，避免两批各写一套再返工。此为**跨批依赖**，写在 §14 已知限制。
- 视图归一是**防白屏**措施：`view` 初值来自 `localStorage`（`useQuotesStore.ts:17`），老存储里的 `'exec'` 会让内容区无任何视图匹配而空白（顶栏因 `currentViewMeta` 回退仍显示「交易总览」）。
- 组合风险的下钻不得改变其降级黄条/错误红条逻辑（`ViewPortfolio.vue:17-19`）。

## 12. 测试计划

**既有测试的硬约束（实现时不得破坏）**：

- `tests/frontend/useAlertsStore.test.ts` **挂载 `App.vue`**（`:97`），依赖：① 铃铛按钮 `aria-label="通知中心"`（`:111`）；② `data-testid="alert-code-chip"` 与其 `openFor({code, source})` 行为（`:112-117`）。→ **R1 的「查看详情」必须是新增兄弟元素**，不得重命名/替换现有 chip 与铃铛 aria-label。
- 该测试在 jsdom 中同时渲染桌面侧栏与手机底部栏（jsdom 不执行 CSS 布局，`display:none` 元素仍在 DOM）。→ 徽标在 DOM 中会出现两次（侧栏 settings 项 + 更多格）；新增测试查询必须**限定作用域**，不得用全局计数断言。
- 现有 25 个前端测试文件对 `nav-item` / `sidebar` / `topbar` / `view-heading` / `section-kicker` **零引用**（已核对）→ 壳层改造不产生修旧测试的负担。
- `tests/frontend/constants.test.ts` 现有断言（id 唯一、含 6 个 id、`label`/`icon` 为 string、`VIEW_META` 覆盖）在新增 `group`/`shortLabel` 后**仍然成立**。

**新增测试**：

1. `AppShell.test.ts`（新）：
   - 侧栏按 5 组渲染，组标题顺序 = 研究/验证/执行/风控/系统，且 `总览` 在组外置顶；
   - 手机底部栏 5 格（含「更多」），点击「更多」渲染抽屉且抽屉内分组标题与桌面一致；
   - 徽标：桌面挂「个人中心」项、手机挂「更多」格（作用域查询）；
   - 删除断言：模板中不含 `user-profile` / `market-switcher` / `sidebar-data-note` / `demo-badge`。
2. `ViewOverview.test.ts`（新，本视图此前无测试）：
   - 状态带渲染 4 个数字并带对应跳转；
   - 「验证策略」卡不存在；「执行跟踪」不再渲染重复的 3 行 stat rows。
3. `useQuotesStore` 归一（可入既有 store 测试或新文件）：`localStorage` 中 `view='exec'` 与未知值均归一到 `overview`；`switchView('exec')` 不再生效。
4. `constants.test.ts` 增补：每个导航项 `group` ∈ `NAV_GROUPS`（或 `null`）、`shortLabel` 为非空 string、每组至少 1 个成员。
5. 下钻接线：断言 5 处新增入口点击后 `detailReturnView` 等于来源视图且 `view === 'stock-detail'`（示例：交易计划 → 详情 → 返回回到 `plans`）。

**机械验收（grep 断言，实现后逐条核对）**：

- `section-kicker` / `topbar-eyebrow` 在 `frontend/src/` 残留 **0**；
- `exec` / `mobileExecTab` / `execShowsPlans` / `execShowsAlerts` 在 `frontend/src/` 残留 **0**（`ViewPortfolio.vue` 的 `d.executed` 不属此列，按词边界核对）；
- `mobile-exec-tabs` / `mobile-exec-tab` / `.user-profile` / `.market-switcher` / `.sidebar-data-note` / `.sidebar-note` / `.demo-badge` 在 `styles.css` 与模板中残留 **0**；
- 装饰性 h2/`heading-note` 仅剩 `ViewGrid` 与 `ViewStockDetail` 两处例外；
- 前端不得出现大写英文 kicker 文案（正则 `>[A-Z][A-Z /]{3,}<`）。

**回归门禁**：`npm run verify`（vitest + `vue-tsc --noEmit` + pytest）。后端零改动 → pytest 应保持 679 项全绿、覆盖率不降。

**人工核对（无自动化覆盖的壳层）**：1260 / 1180 / 1060 / 900 / 680 五个断点逐一核对——侧栏分组标题、状态控件、底部 5 格与抽屉、页脚、无横向溢出。

## 13. 文档收口

- `AGENTS.md`：项目布局中 `App.vue` / `constants.ts` / `styles.css` 描述更新（分组导航、状态控件、无 kicker）。
- `CHANGELOG.md`：在 v0.7.2 段落内追加「UI 布局 IA（第③a批）」小节，如实声明删除项（假 UI、34 处 kicker、重复标题/指标）与手机导航变化。
- `ROADMAP.md`：勾选「整体界面优化」中本批覆盖的子项，并注明 ③b 待做。

## 14. 已知限制（如实披露）

1. **抽屉无键盘关闭**：③a 的「更多」抽屉只有点击遮罩关闭，Esc/焦点陷阱属 ③b；期间键盘用户需要点遮罩或切格。
2. **格子与抽屉双名**：手机格用 `shortLabel`（选股/计划/盯盘），抽屉用 `label` 全名。同一目的地两种显示名，属**沿用既有约定**，但确实不是"同名"的严格实现。
3. **单成员分组**：研究/验证/风控 各 1 项，组标题对它们只是语义标签（取舍见 §4）。
4. **无截图证据**：本批验收依赖 grep 断言 + 新增测试 + 五个断点人工核对；不产出 playwright 前后对比图（①②批的像素级验收方式不适用于结构改造）。若需要可视证据，应在实现计划中显式增补截图任务。
5. **老存储迁移**：`localStorage` 中的 `view` 若为 `'exec'` 将被归一到总览；用户上一次所在视图丢失一次（一次性，可接受）。
6. **手机端分组标题**：只有在「更多」抽屉里可见——手机侧栏被裁到只剩品牌与主题开关（现状 CSS），桌面侧栏的组标题在手机上无处显示。

## 15. Self-Review 记录

- **占位符扫描**：无 TBD/TODO；版本号取值方式（构建期注入或硬编码）在 §4 已给出二选一并要求在计划中定死，属实现决策而非未定内容。
- **一致性**：§2 决策与 §4–§9 逐条对应；§10 的文件清单与 §5/§6/§8/§9 的改动一一对齐；§12 的断言清单与 §8/§5 的删除项一致。
- **范围**：单实现计划可承载（壳层重组 + 8 视图标题收敛 + 5 处下钻 + 测试），无需再拆；③b 内容已明确排除。
- **歧义修复**：明确「删除视图内 h2 但要保留 `view-heading-actions`」（§8 表格）；明确「研究/验证/风控 单成员分组照常显示标题」（§4）；明确状态控件跨日显示 `MM-DD HH:MM`（§6）；明确 `exec` 拆除后的 `view` 归一（§10）；明确「返回」文案取 `VIEW_META` 名称（§9）。
