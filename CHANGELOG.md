# Changelog — Atlas Trading Desk

All notable changes to this project. 版本更新清单。

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