# Atlas 交易工作台

一个面向 A 股研究流程的可视化工作台，当前包含：

- 选股器：趋势突破、质量成长、低估修复三种预设策略，筛选真实行情列表中的涨跌幅、PE、PB、量比和换手率。
- 交易计划：设置计划价、止损价、目标价、仓位和交易逻辑，自动计算盈亏比、股数和最大风险。
- 盯盘中心：管理自选股和计划，行情每 15 秒刷新，价格触发计划条件后生成提醒。

## 架构与数据

- 前端：Vue 3 CDN + 响应式状态，位于 `frontend/`，页面状态保存在浏览器 `localStorage`。
- 后端：Python/FastAPI，位于 `backend/`，统一提供行情 API 和前端静态资源。
- 行情源：Tencent 公开行情接口，当前接入实时个股报价、指数报价、复权日线和真实行情候选池。
- 缺失数据不会用模拟值补齐；行情接口失败时页面保留最近一次成功数据并标记为缓存行情。

## 运行

在项目目录执行：

```powershell
python server.py
```

也可以直接使用：

```powershell
python -m backend.main
```

然后打开 <http://127.0.0.1:4173>。

## API

- `GET /api/health`：服务和行情源状态。
- `GET /api/market?codes=600519,300750`：自选股和指数实时行情。
- `GET /api/screener?market=全部&pageSize=300`：真实行情候选池。
- `GET /api/history?code=600519`：复权日线。

FastAPI 文档地址：<http://127.0.0.1:4173/docs>
