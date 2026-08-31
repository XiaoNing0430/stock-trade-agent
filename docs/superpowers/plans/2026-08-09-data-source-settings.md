# 多数据源与网站设置实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**目标：** 提供可持久化的网站设置菜单和腾讯、AkShare、Tushare 三来源的安全切换与故障切换能力。

**架构：** 使用 `WorkspaceSettings` JSON 行保存非敏感工作区配置。数据源分发器按实时行情、历史日线、选股指标选择适配器，腾讯保持默认和兜底。AkShare 与 Tushare 均延迟导入，缺少依赖或 Token 时服务仍能启动。

**技术栈：** FastAPI、SQLAlchemy、requests、可选 AkShare/Tushare、Vue 3、pytest。

## 全局约束

- 浏览器不得发送、保存或显示 API Token、数据库密码、Redis 密码。
- 默认配置必须与现有腾讯行情行为一致。
- 每一次响应只使用一个成功数据源，并返回实际来源。
- Tushare 未配置 `TUSHARE_TOKEN` 时不可设为首选来源。

---

### 任务 1：持久化设置与设置接口

**文件：**
- 修改：`backend/storage.py`、`backend/settings.py`、`backend/app.py`
- 测试：`tests/test_settings_api.py`

**接口：** `get_workspace_settings(workspace_id)`、`save_workspace_settings(payload, workspace_id)`、`GET /api/settings`、`PUT /api/settings`。

- [x] **步骤 1：写失败测试**

```python
def test_settings_api_returns_defaults_without_secrets(client):
    payload = client.get('/api/settings').json()
    assert payload['data']['historySource'] == 'tencent'
    assert 'tushareToken' not in str(payload)
```

- [x] **步骤 2：运行失败测试**

运行：`python -m pytest tests/test_settings_api.py::test_settings_api_returns_defaults_without_secrets -q -p no:cacheprovider`

预期：接口不存在。

- [x] **步骤 3：实现存储和接口**

创建工作区唯一 JSON 设置行；以白名单规范化来源、刷新间隔、缓存、超时和重试；接口仅返回 `tushareConfigured` 布尔值。

- [x] **步骤 4：运行测试**

运行：`python -m pytest tests/test_settings_api.py -q -p no:cacheprovider`

预期：通过。

### 任务 2：适配器与故障切换

**文件：**
- 修改：`backend/data_source.py`、`backend/app.py`、`backend/grid_scheduler.py`、`requirements.txt`
- 测试：`tests/test_data_sources.py`

**接口：** `source_capabilities()`、`test_data_source(source)`；扩展 `load_market`、`load_history`、`load_screener` 以接收配置并返回实际来源。

- [x] **步骤 1：写失败测试**

```python
def test_history_falls_back_when_preferred_source_fails(monkeypatch):
    config = {'historySource': 'akshare', 'fallbackEnabled': True}
    monkeypatch.setattr(data_source, '_load_akshare_history', lambda *_: (_ for _ in ()).throw(RuntimeError('down')))
    monkeypatch.setattr(data_source, '_load_tencent_history', lambda *_: [{'date': '2026-08-01', 'close': 10}])
    history, source = data_source.load_history_with_source('600519', 1, config)
    assert source == 'tencent'
```

- [x] **步骤 2：运行失败测试**

运行：`python -m pytest tests/test_data_sources.py::test_history_falls_back_when_preferred_source_fails -q -p no:cacheprovider`

预期：函数不存在。

- [x] **步骤 3：实现适配器**

保留腾讯实现为默认适配器；为 AkShare 与 Tushare 增加延迟导入和字段映射；实时行情仅允许腾讯，历史日线和选股允许三来源，首选失败时按固定顺序降级。

- [x] **步骤 4：接入路由和定时回测**

市场、历史、选股和网格接口读取工作区设置；响应和市场日线快照记录实际来源。

- [x] **步骤 5：运行来源测试**

运行：`python -m pytest tests/test_data_sources.py tests/test_backend_api.py -q -p no:cacheprovider`

预期：通过。

### 任务 3：网站设置菜单

**文件：**
- 修改：`frontend/app.js`、`frontend/index.html`、`frontend/styles.css`
- 测试：`node --check frontend/app.js`、本地浏览器

**接口：** 使用设置 API；新增 `settingsDraft`、`settingsStatus`、`loadSettings()`、`saveSettings()` 和 `testDataSource(source)`。

- [x] **步骤 1：增加设置导航和三个标签**

工作台、数据获取、连接状态三个标签；按用途选择来源，未配置 Token 时禁用 Tushare。

- [x] **步骤 2：接入保存和连接测试**

加载时读取设置，保存后刷新行情；测试按钮显示可用状态和诊断信息，不显示敏感数据。

- [x] **步骤 3：完善窄屏样式与验证**

标签与来源状态行可在窄屏换行，且没有页面横向溢出。

### 任务 4：回归、提交和推送

**文件：**
- 创建：`docs/superpowers/plans/2026-08-09-data-source-settings.md`

- [x] **步骤 1：运行检查**

运行：`node --check frontend/app.js`、`python -m pytest -q -p no:cacheprovider`、`git diff --check`。

- [x] **步骤 2：提交并推送**

运行：`git add backend frontend tests requirements.txt docs/superpowers/plans/2026-08-09-data-source-settings.md`，随后提交 `feat: add configurable market data sources` 并推送 `main`。
