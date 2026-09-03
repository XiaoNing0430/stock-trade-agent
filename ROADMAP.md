# ROADMAP — Atlas 交易工作台 未来功能规划

## 已发布版本

- **v0.4.0** — 全栈工程化改造（ESLint/Prettier/ruff/mypy、Vite 8+TS 5.9、Pinia 8 store、Pydantic+Alembic、vitest+pytest-cov、GitHub Actions CI）

## 待办（方向 2 — 后续功能开发）

### 全市场选股器
- [x] 已扩容为全市场分页排序选股器（腾讯排名接口，~4600 只，分页/排序/缓存已完成）
- [x] 已接入多数据源 Router：`/api/screener/v2` 按 `screenerSource` 设置选源（腾讯排名委托 / 东财 clist 原生分页）
- [x] 前端「精选 50 / 全市场」双模式 + 表头排序 + 分页器（Vue 3 + Pinia）
- 相关设计文档：`docs/superpowers/plans/2026-09-02-full-market-screener-v2.md`（旧版已归档）

### 新策略类型
- [x] 当前支持：网格、双均线（SMA）、定投（DCA）、MACD 四种
- [x] 已扩展：布林带反转、唐奇安突破、动量、多因子（ADX 状态过滤 + 动态切换 + 僵局保护）
- [x] 策略引擎已泛化（`backend/strategy_engines.py` + `backend/strategy_base.py` + `backend/indicators.py`）

### 多数据源接入
- 当前仅 Tencent 公开行情接口
- 可接入：东方财富、新浪财经、Tushare（已有 token 占位）等
- 需注意接口频率限制与数据格式差异

### 其他功能
- 多语言支持（英文 UI）
- 自定义主题/配色
- 历史回测结果对比与导出
- 提醒方式扩展（邮件、Webhook 等）

## 依赖升级跟踪（方向 4）

### 已完成（v0.4.0 后安全升级）
- **lucide** `1.37.0` → `1.38.0`（minor）
- **APScheduler** `3.10.4` → `3.11.3`（minor，后端测试全绿）
- **akshare** `1.18.83` → `1.18.94`（minor，数据源补丁）

### 待评估（major，有破坏性风险，需独立 feature 分支验证）
- **eslint** `9.39.5` → `10.x`：flat config 大版本，需验证 eslint.config.js 兼容性
- **@eslint/js** `9.39.5` → `10.x`：随 eslint 一起升级
- **typescript** `5.9.3` → `7.0`：TS 7 为全新大版本，vue-tsc / @typescript-eslint 兼容性未知，风险最高
- **alembic** `1.14.1` → `1.19.x`：迁移框架大版本，需验证 baseline 迁移与 autogenerate 行为

### 升级纪律
- 每个 major 升级走独立 `feature/*` 分支 + 全量验证（vue-tsc / eslint / vitest / pytest / build）
- minor 补丁升级可直接进 develop（已验证 3 例全绿）