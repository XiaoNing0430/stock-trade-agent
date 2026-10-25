# Changelog — Atlas Trading Desk

All notable changes to this project. 版本更新清单。

## [未发布]

### 导航分区标题减噪（③a 遗留收口，2026-10-25）

- **组标题只在同组有 ≥2 项时渲染**：研究/验证/风控/系统 各只有 1 项，标题对用户零信息量，故不渲染；仅「执行」（交易计划 + 盯盘中心）保留标题。
- **分区节奏改由上间距承担**：无标题分区的首项带 `nav-item--section-start`（上间距与标题等价）；图标条断点（≤1060px）原本就隐藏标题，故显式收平间距，保持等距图标列。
- **「更多」抽屉退化为纯列表**：抽屉只收未进底部栏的 3 项，分属 3 个单成员分区 → 组标题一个都不渲染，行高 44px 与命中区不变。
- **测试**：`AppShell.test.ts` 侧栏契约改为「标题 = `['执行']`、无标题分区首项 = 选股器/策略/组合风险/个人中心」；抽屉断言改为「0 个组标题 + 3 项仍在」。

## [v0.7.2] - 2026-10-18

### 多策略回测对比 + CSV 导出（研究体验 P3）

- **`POST /api/strategy/compare`**：同标的横向对比。一次上游取数，同一份日线重放全部勾选策略（网格自动建议区间 8 格 classic + 7 个策略引擎 schema 默认参数）；单策略失败不拖垮整单（per-item `error`，HTTP 200）；trades 全量不截断（与单策略端点 `-100` 截断的有意差异）；顶层基准曲线仅一份；结构化日志 `strategy.compare`（耗时/状态/失败类型）。
- **`POST /api/strategy/compare-saved`**：已保存策略对比。snapshot 纯读库 `latestMetrics`（失效 id / 从未回测逐项如实披露）；rerun 按各自保存参数现跑（per-item `dataSource`/`dataAsOf` 降级披露）；**零写库**——不写 backtest 表、不更新 `latest_metrics`、不调度。
- **前端**：ViewGrid 新增第 9 个「对比」tab（策略类型勾选 + 指标对比表最优高亮 + `multiLineSvg` 归一化净值叠图 + 已保存策略合并勾选 ≤10）；新模块 `modules/csv.ts`（指标/曲线宽表/成交长表三张 CSV 组装，`csvCell` 对 `= + - @ \t \r` 开头字符串加 `'` 前缀防 Excel 公式注入，BOM + Blob 下载）；新 store `useCompareStore`。
- **测试**：新增 `tests/test_strategy_compare.py`（14 用例，含 rerun 零写库断言与终审收尾回归：保存 0 值参数不被 `or` 兜底改写、`tradesLimit` 穿透隔离、未知策略类型中文报错）+ 前端 3 个测试文件（csv 注入矩阵 + RFC4180 引号包裹 / store 全选清空截断 / ViewGrid 冒烟）。

### UI 主题基建（第①批）

- `styles.css` 全量令牌化：103 处裸色值收敛为语义令牌（浅色渲染零变化），新增 `html[data-theme='dark']` 覆盖块（B · 中性炭灰基调）。
- 另修复基线遗留的 7 处未定义令牌引用（--border/--text/--accent/--shadow-large）与图表面积填充的令牌适配——前者的边框/着色/阴影修复前因变量未定义而不渲染，属用户可见变化。
- 终审修复：图表面积填充改由 `.chart-area` 类规则着色（`var()` 拼 hex alpha 曾致 SVG 黑块）、侧栏主题开关图标随主题翻转；暗色补 `color-scheme: dark` 并为无样式控件（`.field` 文本输入 / `.settings-row` / `.input` / `.minute-toolbar`）接通既有令牌——浅色下这些控件由 UA 白底改为令牌浅灰，属用户可见变化。
- 新模块 `modules/theme.ts`：浅/深/跟随系统三态，localStorage 持久化（键 `atlas-theme`，异常静默降级），`main.ts` 首帧前应用防闪白，系统偏好变化仅在未显式选择时联动。
- 入口：侧栏底部快捷开关 + 设置页「外观」三态卡片；图表/组件取色接入 `--chart-N` 令牌，暗色自适应。

### UI 视觉打磨（第②批）

- 版式令牌阶梯：字阶 14 种收敛为 5 档（11/12/14/18/24，`--fs-*`）、间距全量落 4px 栅格（`--space-1..8`）、圆角 8 种收敛为三档（6/8/12，`--radius-sm|md|lg`）、阴影两档（`--shadow-sm|md`）；旧版式令牌删除。
- 四族组件精修：数据表格 33px 行高统一、表单控件 32px 高 + 焦点环统一、卡片标题节奏统一；按钮三档高度（sm 28 / md 34 / lg 38）与禁用态（透明度 + cursor）统一——lg 档应用于对话框与表单 footer 主操作。全站版面 ±1-2px 位移与字号 ±1px 变化属本批目的（A 密度 + B 字阶方向，用户选定）。
- playwright 8 视图 × 浅/深前后截图对比验收。

### UI 布局 IA（第③a批）

- 主导航按工作流分区（研究/验证/执行/风控/系统），总览置顶；桌面侧栏显示分区标题。
- 手机底部栏改为 4 格直达 + 「更多」抽屉，未读徽标挂「更多」。
- 行情状态（状态 + 最后更新时间 + 刷新）合并为顶栏单一控件，跨日显示日期；页脚去掉重复的行情源。
- 总览首屏 4 张 KPI 卡压成一行状态带，删除与面板逐字重复的指标。
- 删除 8 个视图的装饰性标题与 34 处英文标签；视图标题由顶栏单一提供。
- 5 处「有代码点不动」的入口补上下钻（提醒面板/通知收件箱/交易计划/已归档计划/组合风险交易对），详情「返回」显示来源视图。
- 如实披露：手机格用短标签（选股/计划/盯盘）而抽屉用全名；「更多」抽屉暂无 Esc 关闭（留给第③b批）。
- 代码清理（无 UI 影响）：删除 `marketStatus`（`dataState` 的第三次复述，两个渲染点本批均已移除）与 `todayLabel`；`view` 增加白名单归一（老存储里的 `exec` 归一到总览）。
- 验收记录：机械断言全量通过（装饰性 kicker / 假 UI 类 / exec 伪视图 / `todayLabel` 均 0 残留）；装饰性大写英文标签仅剩 `ViewPortfolio` 的 `HHI` 一处**已裁定例外**（技术指标缩写，非装饰标签）。本批不产出截图证据——第①②批的像素级前后对比方式不适用于结构改造，壳层验收由机械断言 + 五断点（1260/1180/1060/900/680px）人工核对承担。

### UI 交互一致性（第③b批）

- 新增 `modules/overlayA11y.ts` 并接线 5 个浮层（交易计划草案 / 自定义策略编辑器 / 通知面板 / 「更多」抽屉 / 快捷键帮助）：Esc **只关最顶层**、Tab 焦点陷阱（过滤 disabled / `tabindex="-1"` / `display:none` / `inert`，首尾循环）、浮层打开时锁定 `.view-panel.is-active` 滚动、关闭后焦点归还触发控件；通知面板与「更多」抽屉补齐 `role="dialog"` + `aria-modal="true"` + 遮罩语义。
- 立「加载中 / 没有数据 / 字段缺失 / 失败」四态语义并落到 8 个视图：加载中一律 `.loading-state` + `role="status"`（转圈图标，`prefers-reduced-motion` 下不转）、**绝不与 `--` 互顶**；没有数据才是 `.empty-state`（结论 + 下一步），字段缺失仍是 `--`，失败沿用既有告警。空态按「**就地动作优先、否则跳转**」补 6 处动作按钮（精选 50 / 策略回测 / 多策略对比 / 交易计划 / 组合净值）；组合风险净值区与 KPI 首屏加载中不再显示「暂无持仓」结论而是「计算中」。
- Toast 策略：同 `tone + message` **去重**（重复触发不新增节点，加 200ms 高亮脉冲）、屏上**上限 3 条**（超出从最旧移除）、整条可点击关闭 + `aria-label="关闭提示"` 按钮、悬停 / 聚焦暂停计时（离开按整段时间重计）、error 6000ms 其余 3200ms；保留 `aria-live="polite"` 并移除区域级 `aria-atomic`（避免每次新增重读整屏 3 条）。~75 处调用点与既有 spy 断言零改动。
- 桌面快捷键：`1`–`7` 切视图、`/` 聚焦搜索框、`?` 开关快捷键帮助浮层；修饰键 / IME 组合 / 输入框（含 SELECT、内容可编辑区）/ 浮层打开时一律不触发导航。导航项与抽屉项补 `aria-keyshortcuts`，顶栏新增常显 `?` 入口；帮助浮层键位表覆盖 `/`、`1`–`7`、`?`、`Esc` 与 `Enter` 在搜索框 / 回测参数框的提交语义，并注明数字键为桌面快捷键。
- 5 处下钻控件（通知 chip / 设置页提醒 / 计划行与复盘行 / 组合风险交易对）补**逐行可访问名**：有行情名称时为「查看 {名称} {代码} 的详情」，名称缺失时退化为「查看 {代码} 的详情」——只读内存中既有行情，**零新增请求与字段**，绝不拿事件标题冒充股票名。
- ≤1060px 图标条隐藏侧栏主题开关文字标签（仅留图标 + `aria-label`），避免 82px 宽图标条内文字溢出。
- 修复：浮层滚动锁在**选股器视图**失效——既有 `.screener-view { overflow: auto !important }` 压过锁规则，为锁声明补 `!important`（特异性 (0,3,1) 胜出）后压回；真浏览器复验该视图 `overflow` 由 `auto` 变 `hidden`，并新增 `stylesContract` 测试守卫此契约。
- 验收与门禁：真 chromium + 真后端四档宽（1440 / 1060 / 900 / 680）**31 条断言全通过、0 未验证**（Esc 四浮层、面板内 12 次 Tab 循环、滚动锁锁定与恢复、Toast 去重与上限、快捷键切换与全部抑制路径、≤1060 标签隐藏）；`npm run verify` 全绿（vitest 34 文件 / 369 项、`vue-tsc` 0 error、pytest 679 通过、覆盖率 93.23%）。**后端零改动。**
- 如实披露：快捷键派发器（`app.ts`）的端到端接线无仓库内集成测试，由浏览器验收 + 决策级单测承担；另发现**既有**缺陷 `/api/workspace` PUT 200/409 交替（前端不推进 `workspaceRevision`，后端每次 +1），本批未触碰，已另开修复分支修复（见下节）。

### 修复 — 工作区同步 PUT 200/409 交替（F1）

- 现象：单标签页内定时同步连续 PUT 出现「成功 / 409」交替（真浏览器探针实测 **4×200 / 4×409**），并伴随杂散 toast「检测到其他页面更新，已自动采用服务器版本」。
- 根因：后端 `storage._bump_workspace_revision` 每次保存 **+1**；前端 `useWorkspaceStore` 的 `scheduleWorkspaceSync` / `syncNow` 成功 PUT 后**丢弃**响应里的新 `revision`，本地 `workspaceRevision` 永久落后一格。下一次 PUT 必带过期 `baseRevision` → 409；默认 `server` 冲突策略随即用服务器快照覆盖本地，**丢弃尚未落盘的本地改动**。
- 修复：两条写路径成功时采用响应 `revision`（`adoptWorkspaceRevision`）；响应缺该字段时保持原值，绝不清零。
- 验证：同一真浏览器探针 + 真后端 A/B —— 修复前 4×200 / 4×409，修复后 **8×200 / 0×409** 且 `baseRevision` 逐次跟进（1674→1675→…）；新增 3 条 store 用例（实现回退即红）。

### ③b 批延后 minor 收口（测试硬化与小修）

- 终审与验收共登记 **45 条**延后 minor（另 3 条 ③a 遗留），逐条裁定：**能写出可判别断言的修，其余显式记录理由后关闭**（不静默丢弃、不伪造覆盖）。**后端零改动。**
- 产品小修：浮层 Tab 在「顶层浮层面板尚未/不再存在」的一帧内不再漏给背景、打开时的延迟聚焦补「已关闭」守卫、`isVisible` 拒绝 `inert` 祖先子树；组合风险首屏 KPI 容器内最后一处裸 `--`（「本次费率」）接入加载态；≤1060px 图标条主题开关的 `padding` 惰性声明提特异性后**真正生效**；`.toast`（`cursor`）与 `.shortcut-table th/td` 规则归位到既有作用域。
- 测试硬化（每条都能指出它拦下的回归）：Toast 120ms 淡出窗可观测、去重确实重挂计时、上限「最旧条进入淡出且节点数 ≤ 存活+1」、直接点 `.toast-close`；浮层 `closeOnEsc:false` / `[data-autofocus]` / 空面板 / 归还目标已断开四条分支；详情页「有缓存刷新不得掩盖真实值」补锁定断言（并使 `&& !selectedStock` 半侧可判别）；网格与复盘加载态被结果替换；帮助浮层 `.self` 负向；精选空态按钮文案；下钻可访问名由「存在 `aria-label`」改为精确串断言。快捷键派发器抽出可测工厂 `createShortcutHandler` 并补齐派发 / 抑制（含 `metaKey`/`altKey`/`TEXTAREA`）/ 初始化期卸载泄漏（监听器与刷新计时器）用例。
- 规格口径注记：§8.2 Toast 上限的「子节点数」明确为**存活**条数（淡出期内瞬态第 4 个子节点属设计；严格「≤3 子节点」会删掉同句要求的 120ms 淡出）；§6.3 更正桌面端被隐藏元素为 `.bottom-nav`（结论「无键盘风险」仍成立）。
- 验收：真浏览器 **31 条断言全通过 / 0 未验证**；`npm run verify` 全绿（vitest 35 文件 / 402 项、`vue-tsc` 0 error、pytest 679 通过、覆盖率 93.23%）。验收脚本原「Toast 上限」断言此前依赖 F1 缺陷产生的杂散 toast 才能凑齐淘汰条件，F1 修复后改为**显式触发 4 条不同文案并逐条等其真出现**，断言口径与规格 §8.2 淡出语义对齐。

### 修复 — Pinia 解构导致响应式冻结（冲突横幅 / 盯盘开关 / 总览提醒）

- 现象（三处，**均早于 ③b 批**）：① 冲突处理策略设为「询问」时，工作区冲突横幅**永不显示**（`v-if` 恒假），「忽略冲突提示」按钮也写不回状态；② 盯盘中心的盯盘开关点击只翻 DOM 复选框——store 标志不变、状态标签不变、不发 toast（真机连点 6 次标签恒为「盯盘已开启」）；③ 总览「提醒」计数与提醒动态列表冻结在挂载瞬间。
- 根因：`const { x } = store` 直接把 Pinia store 的 `ref` / `computed` 解构出来，得到的是**挂载时快照**——既不跟随后续变化（模板 `v-if` 与派生文案不动），绑定写入也落空（写的是本地绑定而非 store）。
- 修复：三处改用 `storeToRefs(store)` 解构响应式状态；函数（`refreshAll` / `renderIcons` / `switchView` 等）仍直接解构。仓库其余同形写法经全仓 grep 分类确认解构的都是函数，无同类问题。
- 验证：新增 3 组回归用例，修复前逐条变红（`expected false to be true`：横幅不渲染；`expected true to be false`：store 标志不翻转；`提醒0` → `提醒1`：计数冻结）。真机端到端两路：① 盯盘开关点击后标签 `盯盘已开启 → 盯盘已暂停` 且发出状态 toast、再点可逆（验收断言增至 **34 条全通过 / 0 未验证**）；② 新探针在真后端构造 409（带外以当前 `revision` 为 base 的 PUT 使前端基线变旧）→ 前端 PUT 实测 409 → **冲突横幅出现**（`role="alert"`，三个按钮齐备）→ 点「采用服务器版本」后横幅消失、后续 persist 恢复 200（探针结束自动还原 `conflictPolicy`）。总览提醒的浏览器侧变化未构造场景 → 如实记为真机未覆盖。
- 约定钉死：`AGENTS.md`「关键约定」增「Pinia 解构纪律」条目（并点名这三处漏网，使代价可见）。

## [v0.7.1] - 2026-10-03

### 修复

- **定时任务不再静默失效**：`grid_scheduler.scheduler` 是模块级单例，而 APScheduler 3.x 的 executor 是一次性的——`shutdown()` 关闭底层线程池后不会再重建，同一进程内 `stop→start` 之后所有到期任务都会抛 `RuntimeError: cannot schedule new futures after shutdown`，且只落 ERROR 日志、任务静默不执行（扫描 / 日线 ETL / 行业预热 / 网格回测等于全灭）。现 `start_scheduler()` 在启动前摘掉旧 executor（`remove_executor("default", shutdown=False)`，并容忍首次启动的懒创建），由 `start()` 按原配置创建全新的默认 executor。生产单次启动行为不变。

### 自定义策略编辑器打磨（6 项）

- **`sort_by` 白名单**：`changePct` / `amount` / `turnoverRate` / `pe` / `pb`。未知字段此前会让 `pipeline._sort_key` 返回 `-inf`，排序静默退化为上游原序（不报错、结果不对）→ 现在存前中文 422 拦截。仅作用于策略配置，`/api/screener/v2` 的市场排序字段映射不受影响。
- **策略下拉 `custom` 角标**：自定义行渲染为 `自定义 · {名称}`，内置行不变。
- **删除 `useScreenerStore.customStrategies` 冗余状态**：合并列表（含 `custom` / `version`）是唯一数据源，保存/删除后只刷新 `loadStrategies()`。
- **fork 来源 `sourceBuiltin` 由 UI 提交**：「从内置复制」预填时记录来源内置 id；编辑既有 fork 策略时从单条 GET 回填并原样提交（此前 PUT 会把该列清空）。
- **合并列表读库失败补日志**：`screener_logger.warning("screener.custom_strategies_list_failed")`；列表仍照常返回内置行（绝不整体失败），但不再静默表现为「没有自定义策略」。
- **请求校验错误统一契约**：新增 app 级 `RequestValidationError` handler，请求模型/查询参数校验失败返回 `{"detail": {"error": 中文短句, "code": "VALIDATION_ERROR"}}`（此前是 FastAPI 默认的 `detail` 列表 + pydantic 英文样板，前端拿不到 `code`）。

## [v0.7.0] - 2026-10-03

### 设置页 Tushare Token 与跨源交叉校验开关

- 工作区设置新增 `tushareToken` 与三态 `crossCheckEnabled`（未设 = 跟随 env / 开 / 关）；**DB 显式值优先于 env**，页面开关即时生效（注册期 env 门改为运行时判定）。
- 设置 API 掩码透传 token（明文永不回显；缺省不覆盖既有值）；设置页新增 Tushare 行与「T0 对拍前启用有偏差」警告。
- `cross_check` 调度常驻注册，启用/停用不依赖进程重启。

### 自定义策略编辑器（研究体验 P3）

- 新表 `screener_custom_strategies`（Alembic 前向迁移）：服务端生成 `custom_<12hex>` id、`version` 乐观锁、`source_builtin` fork 来源。
- CRUD 四端点 + 合并策略列表（内置行字段零变化，自定义行加 `custom` / `version`）：单条 `UPDATE ... WHERE id AND version` 原子乐观锁 → 409 携带服务器最新行；DELETE 在单事务内复查扫描引用 + 返回引用快照 + 结构化日志（含完整 config 快照，硬删后可凭日志重建）；列表名称搜索 + 分页；单条 GET 按需返回 `scanReferences`。
- 校验加严：因子名 ∈ 7 因子白名单、`quick_filters` 字段白名单、因子 ≤ 20 条、`weight ∈ [0.01, 100]`、`threshold` 必须有限值且 |·| ≤ 1e6。
- `load_strategy` 内置优先 → 自定义 DB 兜底（管道/扫描零改动）；PUT/DELETE 后按 `screener:{id}:` 前缀主动失效进程内管道缓存（含 stale 副本）。
- 前端 `CustomStrategyDialog`：空白新建 / 「从内置复制」预填、粗筛 5 字段区间（留空 = 不设限）、≤20 因子行、名称描述文本插值（无 v-html）。

### 自定义策略编辑器审计硬化

- **空数值输入 = 未填**：`v-model.number` 清空数字框会回写 `''`，此前原样提交 → pydantic 英文 422。现区间两侧皆空则整键不发、有服务端默认值的字段省略键回落默认、因子 `threshold` 无默认值则前端中文内联拦截 + 后端中文 422；后端请求模型与配置模型同步归一，挡住直接 API 调用。
- **409 冲突保留本地编辑**：只刷新 `version` 并可重试（此前整体覆盖用户输入，且注释与行为相反）。
- **文本上界**：`name ≤ 64` / `description ≤ 256`（对齐 DB 列宽）→ 422；此前越界在真库 PG 会 DataError 被兜成 502。
- **422 文案中文化**：loader 校验器消息 + pydantic 首条错误映射为中文（形如「因子 #1 阈值：…」），`detail.code` 保持机器码，不再回显 pydantic 英文样板与文档链接。
- 补齐测试缺口：PUT/DELETE 缓存失效接线、删除日志含 config 快照、管道跑自定义 id 与内置等价（含缓存键隔离）、前端 422 展示与文本插值。

### 修复

- **部分构建产物不再让服务崩启动**：`frontend/dist` 存在但 `dist/assets` 缺失时（构建中断、或 Vite `emptyOutDir` 的建中窗口与运行中的服务/测试重叠），`create_app()` 会挂载不存在的目录而抛 `RuntimeError: Directory ... does not exist`，整个应用创建失败。现按 `dist/assets` 是否真实存在判定，缺失即回退源目录（与「无 dist」路径语义一致）。
- 该缺陷由并发 `npm run build` + pytest 暴露（测试套件在构建删目录的窗口内建 app 即整批失败），**不是仓库既有 flake**：`npm run verify` 本身不含 build，连续 3 次全绿。

### 工具链

- **行尾纪律**：新增 `.gitattributes`（`* text=auto eol=lf`）+ `.prettierrc.json` 显式 `endOfLine: lf`。修复「pre-commit 仓库级 prettier 钩子把 CRLF 工作区文件改写成 LF → git status 记为已修改而 git diff 为空（索引未变）→ 每次提交留脏文件、阻塞 `git flow feature finish`」。索引与工作区统一 LF，与 CI（ubuntu）及 prettier/ruff/eslint 输出一致。

## [v0.6.0] - 2026-10-03

### 交易辅助决策闭环（P0/P1 主线）

- **交易计划草案生成**：`POST /api/assist/plan-draft`（30 次/分钟滑窗限频 + 降级/stale 透传 + 涨停提示 + 观测日志）+ `PlanDraftDialog` 草案对话框（调参重算零 API、零股禁存、降级黄标、Kelly 半仓参考）+ 选股/详情/设置页入口。
- **仓位计算器**：建议股数 = 单笔风险%（默认 1%）× 账户权益 ÷ 止损距离，整手取整；账户权益与风险偏好为设置项，可选半凯利。
- **选股 → 回测联动**：命中行一键对该票跑回测引擎（参数预填）。
- **策略定时扫描 + 指令推送（P1）**：策略实验室每策略开关（quick/deep）+ 工作日 15:40 / 周末 10:00 自动扫描 → 提醒中心合成提醒（跌出再报去重）→ 点击重算草案 → 人工确认落计划。
- **计划绩效复盘（P1）**：bfq 原始价日线回放（反前视起点）→ 胜率/盈亏比/期望值 + 来源归因分组（scan/screener/monitor/manual）→ ViewPlans 绩效面板。
- **组合风险视图（P1，第 8 视图）**：自选 + 计划合计敞口、行业集中度、毛/净 NAV 双线、交易对与事件折叠区（`backend/portfolio_risk.py` 纯函数引擎）。

### 策略引擎泛化

- `strategy_base` 统一基类（signal_at 钩子 + 整手/手续费/T+1/权益曲线/基准指标）+ `strategies/` 六策略（双均线、MACD、布林带反转、唐奇安突破、动量、定投）+ 多因子（ADX 状态过滤 + 动态切换 + 僵局保护）+ 注册表 `strategy_engines`。
- `indicators.py` 技术指标库（BOLL/ATR/Donchian/Momentum/RSI/ADX + `closed_bars` 反前视截断）。

### 数据中台（P2 + P2.5）

- **全市场日线 ETL**（`bars_etl`）：水位时刻粒度/universe 并集/缺口四档/DQ 逐根拒收/空响应失败熔断自愈/三触发调度（交易日 15:20 日补、周六 10:30 审计、启动 60s 探测）；500 根 bfq、1500 码/日预算、3.3rps 节奏。
- **Redis CacheFacade 接管行情缓存**：前缀策略表白名单（quotes:/history:/minute:）、ts 封装判新鲜、熔断旁路、降级读；重启不再丢 warm-up。
- **受保护按需分钟线（P2.5）**：独立令牌桶 1rps / 熔断 900s / ETL 互斥 / 双缓存短 TTL 无降级读；详情页周期切换（1m–60m）与降级态呈现（黄标缓存、灰条+重试、429 toast）；`/api/health` 暴露 minuteCache/minuteCircuit。
- **跨源交叉校验（P2.5）**：Tushare daily 为主 / 东财 clist 为辅，日抽 30 码对账最新收盘；`CROSS_CHECK_ENABLED` 默认关，`health.bars.crossCheck` 观测位。
- 行业映射 `industry_map` 表 + 双层缓存（进程 TTL + 表）。

### P3 Point-in-time 日快照归档

- 四表（snapshot_runs/closes/industries/audits）+ ETL 后幂等归档：complete 快照不可变、失败记录不降级、PostgreSQL advisory lock 序列化同日变更。
- 行业回填 API：A→B→A 追加审计、相同重试幂等、exact 不可覆盖（409）、canonical SHA-256 + 有界样本摘要。
- **`asOfDate` 历史口径**：计划复盘与组合风险按"历史今天"走 PIT 快照路径——行情严格不跨日回退、停牌无前收分账、coverage（market/industry）驼峰如实披露；设计见 `docs/superpowers/specs/2026-09-18-p3-pit-snapshots-design.md`。

### 修复与工程

- `fix`: /api/health 分钟熔断态无参调用 TypeError（P2.5 引入的必现崩溃）及同期 mypy/eslint/prettier 门禁债归一。
- `test`: test_bars_etl_run 直连真实 PG 的泄库隔离（run_full 归档路径哑化）；pytest 临时根自愈（Windows 提权遗留 DACL 毒目录致 tmp_path 崩溃）。
- CI/pre-commit 全量钩子（mypy/eslint/prettier/vue-tsc）在每次提交强制执行。

## [v0.5.0] - 2026-09-04

### 多数据源架构

- **统一数据源接入层**：`DataSource` ABC + 能力位（realtime / history / screener / paged_screener / fundamental）+ `DataSourceRouter`（按设置选源 + 降级链，最多 3 层回退）。适配器：腾讯公开行情、东方财富实时行情、MockUS 美股模拟（`MOCK_US_ENABLED` 注册）。
- **正交组件**：`MarketCalendar` / `DataNormalizer` / `AssetMetadata` 三 ABC，各源自带交易日历与归一化实现。
- **行情来源设置**：`realtimeSource` / `historySource` / `screenerSource` / `fundamentalSource` + `fallbackEnabled`，设置页切换即时生效；`GET /api/sources` 列出各源能力位与可用性。

### 全市场选股器 Phase 2

- `/api/screener/v2` 接入 Router：按 `screenerSource` 选源（腾讯排名委托 / 东财 clist 原生 `pn/pz/fid/po` 分页排序），两源返回 shape 统一 `{total, page, pageSize, rows, provider}`。
- 前端「精选 50 / 全市场」双模式复用，行情来源切换在页面 provider 标签与来源列表即时体现。

### 策略选股管道（新功能）

- **混合管道**：API 粗筛（screener 能力）→ 本地因子精筛（history 能力，7 因子编排既有 indicators）→ 财务增强（fundamental 能力，top_n 补 ROE/市值/PEG）。
- **声明式策略**：`backend/screener/configs/*.json`（内置超跌反弹 / 趋势突破），pydantic 校验算子与边界。
- **生产级韧性**（五轮评审）：`reference_date` 截断 bars 杜绝未来函数（默认上一交易日）；缓存键 strategy×mode×market + 互斥锁双重检查防击穿；全源失败返回过期缓存（`stale: true`）；限频 = 池 max_workers=5 + min-interval 0.1s（≤10 req/s）+ 阶段 deadline 45s 部分结果；trace_id + stage_timings + counts 结构化观测。
- **API**：`GET /api/screener/strategies` + `POST /api/screener/strategy`（mode 默认 quick，绝不拉 history）。
- **前端**：选股器第三个标签页「策略」，极速/深度切换（默认极速）、评分表、达标因子标签、基准日期展示、stale 警告横幅。
- 观测脚本：`python scripts/observe_screener.py`。

### 修复

- 行情来源切换未体现在页面：provider 标签硬编码、`/api/history` provider 硬编码、测试 DB 设置污染三根因修复。
- 东财 K 线接口缺 `fields1`/`fields2` 返回空 `klines`（选股管道端到端验收时发现，补回归测试）。
- 测试隔离：8 处路由测试补 `get_workspace_settings` mock，杜绝 DB 设置跨测试污染。

## [v0.4.1] - 2026-08-30

### 工程化打磨

#### 性能
- lucide 图标按需导入（`frontend/src/modules/lucideIcons.ts`，45 个实际使用图标，PascalCase 键），构建产物 >500KB 降至 200.65 kB（gzip 65.40 kB），消除 Vite chunk 体积警告。

#### 部署
- **Docker 化部署**：`Dockerfile` multi-stage 构建（node:22-alpine 前端 + python:3.13-slim 后端）+ `docker-compose.yml`（postgres:16 / redis:7 / app 三服务，健康检查依赖）。
- `ARG REGISTRY` 支持镜像源覆盖（受限网络可用 `--build-arg REGISTRY=hub.rat.dev/library` 构建）；前端构建阶段复制根级 tsconfig/vite 配置；`HOST=0.0.0.0` 使容器端口映射生效。
- 宿主端口 5433/6380 避开本机已有 PostgreSQL/Redis；不挂载 `./frontend/dist` 避免遮蔽镜像内构建产物。

#### 测试
- 新增 **Playwright e2e** 冒烟测试（`e2e/smoke.spec.ts` 3 项：首页加载 / 导航菜单 / API 健康检查），`npm run test:e2e`。
- Chromium 浏览器二进制经 `PLAYWRIGHT_DOWNLOAD_HOST` 镜像源安装（国内网络可用）。

#### 依赖升级
- lucide `1.37.0` → `1.38.0`、APScheduler `3.10.4` → `3.11.3`、akshare `1.18.83` → `1.18.94`（minor 安全升级，全量验证通过）。
- eslint 10 / TypeScript 7 / alembic 1.19 列为待评估 major（破坏性风险，需独立分支验证），跟踪清单见 `ROADMAP.md`。

#### 文档
- 新增 `ROADMAP.md`：未来功能规划（全市场选股器 / 新策略类型 / 多数据源 / 多语言）+ 依赖升级跟踪。
- `OPERATIONS.md` 工程化工具链章节深化：npm scripts 对照表、CI job 明细、Docker 部署说明、依赖升级纪律。

### 修复
- Dockerfile 构建缺少根级 `tsconfig.json` / `vite.config.ts` 导致容器内 `vue-tsc` 失败 → 修复复制配置。
- 容器端口映射失效（`server.py` 默认绑定 127.0.0.1）→ `ENV HOST=0.0.0.0`。
- Playwright Chromium 下载超时（Google storage 不可达）→ 镜像源重装。

## [v0.4.0] - 2026-08-30

### 工程化

#### 工具链
- ESLint 9 flat config（typescript-eslint + eslint-plugin-vue），覆盖 `.ts` / `.vue`，0 error。
- Prettier 3 前端格式化，规则与 ESLint 无冲突。
- ruff check + format（line-length 120，select E/F/W/I/UP）替代原有 flake8 / isort / black。
- mypy 后端类型检查（`backend/` + `tests/`，strict-lite 配置）。
- pre-commit 钩子自动化：ruff --fix → ruff-format → mypy → eslint → prettier → vue-tsc --noEmit，提交前必过。
- pyproject.toml 统一 ruff/mypy/pytest 配置（覆盖率门禁 ≥80%）。
- npm scripts 收口：`npm run dev`（concurrently 双端）、`npm run build`（vue-tsc + vite build）、`npm run verify`（vitest + vue-tsc + pytest）、`npm run lint` / `npm run format`。

#### 前端迁移
- 从 Vue 3 全局构建 + 无构建工具迁移至 **Vite 8 + TypeScript 5.9 strict** 标准构建体系。
- `frontend/src/` 源码目录：main.ts / app.ts / App.vue + 7 个 SFC 独立视图（ViewSettings / ViewOverview / ViewMonitor / ViewScreener / ViewStockDetail / ViewGrid / ViewPlans）。
- vue-tsc 类型门禁：`npm run build` 与 `check:frontend` 均先执行 `vue-tsc --noEmit`。
- vitest 测试基建：jsdom 环境 + @vue/test-utils，10 个测试文件共 66 项测试（组件 + 模块）。

#### 状态管理
- 引入 **Pinia 4**，8 个领域 store 替代全局 `APP_CTX` provide/inject 模式：
  - useWorkspaceStore / useQuotesStore / useScreenerStore / useGridStore
  - useStrategyStore / usePlansStore / useAlertsStore / useSettingsStore
- 修复 `storeToRefs` 响应性丢失 2 个回归 bug（筛选器预设不渲染、计划列表不更新）。

#### 后端契约与迁移
- `backend/schemas.py` 新增 24 个 Pydantic 请求/响应模型类（+ WorkspacePutOut 别名，共 25 个模型名），替换所有 `payload: dict = Body(...)` 与裸 dict 返回，字段名逐字节不变。
- 20 个 `/api` 路由全量改造为 Pydantic 参数校验 + 响应模型注解。
- 引入 **Alembic 1.14** 迁移框架（`backend/migrations/`），创建 baseline 初始迁移，淘汰原生 `ALTER TABLE ... IF NOT EXISTS` 机制。
- 统一 API 错误契约：结构化错误码 + `api_error` 助手，前端 `error.code` 处理。

#### 测试
- 前端 vitest 66 项：format / chart / constants / planUtils / marketUtils / signalUtils / alertUtils 纯模块 + ViewPlans / ViewScreener / ViewSettings 组件测试。
- 后端 pytest 139 项 + pytest-cov 覆盖率门禁 ≥80%（实测 97.8%），覆盖：
  - api 路由全链路（正常 / 异常 / 边界）
  - grid_strategy 数学计算与基准/风险指标
  - grid_scheduler 调度逻辑与定时任务
  - schemas 模型校验
  - storage 持久化异常（升级覆盖至 lifespan 存储异常、策略增删 503/404、告警删除分支）
  - strategy_engines 四种策略引擎
  - settings API 与默认设置
- 补测发现的回归修复：lifespan 存储异常处理、策略增删 503/404 错误路径、告警删除分支覆盖。

#### CI
- **GitHub Actions** 三 job 门禁：
  - `backend`：ruff check + format-check → mypy → pytest（含 postgres:16 service）
  - `frontend`：vue-tsc → eslint → vitest
  - `build`：npm ci → npm run build → python server.py 启动 → curl 探测 `/api/health` 与首页

## [v0.3.4] - 2026-08-30

### 重构
- **P3-1 组件化拆分（方案 B）**：7 个视图全部从单文件大模板迁移为独立 Vue 3 组件（`ViewSettings` / `ViewOverview` / `ViewMonitor` / `ViewScreener` / `ViewStockDetail` / `ViewGrid` / `ViewPlans`），共享状态通过 `provide / inject` 上下文（`APP_CTX`）传递，`index.html` 从 704 行瘦身至 174 行骨架壳。
  - 网站设置布局优化（方案 A）：双标题去重、胶囊 / 下划线双层 tab、两栏对齐行、页面微抛光。
  - 消除矮窗口下突兀滚动条（间距收紧 + 精致细滚动条兜底）。

### 新增
- 行情缓存 TTL 硬下限（2s）与外部接口限频（默认 5 rps），选股器 v2 接入缓存。
- 统一 API 错误契约：结构化错误码 `code` + `api_error` 助手 + 前端 `error.code` 处理。

### 测试
- 前端纯函数模块（format / chart / constants）新增 `node:test` 单元测试。
- 后端测试增至 **75 项**，全量通过。

## [v0.3.3] - 2026-08-30

### 新增
- **统一策略实验室**：nav「网格策略」升级为「策略」，顶部支持网格 / 双均线 / 定投（DCA）/ MACD 四种策略类型切换，共用回测、权益曲线、指标卡、保存与每日调度基础设施。
  - 双均线：快线上穿慢线买入、下穿卖出，周期参数可调。
  - 定投（DCA）：每 N 个交易日固定金额投入，止盈 / 止损线全仓卖出，资金不足一手时滚入下一期。
  - MACD：DIF 上穿 DEA 买入、下穿卖出，含预热期（无信号不交易）。
  - 新增 `Strategy` / `StrategyBacktest` 通用存储表与 `/api/strategy/*` 端点，调度器泛化支持新策略每日 15:20 盘后回测。
- **独立个股详情视图**：全站任意列表（总览 / 选股 / 盯盘）点击股票进入独立详情页，含报价、走势图、自选、网格策略与制定计划入口；返回按钮回到来源视图。选股器视图不再有底部详情面板。
- 网格回测追加**胜率、最长回撤持续期、单格收益、利润因子**等风险指标。
- 全市场选股器：新增腾讯排名接口（约 4600 只），支持精选 / 全市场切换、分页、排序。
- 上游失败时走势图与回测**降级读取本地日线缓存**，前端显示来源角标（本地缓存 / 实时）。
- 通知中心：系统事件（冲突自愈、保存失败、行情降级）写入提醒中心，桌面通知按类型开关。

### 修复
- `profitFactor` 在全赢策略下返回 `inf` 导致 JSON 序列化失败，改为 `null`。
- 全市场选股面板贴边、表格过长问题（内边距 + 内部滚动）。
- 选股器强制跳回视图的体验问题（独立详情页来源返回）。

### 非功能
- 后端测试从 52 项增至 **68 项**（新增策略引擎与 API 测试），全量通过。

## [v0.3.2] - 2026-08-29

### 新增
- 提醒中心：系统事件持久化写入，底部导航角标统一计数，桌面通知按类型开关。
- 工作区冲突自愈：server / local / ask 三种策略，双标签页自我振荡修复。

## [v0.3.1] - 2026-08-2x

### 新增
- 交易计划、盯盘中心、价格触发扫描与桌面通知。
- 网格策略：区间测算、回测、参数优化、保存与每日调度。

## [v0.2.0] - 2026-08-1x

### 新增
- 选股器、交易总览、个人中心、工作区设置。

## [v0.1.0] - 2026-08-06

### 新增
- 初始版本：真实行情连接、自选与基础报价展示。