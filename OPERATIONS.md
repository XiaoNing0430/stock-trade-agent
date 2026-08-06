# Stock Trade Agent 操作文档

## 项目定位

`stock-trade-agent` 是一个面向 A 股的本地交易研究工作台，当前支持真实行情选股、制定交易计划、盯盘和提醒。项目采用前后端分离目录：`frontend/` 使用 Vue 3，`backend/` 使用 FastAPI；开发入口 `server.py` 只负责启动 uvicorn。

## 运行项目

首次运行前，复制 `.env.example` 为 `.env`，填入 PostgreSQL 和 Redis 信息。不要提交 `.env`；它被 `.gitignore` 排除。

```powershell
cd E:\Data\Code\AI\stock-trade-agent
python server.py
```

打开：

```text
http://127.0.0.1:4173
```

默认端口是 `4173`。如需修改：

```powershell
$env:PORT=4180
python server.py
```

## 行情接口

本地代理提供这些接口：

- `GET /api/health`：检查服务和行情源状态。
- `GET /api/market?codes=600519,300750`：读取自选股和指数实时行情。
- `GET /api/screener?market=全部&pageSize=300`：读取真实行情候选池。
- `GET /api/history?code=600519`：读取复权日线。
- `GET /api/workspace`：读取自选、交易计划和提醒。
- `PUT /api/workspace`：保存自选、交易计划和提醒。

当前行情源是 Tencent public quote API。页面不会用模拟价格补齐缺失报价；接口失败时会显示缓存或异常状态。

股票分类由代码规则生成并随行情返回：

- `exchange`：上交所、深交所、北交所。
- `board`：沪深主板、创业板、科创板、北交所，以及沪市/深市 ETF。
- `securityType`：股票、ETF、指数。

FastAPI Swagger 文档：

```text
http://127.0.0.1:4173/docs
```

## 本地验证

```powershell
node --check frontend/app.js
```

服务启动后验证接口：

```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:4173/api/health
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:4173/api/market?codes=600519,300750"
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:4173/api/screener?market=全部&pageSize=20"
Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:4173/api/history?code=600519"
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:4173/api/workspace
```

## Git 操作

查看状态：

```powershell
git status --short --branch
```

提交：

```powershell
git add .
git commit -m "feat: add real-time stock trading desk"
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
- 本工具用于研究和流程管理，不构成投资建议。
