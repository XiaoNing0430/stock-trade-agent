# AGENTS.md

AI 编码代理在此仓库中工作的指引。

## 项目简介

**Atlas 交易工作台** — 一个本地单用户的 A 股研究与交易辅助工作台 Web 应用。实时行情驱动选股器、策略选股管道、交易计划、价格触发盯盘中心和网格策略回测。定位是**交易辅助决策工具，非自动执行系统**：生成建议交易指令（计划草案：入场/止损/目标/建议仓位）供用户人工执行；从不连接券商，从不自动下单。

UI 使用中文。除非任务另有说明，新用户可见字符串保持中文。

## 技术栈

- **前端：** Vue 3 + TypeScript 5.9 (strict) + Vite 8 + Pinia 4 + vitest 4 + @vue/test-utils + lucide。源码位于 `frontend/src/`（stores/, modules/, views/, types/, api/, app.ts, main.ts, App.vue）。由 Vite 构建，通过 Vite 开发服务器或静态文件提供服务。
- **后端：** Python / FastAPI + SQLAlchemy 2.0 + Pydantic v2 + Alembic 1.14（迁移脚本在 `backend/migrations/`）+ APScheduler（网格回测调度）+ ruff + mypy + pytest-cov。
- **数据源：** 腾讯公开行情（`qt.gtimg.cn`, `web.ifzq.gtimg.cn`）与东方财富（适配器在 `backend/sources/`，`DataSourceRouter` 按能力位路由 + 降级链）；MockUS 美股模拟按 `MOCK_US_ENABLED` 注册。
- **配置：** `.env`（Git 忽略）基于 `.env.example` 创建。

## 数据库直连

应用启动时通过 `.env` 环境变量直接连接 PostgreSQL 与 Redis：

- `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` — PostgreSQL 连接信息（默认 `127.0.0.1:5432`，库名 `stock_trade_agent`）。
- `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` / `REDIS_DB` — Redis 连接信息（默认 `127.0.0.1:6379`，db 15）。

若 PostgreSQL 或 Redis 不可达，服务仍可启动：后端在 `/api/health` 中如实报告存储状态（`database` / `redis` 为 `false`），不会伪造可用性。前端在服务不可达时保留浏览器缓存，恢复后自动同步。

## 项目布局

```
server.py                 开发入口 — 在 127.0.0.1:4173 启动 uvicorn
backend/
  app.py                  FastAPI 应用，所有 /api 路由，提供前端静态资源
  main.py                 python -m backend.main 入口
  data_source.py          数据源门面：适配器接线 + 分类 + 请求/重试 + 运行时配置 + cached 三级（L1→L2→上游）
  bars_etl.py             全市场日线 ETL：水位/universe/缺口四档/DQ 拒收/熔断自愈/三触发调度（bfq 500 根）
  snapshot_archive.py     P3 PIT 日快照归档：ETL 后幂等落库（complete 不可变/失败记录不降级/仅当日归档 exact 行业）
  snapshot_query.py       PIT 快照统一查询：行情/行业覆盖判定（驼峰 coverage）、load_archived_bars、asOfDate 路径
  minute_path.py          受保护按需分钟线：令牌桶 1rps/熔断 900s 半开/ETL 互斥/双缓存/L1 逐出（不落库不轮询）
  cross_check.py          日线最新收盘跨源校验（Tushare 主/东财辅；启用=设置页三态开关或 env CROSS_CHECK_ENABLED，默认关）
  redis_cache.py          CacheFacade：Redis L2（前缀策略表白名单、ts 封装、熔断旁路）
  grid_strategy.py        网格策略计算：build_grid, suggest_grid, backtest_grid, optimize_grid（含基准/风险指标）
  grid_scheduler.py       APScheduler 封装，用于每日网格回测（Asia/Shanghai）
  plan_review.py          计划绩效复盘：设计口径日线回放引擎（窗口/微结构/聚合，只读，零写 plans；支持 asOfDate）
  portfolio_risk.py       组合风险引擎：交易对 build_links、名义额静态分配回放、四档 exitMode、NAV 双线、聚合（纯函数，只读）
  industry_map.py         行业映射双层缓存（进程 TTL + industry_map 表；API 只读缓存，预热走后台 job；
                          连接级有界重试 + 整轮不完整时 30 分钟提前补跑 + `/api/health.industry` 观测位）
  indicators.py           技术指标库（MA/EMA/BOLL/ATR/Donchian/Momentum/RSI/ADX + closed_bars 反前视截断）
  strategy_base.py        策略基类：signal_at 钩子 + 统一整手/手续费/T+1/权益曲线/基准指标
  strategy_engines.py     策略注册表（按 id 登记，供 API 与调度器调用）
  strategies/             内置策略实现（ma_cross/macd/bollinger/donchian/momentum/dca，继承 strategy_base）
  multi_factor.py         多因子策略（ADX 状态过滤 + 动态切换 + 僵局保护）
  screener/               策略选股管道：pipeline/factors/scan/loader + configs/*.json 声明式策略
  assist/                 交易辅助：build_plan_draft 草案服务 / 单笔风险 calculator / 滑窗限频 limiter
  sources/                数据源适配器（tencent/eastmoney/mock_us + base/router/cn_impl 日历与归一化 + guard 节流/熔断护栏）
  schemas.py              30 个 Pydantic 请求/响应模型
  storage.py              SQLAlchemy 模型 + 持久化助手（18 张表，含 4 张 PIT 快照表与 screener_custom_strategies）
  settings.py             pydantic-settings；环境变量（POSTGRES_*, REDIS_*, TUSHARE_TOKEN, MOCK_US_ENABLED, CROSS_CHECK_ENABLED）
  migrations/             Alembic 迁移脚本（基线 + 前向迁移，最新 p3pit20260918 PIT 快照四表）
frontend/
  index.html              Vite 入口 HTML — 引用 /src/main.ts
  src/
    main.ts               Vue 应用启动（createApp, Pinia, 挂载）
    app.ts                Vue 应用设置、路由、轮询、错误处理
    App.vue               根布局 SFC
    styles.css            全部样式（CSS 变量，单文件）
    components/
      PlanDraftDialog.vue  交易计划草案对话框（调参重算 → 确认落计划）
      CustomStrategyDialog.vue  自定义选股策略编辑器（粗筛区间 + ≤20 因子行 + fork 内置；409 保留本地编辑仅刷新 version）
    api/
      client.ts           类似 Axios 的 fetch 封装
    stores/               12 个 Pinia 状态仓库
      useWorkspaceStore.ts / useQuotesStore.ts / useScreenerStore.ts
      useGridStore.ts / useStrategyStore.ts / usePlansStore.ts
      useAlertsStore.ts / useSettingsStore.ts / useAssistStore.ts
      useScanStore.ts / useReviewStore.ts / usePortfolioStore.ts
    modules/              纯逻辑模块
      constants.ts / format.ts / chart.ts / planUtils.ts
      marketUtils.ts / signalUtils.ts / alertUtils.ts
      assistCalc.ts（草案试算） / lucideIcons.ts（图标注册表）
    views/                8 个 SFC 视图
      ViewSettings.vue / ViewOverview.vue / ViewMonitor.vue
      ViewScreener.vue / ViewStockDetail.vue / ViewGrid.vue / ViewPlans.vue
      ViewPortfolio.vue  组合风险（第 8 视图：毛/净 NAV 多线、敞口/集中度、交易对与事件折叠区）
    types/
      models.ts           TypeScript 类型定义
tests/
  test_backend_api.py     FastAPI 路由 + data_source 解析（含 HTTP 重试/退避、运行时配置）
  test_grid_strategy.py   网格策略计算（含基准/风险指标、候选稳健性）
  test_grid_scheduler_coverage.py
  test_settings_api.py    设置 API + 默认设置断言
  test_schemas.py         Pydantic 模型验证测试
  test_storage_coverage.py
  test_scan.py            策略扫描去重引擎 + 编排护栏 + 扫描 API
  test_plan_review.py     计划复盘：source 存取 + bfq 链路 + 回放引擎 + 聚合 + API 端点
  test_portfolio_engine.py   组合回放引擎：core 状态机 + 闭环 exitMode 矩阵 + 复盘微结构等价（equiv 场景）
  test_portfolio_aggregate.py 聚合层：KPI/敞口/行业集中度/信号看板/自选观察指数/假想线
  test_portfolio_api.py   存储校验（交易对五规则/exitMode 白名单）+ /api/portfolio/risk 端点
  test_industry_map.py    行业映射双层缓存：fresh/stale/empty 判定 + 整表 min() 时龄 +
                          连接级有界重试/完成标记/日志降噪/health 聚合
  test_bars_etl.py        全市场日线 ETL 核心：水位时刻粒度/universe 并集/缺口四档/调度注册/health 位
  test_bars_etl_run.py    ETL 执行流：空判失败熔断/DQ 拒收矩阵/SAVEPOINT 隔离/no_new_bar/自愈队列/护栏/互斥/公平序
  test_redis_cache.py     CacheFacade（fake redis+假时钟全离线）：白名单/PX 随动/严格序列化/熔断仅计客户端
  test_cached_facade.py   cached()×门面接线：L2 回填/写穿/降级真实 age/screener 零触达/quotes 键归一
  test_minute_path.py     受保护分钟线：令牌桶/熔断半开/ETL 互斥/L1 逐出/降级态矩阵
  test_p3_snapshots.py    P3 PIT 快照：状态映射/停牌无前收/审计幂等与哈希/回填冲突/asOfDate 接入
  test_custom_strategies.py 自定义选股策略：CRUD/原子乐观锁/事务删除引用快照/白名单与资源上界/扫描联动/
                          空值归一与中文 422/缓存失效接线/管道自定义 id 等价/删除日志快照
  test_screener_loader.py 声明式策略配置加载：内置 config 合法性 + 算子/因子/上界拒收
  test_source_guard.py    上游护栏与运行时降级：节流/连败熔断/半开单探测 + 降级链有序 + 东财快速失败
  conftest.py             逐用例隔离 L2 facade + pytest 临时根自愈（提权遗留毒目录回退 .pytest_tmp，离线纪律）
  test_strategy_engines.py
  frontend/               21 个 vitest 测试文件（共 236 项测试）
docs/superpowers/         文档/计划（设计及实现文档）
.worktrees/                git worktrees（Git 忽略）
```

## 运行应用

应用支持**双轨**运行：

### 开发模式（热重载）

```powershell
# 从仓库根目录执行。需要 PostgreSQL + Redis 可达（见 .env）。
npm run dev
```

同时启动 Vite 开发服务器（`:5173`，前端 HMR）和 FastAPI 后端（`:4173`，API）。前端将 `/api` 请求代理到后端。

打开 <http://127.0.0.1:5173>。API 文档位于 <http://127.0.0.1:4173/docs>。

### 生产模式（静态构建）

```powershell
npm run build       # 先执行 vue-tsc --noEmit 类型检查 + vite build → 输出到 frontend/dist/
python server.py    # 或 python -m backend.main
```

`npm run build` 执行 `vue-tsc --noEmit`（类型检查）+ `vite build` → 输出到 `frontend/dist/`。FastAPI 后端在 `:4173` 提供静态构建。

打开 <http://127.0.0.1:4173>。

**兼容性：** 若 `frontend/dist/` 不存在，`python server.py` 回退到提供原始 `frontend/` 源文件——但这需要 Vite 开发服务器单独运行前端才能正常。没有 `dist/` 或 `npm run dev` 时，前端不可用（后端 API 仍可工作）。

`.env` 被 Git 忽略。首次运行前复制 `.env.example` 为 `.env`，填写 `POSTGRES_*` / `REDIS_*`。切勿提交真实凭据。

## 测试

```powershell
npm run verify                        # 完整回归：vitest + vue-tsc + pytest
npx vitest run                        # 前端单元测试（236 项，21 文件，jsdom + @vue/test-utils）
python -m pytest tests/ -v            # 后端测试（665 项，monkeypatch 离线为主；test_bars_etl*.py 直连真实 PG）
python -m ruff check backend tests server.py
python -m ruff format --check backend tests server.py
python -m mypy backend
pre-commit run --all-files            # 运行所有 pre-commit 钩子（ruff/mypy/eslint/prettier/vue-tsc）
```

注意：

- 后端 pytest 运行覆盖率（≥80% 门禁，当前 93.0%）。
- `test_bars_etl.py` / `test_bars_etl_run.py` 设计为直连真实 PG（自造数据须 teardown 自清；`test_bars_etl_run.py` 的 autouse 夹具已哑化 run_full 的快照归档路径——**勿移除**，否则每次跑测试都会向真库写假水位快照）。
- Pre-commit 钩子（`ruff --fix` / `ruff-format` / `mypy` / `eslint` / `prettier` / `vue-tsc --noEmit`）在 `git commit` 时自动执行；mypy/eslint/prettier/vue-tsc 为仓库级全量钩子，任一历史文件不达标都会阻塞所有提交。
- `npm run build` 也会在 Vite 打包前执行 `vue-tsc --noEmit` 作为类型检查门禁。

## 关键约定 / 规则

- **绝不使用模拟值填充缺失数据。** 前端显示 `--` / 空状态代替。行情失败必须展现为缓存/过期/错误状态，绝不出造价格。
- **保留现有 API 字段名。** 新增字段可接受；重命名/删除会破坏 Vue 前端。
- **时间戳：** 标准机器时间戳为 `createdAtMs` — 自 epoch 开始的**毫秒数**（前端 `Date.now()`，后端 `int(created_at.timestamp() * 1000)`）。`createdAt` 是显示便利字符串（`HH:MM`）。使用 `formatTime(ms)` 格式化显示。
- **计划 `status` 值：** `执行中`、`已触发`、`已过期`、`已归档`。前端 `activePlans` 仅显示 `执行中`/`已触发`。
- **价格触发语义方向感知：** 对于 `buy` 计划，`price <= stop`（止损）且 `price >= target`（止盈）；对于 `sell` 计划（已持仓），`price >= target`（止盈卖出）且 `price <= stop`（止损卖出）。
- **网格回测假设保守且已披露**（T+1、100 股整数倍、最低佣金、股票卖出印花税、过户费、滑点、涨跌停限制、停牌；70/30 训练/验证拆分）。请勿将回测结果视为未来收益。
- **通过 `classify_code()` 分类交易品种**（交易所 / 板块 / 证券类型）。涨跌幅限制因板块而异（北交所 30%，创业板/科创板 20%，其他 10%）。
- **显式 `any` 是接受的约定**，用于前端 `frontend/src/` 中来自外部 API 的动态行情结构（`eslint.config.js` 设置了 `@typescript-eslint/no-explicit-any: 'off'`）。保持类型面尽可能窄；新代码优先使用精确类型。
- **安全性：** XSS 敏感点为 `showToast`（必须使用 `textContent`）和 `chartSvg`（必须使用 `escapeHtml` 转义插值标签）。保持此纪律。
- **前端轮询** 由 `armRefreshTimer()` 驱动，遵循 `settingsDraft.refreshInterval`；`refreshAll()` 通过 `refreshInFlight` 防止并发运行。
- **工作区同步修订锁定：** `GET /api/workspace` 返回 `revision`；`PUT /api/workspace` 接受 `baseRevision`（冲突 → 409，`detail.workspace` 包含服务器快照）和 `force=true` 覆盖。前端在 `workspaceRevision` 中维护最新已知修订，通过 `settingsDraft.conflictPolicy` 解决 409：`server`（默认）自动采用服务器快照，`local` 自动强制保存本地版本，`ask` 显示冲突横幅"采用服务器版本" / "用本地覆盖"——绝不自动重试 409。
- **网格回测日线分类：** 停牌 = `volume <= 0`。一字板（`high == low`, volume > 0）在涨停时仅可卖出，跌停时仅可买入。计数器：`onePriceLimitUpDays` / `onePriceLimitDownDays`（新增指标字段，累加性）。
- **自定义选股策略输入语义（2026-10-03 硬化）：** 数字输入留空（Vue `v-model.number` 回写 `''`）= **未填**，绝不猜数：区间两侧皆空即「不设限」整键不发；`topN`/`deepCap`/因子 `period`/`weight` 省略键回落服务端既有默认；因子 `threshold` 无默认值 → 前端中文内联拦截不提交、后端中文 422。后端 `ScreenerStrategyConfig` 对 `''` 做同样归一，挡住直接 API 调用。422 `detail.error` 面向用户须为中文（`detail.code` 保持机器码 `VALIDATION_ERROR`）。
- **API 错误契约统一（2026-10-03 打磨批）：** 所有错误响应（含 FastAPI 请求模型/查询参数校验失败）一律 `{"detail": {"error": 中文短句, "code": 机器码}}`；请求校验失败由 app 级 `RequestValidationError` handler 转换，`detail` 不再是对 pydantic 错误列表。新增端点请沿用 `api_error(...)`，不要自己拼错误形状。
- **策略配置白名单（挡在保存前）：** 因子 `name`（7 因子）、`quick_filters` 字段（5 个）、`sort_by`（`changePct`/`amount`/`turnoverRate`/`pe`/`pb`）均为白名单，未知值存前 422——这些字段写错时管道会因行值缺失或 `_sort_key` 返回 `-inf` 而**静默失效**（不报错、结果不对）。
- **运行时降级与上游护栏（2026-10-03）：** `fallbackEnabled` 是**请求期**真实降级——`/api/market`、`/api/screener`、`/api/screener/v2` 走 `_call_with_source_fallback`：首选源运行时失败即按 `source_chain()` 依次换**真实源**，响应以 `fallbackUsed` + `failedSources` 如实披露（`provider` 为实际应答源）；关掉开关则只试首选、失败如实 502。**别把「选源期可用」当请求期降级**（旧实现只在选源时换源，东财被 reset 就整体 502）。东财 `push2` 域另有护栏：12ms 级最小间隔 + 连接级连败 3 次熔断 300s（半开单探测），熔断期快速失败（`SourceCircuitOpen`，不打上游）；`HTTPError` 说明链路正常，不计入熔断。
- **`available` 是声明位、不是连通性：** `DataSource.available` 只表示"已注册且 token/依赖满足"（东财/腾讯硬编码 `True`）。设置页必须显示为「已注册 · 未探测连通性」+ 运行时 `circuit`（closed/open/half-open），**禁止**再写成"连接可用"；`/api/health.sourceCircuits` 暴露各源熔断态。
- **`asOfDate` 历史口径（P3 PIT）：** 复盘/组合风险接受 `asOfDate`（"历史今天"，须为不晚于今天的交易日）：行情/行业走 PIT 快照路径，**严格不跨日回退**，缺失按 complete/degraded/no-run/failed 如实披露，绝不向前回补造数；行业快照最多回溯 20 个交易日，`pit_quality` 优先于距离，`inferred` 永远是 historical_fallback 且不可覆盖 `exact`；历史缺口只能显式回填（写审计）。
- **分钟线受保护语义：** 分钟线仅自选/详情单码、用户手动触发；不落库、不进 ETL、不自动轮询全自选。独立令牌桶 1rps/burst 3（与日线节流隔离）、上游 3 败熔断 900s、501 单次即熔断、5xx 零重试、短 TTL（L1 15s / L2 120s）**无陈旧降级读**。降级态文案见 spec §6（`etl_busy`/`circuit_open`/`unavailable` 灰条、429 toast）。

## Git 工作流 — Git Flow（强制）

**仓库要求使用 Git Flow。所有功能 / 发布 / 修复工作必须通过 Git Flow 分支进行。**

- 分支：`main`（发布，带标签）、`develop`（集成）、`feature/*`（从 `develop` 拉出）、`release/*`、`hotfix/*`。
- 绝不直接向 `main` 或 `develop` 提交功能工作——从 `develop` 创建 `feature/*`，然后 `git flow feature finish`。
- 命令（`git-flow-avh`）：
  - `git flow feature start <name>`（基于 `develop`）
  - ... 完成工作 + 提交 ...
  - `git flow feature finish <name>`（`--no-ff` 合并到 `develop`）
  - `git flow release start v0.x.y` / `git flow release finish v0.x.y`（合并到 `main` + 打标签 + 同步 `develop`）
- `git flow init` 需要**干净的工作树**——先暂存未提交的更改。
- 本工具链无法直接执行 git 命令——请自行运行 git 命令并在报告时粘贴输出。
- **行尾纪律（2026-10-03 修复）：** 仓库以 `.gitattributes` 钉死 `* text=auto eol=lf`（`.prettierrc.json` 亦显式
  `endOfLine: "lf"`）。背景：本机 `core.autocrlf=true` 且无 `.gitattributes` 时，pre-commit 的**仓库级** prettier
  钩子（默认 `endOfLine=lf`）每次提交都会把 CRLF 工作区文件改写成 LF；git 随后把「待行尾转换」记为已修改但
  `git diff` 为空（索引内容未变、`git update-index --refresh` 报 `needs update`），于是每次提交后都留下脏文件，
  阻塞 `git flow feature finish`。修复后索引与工作区同为 LF，prettier/ruff/eslint 输出与 CI（ubuntu）一致。
  新克隆无需额外配置；若某个历史工作区仍有 CRLF 文件想一次性转 LF：
  `git ls-files | % { Remove-Item -LiteralPath $_ -Force }; git checkout -- .gitattributes; git checkout -- .`

### 提交信息约定

- **主题行（第一行）必须使用中文。**
- 使用 Conventional Commits 类型前缀（`feat` / `fix` / `refactor` / `perf` / `test` / `docs` / `chore`），可选后接中文主题。
  - 例如：`feat: 新增全市场选股与分页`, `fix: 修复计划有效期过期逻辑`, `docs: 完善 AGENTS.md`.
- 正文（可选）建议使用中文——说明变更内容及原因。
- 每次提交对应一个逻辑变更；保持提交小巧可审查。

## 存储与数据说明

- PostgreSQL 存储自选股、交易计划、提醒、网格策略/回测、行情 K 线、行业映射、PIT 日快照（snapshot_runs/closes/industries/audits）和工作区设置。Redis 承担两类职责：`storage_status()` ping 检测 + `redis_cache.CacheFacade` 行情 L2 缓存（`data_source.cached` 三级 L1 dict→L2→上游；前缀策略表白名单：`quotes:`/`history:` 走全局路径，`minute:` 120s 窗且**无降级读**，`screener_v2:` 刻意不入 L2；连接失败=down facade，行为与无 Redis 时逐字一致；熔断 3 败/30s 旁路，物理 TTL≥1860s 保降级读）。**全市场日线 bfq 由 `bars_etl` 后台 ETL 落库**（启动 60s 探测自愈 + 交易日 15:20 日补 + 周六 10:30 审计；500 根深回补受腾讯 ifzq ~1500 持续请求 501 全 IP 惩罚窗约束，1500 码/日预算跨数日消化，ETL 专属 3.3rps 节奏）；**ETL 完成后 `snapshot_archive` 幂等归档当日 PIT 快照**（覆盖不足 95% 或有失败码 → degraded 如实披露）；`/api/health.bars` 暴露水位/新鲜数/universe/最后运行/abortReason/crossCheck。HTTP 超时/重试/缓存 TTL 由工作区设置通过 `data_source.apply_runtime_config(...)` 驱动（默认：TTL 8s，超时 10s，重试 1 次）。
- 选股器自 v0.5.0 起为全市场分页排序（`/api/screener/v2` 按 `screenerSource` 选源）+ 策略选股管道（`backend/screener/`）；`REAL_UNIVERSE` 仍用于「精选 50」标签。
- 数据库迁移使用 **Alembic**（`backend/migrations/`）。基线迁移在 `c1a08e78583e_baseline_schema.py`。新增迁移通过 `alembic revision --autogenerate -m "描述"` 生成，提交前检查生成的脚本。

## 何时询问

在以下情况应停止并询问，而非猜测：原始测试/验证失败、指令不明确、即将超出当前阶段的非目标（无券商集成 / 自动下单、无 UI 重构；完整清单见 `ROADMAP.md` 非目标）、或 git 状态异常。