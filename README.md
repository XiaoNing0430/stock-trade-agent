# Atlas 交易工作台

[![CI](https://github.com/XiaoNing0430/stock-trade-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/XiaoNing0430/stock-trade-agent/actions/workflows/ci.yml)

一个面向 A 股研究流程的可视化工作台，当前包含：

- **选股器**：趋势突破、质量成长、低估修复三种预设策略，筛选真实行情列表中的涨跌幅、PE、PB、量比和换手率。支持精选 / 全市场切换。
- **交易计划**：设置计划价、止损价、目标价、仓位和交易逻辑，自动计算盈亏比、股数和最大风险。
- **盯盘中心**：管理自选股和计划，行情每 15 秒刷新，价格触发计划条件后生成提醒。
- **网格策略**：输入股票或 ETF 代码即可给出基准价、触发百分比、每格资金、整手数量和建议投入额；支持经典（跌买涨卖）与趋势（涨买跌卖）模式、日线回测、参数优化、多策略保存和每日盘后定时回测。
- **策略实验室**：统一回测框架，支持网格 / 双均线 / 定投（DCA）/ MACD 四种策略类型。

## 项目结构

```
├── frontend/                  Vue 3 + TypeScript 前端
│   ├── index.html             Vite 入口 HTML
│   ├── src/
│   │   ├── main.ts            Vue 应用启动
│   │   ├── app.ts             应用初始化、路由、轮询
│   │   ├── App.vue            根布局 SFC
│   │   ├── styles.css         全局样式
│   │   ├── stores/            8 个 Pinia 状态仓库
│   │   ├── modules/           纯逻辑模块（format/chart/constants/planUtils 等）
│   │   ├── views/             7 个视图 SFC
│   │   ├── types/             TypeScript 类型定义
│   │   └── api/               接口客户端
│   └── dist/                  Vite 构建产物（生产模式）
├── backend/                    Python/FastAPI 后端
│   ├── app.py                 路由与应用 — 21 个路由装饰器（20 API + 根页面）
│   ├── schemas.py             25 个 Pydantic 请求/响应模型
│   ├── storage.py             SQLAlchemy 模型 + 持久化（10 张表）
│   ├── data_source.py         Tencent 行情适配器
│   ├── grid_strategy.py       网格策略计算
│   ├── strategy_engines.py    通用策略引擎
│   ├── settings.py            pydantic-settings 配置
│   └── migrations/            Alembic 迁移脚本
├── tests/                     测试
│   ├── frontend/              10 个 vitest 文件（66 项测试）
│   └── *.py                   7 个 pytest 文件（139 项测试，覆盖率 ≥80%）
├── .github/workflows/ci.yml   GitHub Actions CI
├── server.py                  开发入口
├── package.json               npm scripts（dev/build/test/verify）
├── pyproject.toml              ruff/mypy/pytest 配置
├── eslint.config.js           ESLint 9 flat config
├── vite.config.ts             Vite 配置
└── vitest.config.ts           vitest 配置
```

## 快速开始

### 开发模式

```powershell
npm run dev         # 一键启动前端 :5173 + 后端 :4173
```

打开 <http://127.0.0.1:5173>。前端开发服务器支持 HMR，`/api` 请求自动代理到后端。

### 生产模式

```powershell
npm run build       # vue-tsc 类型检查 + Vite 构建
python server.py    # 在 :4173 同时提供 API 和前端静态资源
```

打开 <http://127.0.0.1:4173>。

详细启动说明见 [OPERATIONS.md](./OPERATIONS.md)。

## 工具链

| 类别 | 工具 | 用途 |
|------|------|------|
| 前端构建 | Vite 8 + TypeScript 5.9 (strict) | 开发服务器、HMR、生产打包 |
| 前端框架 | Vue 3 + Pinia 4 + lucide | 声明式 UI、状态管理、图标 |
| 前端测试 | vitest 4 + jsdom + @vue/test-utils | 组件与模块测试（66 项） |
| 后端框架 | FastAPI + SQLAlchemy 2.0 + Pydantic v2 | REST API、ORM、请求/响应校验 |
| 数据迁移 | Alembic 1.14 | 数据库演进（`backend/migrations/`） |
| 后端测试 | pytest + pytest-cov | 测试 + 覆盖率门禁 ≥80%（139 项，97.8%） |
| 代码规范 | ESLint 9 + Prettier 3（前端） | `.ts` / `.vue` 静态检查与格式化 |
|            | ruff + mypy（后端） | Python lint、format、类型检查 |
| 自动检查 | pre-commit | 提交前自动运行 lint/format/type-check |
| CI | GitHub Actions | 三 job：backend / frontend / build |

## 架构与数据

- **前端**：Vue 3 + TypeScript，位于 `frontend/src/`；运行时和图标库随项目分发，不依赖外网 CDN。
- **后端**：Python/FastAPI，位于 `backend/`，统一提供行情、工作区持久化 API 和前端静态资源。
- **持久化**：PostgreSQL 保存自选股、交易计划和提醒；Redis 预留给行情缓存、任务调度和提醒去重。浏览器 `localStorage` 仅作为服务暂时不可达时的兜底缓存。
- **行情源**：Tencent 公开行情接口，当前接入实时个股报价、指数报价、复权日线和真实行情候选池。
- **缺失数据不会用模拟值补齐**；行情接口失败时页面保留最近一次成功数据并标记为缓存行情。
- 行情返回同时包含 `exchange`（交易所）、`board`（板块）和 `securityType`（股票/ETF/指数），可区分上交所、深交所、北交所及沪深主板、创业板、科创板。

## API

FastAPI 文档地址：<http://127.0.0.1:4173/docs>

完整 API 列表见 [OPERATIONS.md 文档](./OPERATIONS.md#api-一览)。

## 运行前提

从 `.env.example` 创建本地 `.env`，填写 PostgreSQL 和 Redis 连接信息。`.env` 已被 Git 忽略，不能提交真实密码。

**数据库直连**：应用启动时通过 `.env` 中的环境变量直接连接 PostgreSQL 与 Redis，无需额外配置或代理：

- `POSTGRES_HOST` / `POSTGRES_PORT` / `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` — PostgreSQL 连接信息（默认 `127.0.0.1:5432`，库名 `stock_trade_agent`）。
- `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` / `REDIS_DB` — Redis 连接信息（默认 `127.0.0.1:6379`，db 15）。

若 PostgreSQL / Redis 未就绪，服务仍可启动：后端在 `/api/health` 中如实报告 `storage` 状态（`database` / `redis` 为 `false`），不会伪造可用性；前端保留浏览器缓存并在服务恢复后再次同步。

## 免责声明

本工具用于研究和流程管理，不构成投资建议。网格回测使用日线数据，默认按 T+1 可卖、100 股整数倍、最低佣金、股票卖出印花税、沪市过户费和单边滑点计算，ETF 不计印花税。参数优化采用 70% 训练期选参、30% 验证期排名。实际成交会受盘口、滑点、停牌和涨跌停限制影响；不要将回测结果视为实盘收益预测。