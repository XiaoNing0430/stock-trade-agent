# ROADMAP — Atlas 交易工作台 未来功能规划

## 已发布版本

- **v0.4.0** — 全栈工程化改造（ESLint/Prettier/ruff/mypy、Vite 8+TS 5.9、Pinia 8 store、Pydantic+Alembic、vitest+pytest-cov、GitHub Actions CI）

## 待办（方向 2 — 后续功能开发）

### 全市场选股器
- 当前精选约 50 只股票池（`REAL_UNIVERSE`），扩展至全 A 股（~4600 只）
- 腾讯排名接口已接入（`/api/screener/v2`），需完善分页、排序、缓存
- 相关设计文档：`docs/superpowers/plans/2026-08-30-full-market-screener.md`

### 新策略类型
- 当前支持：网格、双均线（SMA）、定投（DCA）、MACD 四种
- 可扩展：均值回归、动量策略、布林带反转等
- 策略引擎已泛化（`backend/strategy_engines.py`），新增策略只需实现计算函数 + 注册到 `STRATEGY_ENGINES`

### 多数据源接入
- 当前仅 Tencent 公开行情接口
- 可接入：东方财富、新浪财经、Tushare（已有 token 占位）等
- 需注意接口频率限制与数据格式差异

### 其他功能
- 多语言支持（英文 UI）
- 自定义主题/配色
- 历史回测结果对比与导出
- 提醒方式扩展（邮件、Webhook 等）