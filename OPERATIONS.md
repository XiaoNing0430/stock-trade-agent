# Stock Trade Agent 操作文档

## 项目定位

`stock-trade-agent` 是一个面向 A 股的本地交易研究工作台，支持真实行情选股、制定交易计划、盯盘和提醒。项目采用前后端分离架构：`frontend/` 使用 Vue 3 + TypeScript + Vite，`backend/` 使用 FastAPI + SQLAlchemy 2.0 + Pydantic v2；开发入口 `server.py` 只负责启动 uvicorn。

## 运行项目

首次运行前，复制 `.env.example` 为 `.env`，填入 PostgreSQL 和 Redis 信息。不要提交 `.env`；它被 `.gitignore` 排除。

### 开发模式（一键双端）

```powershell
cd E:\Data\Code\AI\stock-trade-agent
npm run dev
```

同时启动前端 Vite 开发服务器（:5173，支持 HMR）与后端 FastAPI（:4173，提供 API）。前端通过 Vite 代理把 `/api` 请求转发到后端。

打开：

```text
http://127.0.0.1:5173
```

后端 API 文档（Swagger）：

```text
http://127.0.0.1:4173/docs
```

### 生产模式（静态构建）

```powershell
npm run build
python server.py
```

`npm run build` 先执行 `vue-tsc --noEmit` 类型检查，再执行 `vite build` 生成 `frontend/dist/` 静态产物；后端 FastAPI 在 :4173 提供 API 与前端静态资源。

打开：

```text
http://127.0.0.1:4173
```

也可以直接使用：

```powershell
python -m backend.main
```

默认端口是 `4173`。如需修改：

```powershell
$env:PORT=4180
python server.py
```

### 兼容性说明

若 `frontend/dist/` 不存在，`python server.py` 会回退到直接提供 `frontend/` 源码目录 —— 但前端源码需要由 Vite 开发服务器编译，因此该回退形态下前端不可用（后端 API 仍可访问）。请始终使用 `npm run dev`（开发）或 `npm run build` + `python server.py`（生产）二选一，前端才能正常工作。

## API 一览

本地后端提供以下接口（共 21 个路由装饰器：20 个 `/api` 接口 + 1 个根页面）：

- `GET /api/health`：检查服务和行情源状态。
- `GET /api/workspace`：读取工作区（自选、计划、提醒，含 `revision`）。
- `PUT /api/workspace`：保存工作区（`baseRevision` 冲突 → 409，`force` 覆盖）。
- `GET /api/settings`：读取工作区设置。
- `PUT /api/settings`：保存工作区设置。
- `GET /api/market?codes=600519,300750`：读取自选股和指数实时行情。
- `GET /api/history?code=600519`：读取复权日线。
- `GET /api/screener?market=全部&pageSize=300`：读取真实行情候选池（精选）。
- `GET /api/screener/v2`：全市场选股（分页 + 排序）。
- `POST /api/grid/preview`：根据指定股票或 ETF 的日线建议网格区间。
- `POST /api/grid/backtest`：运行并可保存网格策略回测。
- `POST /api/grid/optimize`：搜索网格数量和区间宽度的候选参数。
- `GET /api/grid/strategies`：读取已保存网格策略。
- `PATCH /api/grid/strategies/{strategy_id}`：更新网格策略状态/调度。
- `DELETE /api/grid/strategies/{strategy_id}`：删除网格策略及回测记录。
- `POST /api/strategy/preview`：通用策略建议（网格 / 双均线 / 定投 / MACD）。
- `POST /api/strategy/backtest`：运行并可保存策略回测。
- `GET /api/strategy/strategies`：读取已保存策略。
- `PATCH /api/strategy/strategies/{strategy_id}`：更新策略状态/调度。
- `DELETE /api/strategy/strategies/{strategy_id}`：删除策略及回测记录。
- `GET /`：前端页面（`frontend/dist` 或源码回退）。

当前行情源是 Tencent public quote API。页面不会用模拟价格补齐缺失报价；接口失败时会显示缓存或异常状态。

股票分类由代码规则生成并随行情返回：

- `exchange`：上交所、深交所、北交所。
- `board`：沪深主板、创业板、科创板、北交所，以及沪市/深市 ETF。
- `securityType`：股票、ETF、指数。

## 本地验证

```powershell
npm run verify        # 前端 66 项 vitest + vue-tsc 类型检查 + 后端 139 项 pytest
npx vitest run        # 仅前端
python -m pytest tests/ -v
python -m ruff check backend tests server.py
python -m ruff format --check backend tests server.py
python -m mypy backend
pre-commit run --all-files
```

`npm run verify` 等价于 `npm run test:frontend && npm run check:frontend && npm run test:backend`（vitest → vue-tsc → pytest）。

服务启动后验证接口：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:4173/api/health
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:4173/api/market?codes=600519,300750"
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:4173/api/screener?market=全部&pageSize=20"
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:4173/api/history?code=600519"
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:4173/api/workspace
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:4173/api/grid/preview -ContentType 'application/json' -Body '{"code":"588000","lookback":120,"gridCount":8}'
```

## 工程化工具链

### 代码规范

| 工具 | 范围 | 配置 | 说明 |
|---|---|---|---|
| ESLint 9 flat config | `frontend/src/**/*.{ts,vue}` | `eslint.config.js` | typescript-eslint + eslint-plugin-vue；`no-explicit-any: off`（动态行情负载约定）；`tests/frontend/**` 忽略 |
| Prettier 3 | 前端 | `.prettierrc` | 与 ESLint 无冲突 |
| ruff check + format | `backend/ tests/ server.py` | `pyproject.toml` | line-length 120，select E/F/W/I/UP |
| mypy | `backend/` | `pyproject.toml` | strict-lite 配置 |

### npm scripts 收口

| 脚本 | 等价命令 | 用途 |
|---|---|---|
| `npm run dev` | concurrently 双端 | Vite HMR (:5173) + FastAPI (:4173) |
| `npm run build` | `vue-tsc --noEmit && vite build` | 类型门禁 + 打包到 `frontend/dist/` |
| `npm run verify` | vitest → vue-tsc → pytest | 一键全量回归 |
| `npm run test:e2e` | `playwright test --config=e2e/playwright.config.ts` | Playwright e2e（需先启动前端服务） |
| `npm run lint` / `npm run format` | eslint + ruff / prettier + ruff-format | 静态检查 / 格式化 |

### pre-commit 钩子

`.pre-commit-config.yaml` 按序执行：`ruff --fix` → `ruff-format` → `mypy` → `eslint` → `prettier` → `vue-tsc --noEmit`。`git commit` 时自动运行，任一失败则提交中止；ruff-format 修改文件后需重新 `git add` 再提交。

### GitHub Actions CI

`.github/workflows/ci.yml` 三个并行 job：

- **backend**：`ruff check` → `ruff format --check` → `mypy` → `pytest`（覆盖率门禁），使用 **postgres:16 service container**（CI 环境无法连本地开发库）。
- **frontend**：`vue-tsc --noEmit` → `eslint` → `vitest run`。
- **build**：`npm ci` → `npm run build` → `python server.py` 启动 → `curl` 探测 `/api/health` 与首页。

### 覆盖率门禁

pytest 通过 `--cov=backend --cov-fail-under=80` 强制后端覆盖率 ≥80%（实测 97.8%）。前端 vitest 66 项（jsdom + @vue/test-utils）+ Playwright e2e 冒烟（`e2e/`）。

### Docker 部署（v0.4.1+）

- `Dockerfile`：multi-stage —— node:22-alpine 构建前端 → python:3.13-slim 运行后端，`HEALTHCHECK` 探测 `/api/health`。
- `docker-compose.yml`：postgres:16 + redis:7 + app 三服务，`depends_on` 健康检查；宿主端口 5433/6380（避开本机已有 PostgreSQL/Redis）。
- 构建产物在镜像内（`COPY --from=frontend-build`），**不挂载** `./frontend/dist` 以避免遮蔽镜像内构建。
- 启动：`docker compose up -d --build`；停止：`docker compose down`。

### 依赖升级纪律

- **minor / patch**：验证全绿后可直接进 develop（v0.4.1 已升级 lucide 1.38 / APScheduler 3.11 / akshare 1.18.94）。
- **major**：有破坏性风险（eslint 10、TS 7、alembic 1.19），须走独立 `feature/*` 分支 + 全量验证。跟踪清单见 `ROADMAP.md`。

## Git 操作

查看状态：

```powershell
git status --short --branch
```

提交（提交信息首行须为中文，建议 Conventional Commits 前缀）：

```powershell
git add .
git commit -m "feat: 新增全市场选股与分页"
```

推送：

```powershell
git push -u origin main
```

如果仓库还没有远端：

```powershell
git remote add origin <your-repository-url>
git push -u origin main
```

## 注意事项

- Vue 3 和 Lucide 图标随前端资源一起提供，不依赖外网 CDN。
- PostgreSQL 是自选股、交易计划和提醒的持久化来源；Redis 用于后续实时行情缓存、调度和提醒去重。若存储服务短暂不可用，页面保留浏览器缓存并在服务恢复后再次同步。
- 盯盘提醒基于浏览器页面运行，关闭页面后不会继续后台提醒。
- 当前候选池是精选真实行情列表，后续可接入完整 A 股代码主数据。
- 网格策略支持经典模式（低价触发买入后、高价触发卖出）和趋势模式（高价触发买入后、低价触发卖出）。默认采用 T+1 可卖、整手、最低佣金、股票印花税和沪市过户费；ETF 不收印花税。参数优化以 70% 历史数据训练、30% 验证期排名。保存为"每日盘后回测"后，服务会在每周一至周五 15:20（上海时区）为每个已启用策略单独运行回测；服务重启会恢复任务。实际成交会受盘口、滑点、停牌和涨跌停限制影响；不要将回测结果视为实盘收益预测。
- 本工具用于研究和流程管理，不构成投资建议。