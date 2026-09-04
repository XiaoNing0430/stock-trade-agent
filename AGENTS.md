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
  data_source.py          Tencent 行情适配器 + 分类 + 请求/重试 + 运行时配置
  grid_strategy.py        网格策略计算：build_grid, suggest_grid, backtest_grid, optimize_grid（含基准/风险指标）
  grid_scheduler.py       APScheduler 封装，用于每日网格回测（Asia/Shanghai）
  schemas.py              24 个 Pydantic 请求/响应模型（+ 1 个别名）
  storage.py              SQLAlchemy 模型 + 持久化助手（10 张表）
  strategy_engines.py     通用策略引擎（网格, SMA, DCA, MACD）
  settings.py             pydantic-settings；环境变量（POSTGRES_*, REDIS_*, TUSHARE_TOKEN）
  migrations/             Alembic 迁移脚本（基线 + 前向迁移）
frontend/
  index.html              Vite 入口 HTML — 引用 /src/main.ts
  src/
    main.ts               Vue 应用启动（createApp, Pinia, 挂载）
    app.ts                Vue 应用设置、路由、轮询、错误处理
    App.vue               根布局 SFC
    styles.css            全部样式（CSS 变量，单文件）
    api/
      client.ts           类似 Axios 的 fetch 封装
    stores/               8 个 Pinia 状态仓库
      useWorkspaceStore.ts / useQuotesStore.ts / useScreenerStore.ts
      useGridStore.ts / useStrategyStore.ts / usePlansStore.ts
      useAlertsStore.ts / useSettingsStore.ts
    modules/              纯逻辑模块
      constants.ts / format.ts / chart.ts / planUtils.ts
      marketUtils.ts / signalUtils.ts / alertUtils.ts
    views/                7 个 SFC 视图
      ViewSettings.vue / ViewOverview.vue / ViewMonitor.vue
      ViewScreener.vue / ViewStockDetail.vue / ViewGrid.vue / ViewPlans.vue
    types/
      models.ts           TypeScript 类型定义
tests/
  test_backend_api.py     FastAPI 路由 + data_source 解析（含 HTTP 重试/退避、运行时配置）
  test_grid_strategy.py   网格策略计算（含基准/风险指标、候选稳健性）
  test_grid_scheduler_coverage.py
  test_settings_api.py    设置 API + 默认设置断言
  test_schemas.py         Pydantic 模型验证测试
  test_storage_coverage.py
  test_strategy_engines.py
  frontend/               10 个 vitest 测试文件（共 66 项测试）
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
npx vitest run                        # 前端单元测试（66 项，10 文件，jsdom + @vue/test-utils）
python -m pytest tests/ -v            # 后端测试（139 项，快速离线 monkeypatch 模式）
python -m ruff check backend tests server.py
python -m ruff format --check backend tests server.py
python -m mypy backend
pre-commit run --all-files            # 运行所有 pre-commit 钩子（ruff/mypy/eslint/prettier/vue-tsc）
```

注意：

- 后端 pytest 运行覆盖率（≥80% 门禁，当前 97.8%）。
- Pre-commit 钩子（`ruff --fix` / `ruff-format` / `mypy` / `eslint` / `prettier` / `vue-tsc --noEmit`）在 `git commit` 时自动执行。
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

### 提交信息约定

- **主题行（第一行）必须使用中文。**
- 使用 Conventional Commits 类型前缀（`feat` / `fix` / `refactor` / `perf` / `test` / `docs` / `chore`），可选后接中文主题。
  - 例如：`feat: 新增全市场选股与分页`, `fix: 修复计划有效期过期逻辑`, `docs: 完善 AGENTS.md`.
- 正文（可选）建议使用中文——说明变更内容及原因。
- 每次提交对应一个逻辑变更；保持提交小巧可审查。

## 存储与数据说明

- PostgreSQL 存储自选股、交易计划、提醒、网格策略/回测、行情 K 线和工作区设置。Redis 仅用于 `storage_status()` 的 ping 检测；实际行情缓存是 `data_source.py` 中的内存 `dict`。HTTP 超时/重试/缓存 TTL 由工作区设置通过 `data_source.apply_runtime_config(...)` 驱动（默认：TTL 8s，超时 10s，重试 1 次）。
- 选股器自 v0.5.0 起为全市场分页排序（`/api/screener/v2` 按 `screenerSource` 选源）+ 策略选股管道（`backend/screener/`）；`REAL_UNIVERSE` 仍用于「精选 50」标签。
- 数据库迁移使用 **Alembic**（`backend/migrations/`）。基线迁移在 `c1a08e78583e_baseline_schema.py`。新增迁移通过 `alembic revision --autogenerate -m "描述"` 生成，提交前检查生成的脚本。

## 何时询问

在以下情况应停止并询问，而非猜测：原始测试/验证失败、指令不明确、即将超出当前阶段的非目标（无券商集成 / 自动下单、无 UI 重构；完整清单见 `ROADMAP.md` 非目标）、或 git 状态异常。