# 全栈完整标准工程化 — 设计

## 背景与目标

Atlas Trading Desk 当前是"功能扎实、工具链空白"的状态：前端无打包器、无类型系统、无组件测试；后端无 lint、无类型检查、无迁移框架、API 契约裸 `dict`。用户目标：**改造为完整标准的工程化项目（前后端）**，同时保持既有功能与 API 字段名不变。

本设计打破 `AGENTS.md` 中"前端无打包器、后端 prefer 原生 ALTER TABLE"两条既有约定（用户已明确授权），并同步更新文档。

## 关键决策（已确认）

| 决策 | 选择 |
|------|------|
| 执行策略 | 规划一次、分批落地（Git Flow 多分支） |
| TypeScript | **纳入，一次到位**（随 Vite+SFC 迁移） |
| 分支粒度 | 6 个中型分支，逐个可独立 review/回滚 |
| 运行模式 | dev/prod 双轨（Vite HMR / FastAPI 托管 dist） |
| 一键启动 | `npm run dev`（concurrently 聚合前后端） |
| 锁文件 | **提交 `package-lock.json`**（反转早前"不加锁"决定；Vite 生态依赖多、CI 必须可复现） |
| 后端迁移框架 | **引入 Alembic**（改写 AGENTS.md 原生 ALTER TABLE 约定；现有 schema 用 baseline 迁移） |
| 后端 API 契约 | **全部 Pydantic 模型化**（请求 + 响应，字段名不变） |
| 后端类型检查 | 引入 mypy（reasonable 严格度） |
| 测试门禁 | 前端 vitest（node:test 迁移 + 组件测试）；后端 pytest-cov ≥80% |
| 文档 | AGENTS.md / OPERATIONS.md / README / CHANGELOG 全量同步 |

## 现状快照（2026-08-30）

- 前端：`frontend/index.html`（174 行壳）+ `app.js`（1752 行巨型 `setup()`）+ `styles.css`（3677 行）+ `modules/`（constants/format/chart 纯函数）+ `views/View*.js`（7 个组件，87–264 行，`provide/inject APP_CTX` 模式）+ `vendor/`（vue.global.prod.js + lucide.min.js）。FastAPI 直接静态服务 `frontend/`。
- 后端：`backend/app.py`（396 行，17 个路由，全部裸 `dict = Body(...)` 与裸 dict 返回）+ `settings.py`（pydantic-settings）+ `storage.py`（SQLAlchemy + 原生 ALTER TABLE 迁移）+ `grid_strategy.py` / `strategy_engines.py` / `data_source.py` / `grid_scheduler.py`。
- 测试：后端 75 项 pytest（离线 monkeypatch，无需 DB/Redis 实连）；前端 26 项 node:test（`node --test "tests/frontend/*.test.js"`）。
- **已发现真实 bug**：文档中 `node --test tests/frontend/`（尾斜杠）在 Windows 报错，正确写法为 glob——命令收口时修复。
- 工具：Node v22.17.0 / npm 10.9.2 / Python 3.13.5 / git-flow-avh 1.12.3。
- 远端：github.com/XiaoNing0430/stock-trade-agent。

## 目标架构

### 前端目录结构

```
frontend/
  index.html                Vite 入口（最小壳：#app 挂载点 + src/main.ts）
  vite.config.ts            Vite + @vitejs/plugin-vue + 别名 @ + proxy /api
  tsconfig.json             strict
  package.json              scripts + dependencies
  package-lock.json         提交（锁定依赖）
  src/
    main.ts                 createApp + 全局样式 + lucide 初始化
    App.vue                 主壳（sidebar/topbar/notif/footer/视图切换）
    styles.css              全局样式（自现 styles.css 迁入）
    modules/                constants.ts / format.ts / chart.ts
                            planUtils.ts / marketUtils.ts / signalUtils.ts / alertUtils.ts
    composables/            useWorkspace / useQuotes / useScreener / usePlans /
                            useAlerts / useSettings / useGrid / useStrategy
    views/                  ViewOverview / ViewMonitor / ViewScreener / ViewStockDetail /
                            ViewGrid / ViewPlans / ViewSettings（.vue）
    types/                  models.ts（Quote/Plan/Alert/Strategy…，与后端 Pydantic 契约一致）
    api/                    client.ts（fetch 封装，替换 requestJson）
  dist/                     Vite 构建产物（gitignored）
tests/
  frontend/                 vitest 测试（*.test.ts）
```

### 运行模式（双轨）

| 模式 | 命令 | 访问 |
|------|------|------|
| 开发（一键） | `npm run dev` | http://127.0.0.1:5173（HMR，`/api` 代理 :4173） |
| 开发（手动分启） | `python server.py` + `npm run dev:frontend` | 同上 |
| 交付/单进程 | `npm run build` → `python server.py` | http://127.0.0.1:4173 |
| 兼容 | `python server.py`（无 dist 时回退源码服务） | http://127.0.0.1:4173 |

### 后端目录结构（增量）

```
backend/
  schemas.py                Pydantic 请求/响应模型（全部路由）
  migrations/               Alembic（env.py 接现有 engine）
alembic.ini
pyproject.toml              ruff / mypy / pytest / coverage 统一配置
requirements-dev.txt        ruff / mypy / pytest / pytest-cov / pre-commit / alembic
```

## 分支计划（6 分支，依次 merge 到 develop）

```
develop ─► feature/eng-toolchain ─► develop   ① 前后端规范工具链
        └► feature/eng-vite ──────► develop   ② 前端 Vite+TS+SFC 迁移 + FastAPI dist 适配
        └► feature/eng-refactor ─► develop   ③ 前端拆分（composables+纯逻辑）
        └► feature/eng-backend ──► develop   ④ 后端 Pydantic + Alembic
        └► feature/eng-test ─────► develop   ⑤ 前端 vitest + 后端覆盖率
        └► feature/eng-ci ───────► develop   ⑥ CI 全栈门禁 + 文档收口
```

### ① eng-toolchain — 前后端规范工具链

**前端**
- ESLint 9 flat config（`eslint.config.js`）：`globals` 含 browser/node，`Vue` 全局声明 readonly。
- Prettier 3（`.prettierrc.json` + `.prettierignore`）；全量格式化独立 commit。
- `package.json` scripts 收口（此时仍是 JS 结构）：

```json
"scripts": {
  "test:frontend": "node --test \"tests/frontend/*.test.js\"",
  "check:frontend": "node --check frontend/app.js",
  "test:backend": "python -m pytest tests/",
  "lint": "eslint . && ruff check .",
  "verify": "npm run test:frontend && npm run check:frontend && npm run test:backend"
}
```

- 修复 `node --test` 尾斜杠 bug（统一 glob 写法，同步文档）。

**后端**
- `pyproject.toml`：ruff（line-length 120，target py313，E/F/W/I/UP 规则集）+ mypy（reasonable：显式导出检查、忽略缺失 stub）+ pytest + coverage。
- 全量 `ruff check --fix` + `ruff format` 独立 commit；mypy 全量标注修复，`backend/` 与 `tests/` 均过。

**pre-commit（`.pre-commit-config.yaml`）**
1. ruff check --fix
2. ruff format
3. mypy
4. eslint --fix
5. prettier --write
6. node --check frontend/app.js

**交付物**：eslint.config.js、.prettierrc.json、.prettierignore、pyproject.toml、.pre-commit-config.yaml、更新后 package.json、全量格式化结果、`requirements-dev.txt`、文档与 CHANGELOG 更新。

### ② eng-vite — 前端 Vite+TS+SFC 迁移 + FastAPI dist 适配（最大分支）

**Vite**
- `vite.config.ts`：`@vitejs/plugin-vue`、`base:'/'`、`build.outDir:'frontend/dist'`、别名 `@→frontend/src`、`server.port:5173`、`server.proxy:{'/api':'http://127.0.0.1:4173'}`。
- devDependencies：`vite`、`@vitejs/plugin-vue`、`vue-tsc`、`typescript`、`concurrently`；dependencies：`vue`、`lucide`（核心包，保持 `createIcons` + `data-lucide` 模式，最小行为变更；`lucide-vue-next` 图标组件后续可选）。
- **提交 `package-lock.json`**。

**TS 迁移**
- `tsconfig.json`（strict）+ `vue-tsc --noEmit` 校验。
- `modules/` 三文件迁 `.ts`；现有 26 项 node:test **同步迁移到 vitest**（本分支只迁测试框架，新增组件测试在 ⑤）。
- `types/models.ts`：Quote / StockRow / Plan / Alert / GridStrategy / Strategy / HistoryBar 等，字段名与后端 API 返回一致。

**SFC 迁移**
- `index.html` → 最小入口（`<div id="app">` + module 脚本）。
- 现 index.html 壳 → `App.vue`；7 个 `View*.js` → `views/View*.vue`（`<script setup lang="ts">` + `<template>`，逻辑原样搬移）。
- `vendor/` 两个文件删除，改用 npm `vue` / `lucide`（核心包，`createIcons` 初始化逻辑保持）。
- **`APP_CTX` provide/inject 模式保留**（SFC 中继续 `inject(APP_CTX)`，最小行为变更路径）。

**一键启动（新增）**
```json
"scripts": {
  "dev": "concurrently -k -n backend,frontend -c blue,green \"npm:dev:backend\" \"npm:dev:frontend\"",
  "dev:backend": "python server.py",
  "dev:frontend": "vite --port 5173"
}
```
- `python server.py` 保持可独立运行（单进程兼容形态）。
- 不采用"后端反向代理 Vite"或"手写 ps1"（非标准 / 跨平台差）。

**FastAPI 适配（backend/app.py）**
```python
FRONTEND_DIR = ROOT / "frontend"
DIST_DIR = FRONTEND_DIR / "dist"
# 存在 dist → /assets mount dist、/ 返回 dist/index.html
# 否则回退源码服务（兼容未构建状态）
```

**验证**：`vue-tsc --noEmit`、vitest 迁移后全绿、`npm run build` 产出 dist、`python server.py` 服务 dist 打开 :4173 全视图功能正常、`npm run dev` 一键启动 HMR 正常。

### ③ eng-refactor — 前端拆分

**抽纯逻辑到 `modules/`（可测）**

| 新模块 | 函数（自 app.js 抽出） |
|--------|------------------------|
| planUtils.ts | calculateShares / calculateRr / 过期判定逻辑（expirePlans 的纯部分） |
| marketUtils.ts | mergeMarket 纯合并逻辑 |
| signalUtils.ts | signalText / signalClass |
| alertUtils.ts | 提醒纯数组追加+去重（addAlert 非副作用部分） |

每个模块配同名 `tests/frontend/*.test.ts`（vitest），覆盖正常/边缘/null 保护。

**拆 `setup()` 为 composables（`src/composables/`）**

| composable | 负责 |
|------------|------|
| useWorkspace | draft / plans / alerts / watchlistCodes / 409 冲突策略 / 同步持久化 |
| useQuotes | market / selectedCode / selectedHistory / indexHistory / fetch |
| useScreener | screenRows / total / mode / 排序分页 preset 过滤 |
| usePlans | 计划 CRUD / checkPlanTriggers / expirePlans / 测算 |
| useAlerts | 提醒增删改 / 过滤 / 通知面板 |
| useSettings | settingsDraft / dataSources / 加载保存 |
| useGrid | gridDraft / gridResult / 网格策略 CRUD / preview/backtest/optimize |
| useStrategy | strategyDraft / strategyResult / 多类型 CRUD / preview/backtest |

- 拆分后 `App.vue` 的 `setup()` 只保留胶水（创建 composables + `provide(APP_CTX)` + 全局调度）。
- `APP_CTX` 暴露字段集合不变（视图零改动，除已 SFC 化的引用路径）。
- 预期 app.js/setup 主体从 1752 行降至 ~300 行胶水。

**验证**：`vue-tsc --noEmit`、vitest 全绿（新旧）、`npm run build` 后 :4173 全视图回归无异常。

### ④ eng-backend — 后端 Pydantic 模型化 + Alembic

**Pydantic（backend/schemas.py）**
- 请求模型：WorkspacePut / SettingsPut / GridPreviewIn / GridBacktestIn / GridOptimizeIn / StrategyPreviewIn / StrategyBacktestIn / StrategyStatusPut 等。
- 响应模型：MarketOut / ScreenerOut / HistoryOut / GridStrategiesOut / StrategiesOut / WorkspaceOut / SettingsOut / HealthOut 等。
- **字段名逐字节保持现状**（AGENTS.md 硬规则：前端依赖现有字段名）。
- 全部 17 个路由改造；既有 75 项测试全量回归 + 新增 schema 校验测试。

**Alembic**
- `alembic init` + `backend/migrations/`；env.py 接现有 engine（settings.database_url）。
- 现有 schema 生成 **baseline 初始迁移**；未来 schema 变更走 Alembic。
- 现有 `ALTER TABLE IF NOT EXISTS` 机制评估收敛：保留幂等降级路径（`initialize_storage` 在迁移后仍幂等），避免破坏已有库。
- storage.py 新迁移逻辑统一走 Alembic revision。

**验证**：`ruff`/`mypy` 过；75+ 测试全绿；新建空库跑 baseline 迁移成功建表；对既有库 upgrade 无破坏；`/docs` 展示全部 schema。

### ⑤ eng-test — 前端 vitest + 后端覆盖率

**前端**
- vitest 全量配置（jsdom 环境 + @vue/test-utils）。
- 26 项 node:test 已迁 vitest（② 完成）；本分支新增：
  - 纯逻辑模块测试补全（③ 的新模块）。
  - **组件测试**：mount 各 View + 注入 mock APP_CTX，断言关键渲染与交互。

**后端**
- pytest-cov 接入；先跑覆盖率基线再定阈值（目标 ≥80%）。
- 覆盖率门禁写入 CI。

**验证**：`npx vitest run` 全绿 + 覆盖率报告；`pytest --cov` 达标。

### ⑥ eng-ci — CI 全栈门禁 + 文档收口

**`.github/workflows/ci.yml`（3 jobs）**
```yaml
on: [push, pull_request]
jobs:
  backend:    # ubuntu + python 3.13
    # pip install -r requirements.txt -r requirements-dev.txt
    # ruff check . && ruff format --check .
    # mypy backend
    # python -m pytest tests/ -q --cov=backend --cov-fail-under=80
  frontend:   # ubuntu + node 22
    # npm ci（lockfile 存在）
    # npx vue-tsc --noEmit
    # npx eslint .
    # npx vitest run
  build:      # 产物验证
    # npm ci && npm run build
    # 启动 python server.py 服务 dist，探活 /api/health 与 / 200
```
- 后端测试无需 DB/Redis 实连（离线 monkeypatch）。

**文档收口（交付项）**
- `AGENTS.md`：改写"无打包器"→ 双轨说明；"prefer 原生 ALTER TABLE"→ Alembic；新增一键启动、vitest/coverage/mypy/ruff 命令。
- `OPERATIONS.md`：重写运行/验证章节（dev 一键、prod 构建、本地验证命令、CI 说明）。
- `README.md`：工程化总览、双轨快速开始、目录结构、工具链说明。
- `CHANGELOG.md`：逐分支记录。

**验证**：workflow 语法（actionlint 或本地 yaml lint）、文档命令逐条可执行。

## 非目标（YAGNI）

- 不引入 monorepo / pnpm / turbo。
- 后端不引入 pyright（用 mypy 一种即可）。
- 不引入前端状态管理库（Pinia 等）——`provide/inject APP_CTX` 已足够，避免多余依赖。
- 不做 UI 重构 / 不新增功能 / 不改 API 字段名 / 不接券商与全市场自动执行。
- 组件测试只覆盖关键交互，不追求 100% 组件覆盖率。

## 风险与缓解

| 风险 | 缓解 |
|------|------|
| Vite+SFC+TS 迁移量大，行为回归 | 分支 ② 逻辑原样搬移 + 全视图手工回归 + 既有测试迁移兜底 |
| Prettier/ruff 全量格式化大 diff | 格式化独立 commit，CI+测试兜底 |
| Pydantic 模型化改变序列化行为 | 字段名逐字节不变 + 75 项测试回归 + 新增 schema 测试 |
| Alembic 破坏既有库 | baseline 迁移 + initialize_storage 幂等降级 + 空库/既有库双验证 |
| 锁文件 CI 可复现 | 提交 package-lock.json，CI 用 npm ci |
| Windows 一键启动僵尸进程 | concurrently -k 保证同时终止 |

## 验证总纲（每分支合并前）

1. 后端：`ruff check .` / `ruff format --check .` / `mypy backend` / `python -m pytest tests/ -q` 全绿。
2. 前端：`npx vue-tsc --noEmit` / `npx eslint .` / `npx vitest run`（或对应阶段命令）全绿。
3. 运行：`npm run dev` 一键启动 → :5173 全视图功能正常；`npm run build` → :4173 单进程正常。
4. 文档：相关章节与本分支改动一致。

## 交付物汇总

- 工具链配置（eslint/prettier/ruff/mypy/pyproject/pre-commit/requirements-dev）
- Vite+TS+SFC 迁移产物（vite.config.ts / tsconfig.json / src/** / App.vue / views/*.vue / types / api）
- package.json scripts + package-lock.json
- backend/schemas.py + backend/migrations/ + alembic.ini
- 测试（vitest 组件+单元 / pytest-cov）
- .github/workflows/ci.yml
- 文档全量更新（AGENTS.md / OPERATIONS.md / README.md / CHANGELOG.md）
