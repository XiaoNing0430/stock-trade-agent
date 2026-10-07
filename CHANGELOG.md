# Changelog — Atlas Trading Desk

All notable changes to this project. 版本更新清单。

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