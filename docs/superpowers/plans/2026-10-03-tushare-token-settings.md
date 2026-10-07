# 设置页 Tushare Token 与跨源校验开关 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 设置页提供 Tushare token 配置（掩码存取）与跨源校验三态启用开关，运行时生效、特性默认休眠。

**Architecture:** workspace settings 新增 `tushareToken`/`crossCheckEnabled` 两键（DB，PUT exclude_unset 白名单合并）；`cross_check.effective_config()` 解析有效开关与 token（DB 显式值 > env）；调度 job 常驻注册、`run()` 运行时判定；前端 store 持独立输入 ref，GET/PUT 均不回显明文。

**Tech Stack:** FastAPI + SQLAlchemy（后端）、Vue 3 + Pinia + vitest（前端）、pytest 全离线 monkeypatch。

## Global Constraints

- GET `/api/settings`（data 与 sources）**永不出现明文 token**——掩码格式 `****<尾4位>`。
- PUT 语义：`tushareToken` 缺省=不修改、`""`=清除；`crossCheckEnabled` 三态 `null`=跟随环境 / `true` / `false`。
- 测试全离线（monkeypatch），勿让 run()/GET 直连真实 PG。
- 红线不变：跨源校验只读对账，不自动改数、不阻断 ETL。
- 每任务独立提交，中文 Conventional Commits；pre-commit 全量钩子（mypy/eslint/prettier/vue-tsc）必须过。

---

### Task 1: storage 两键与规范化

**Files:**
- Modify: `backend/storage.py`（`DEFAULT_WORKSPACE_SETTINGS` 尾部 + `_normalize_workspace_settings`）
- Test: `tests/test_settings_api.py`

**Interfaces:**
- Produces: `DEFAULT_WORKSPACE_SETTINGS["tushareToken"] == ""`、`["crossCheckEnabled"] is None`；`_normalize_workspace_settings` 对两键的清洗语义（token strip+截断128、开关非布尔→None）。后续任务全部依赖这两个键名。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_settings_api.py`）

```python
def test_workspace_settings_tushare_keys_normalize():
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS, _normalize_workspace_settings

    assert DEFAULT_WORKSPACE_SETTINGS["tushareToken"] == ""
    assert DEFAULT_WORKSPACE_SETTINGS["crossCheckEnabled"] is None
    normalized = _normalize_workspace_settings({"tushareToken": "  abc123  ", "crossCheckEnabled": True})
    assert normalized["tushareToken"] == "abc123"
    assert normalized["crossCheckEnabled"] is True
    bogus = _normalize_workspace_settings({"crossCheckEnabled": "yes"})
    assert bogus["crossCheckEnabled"] is None
```

- [ ] **Step 2: 跑红** `python -m pytest tests/test_settings_api.py::test_workspace_settings_tushare_keys_normalize -q --no-cov` → FAIL（KeyError: 'tushareToken'）

- [ ] **Step 3: 实现**——`DEFAULT_WORKSPACE_SETTINGS` 尾部（`"totalPositionCapPct": 100,` 之后）追加：

```python
    # 跨源校验（P2.5）：Tushare token 页面配置（GET 掩码不回显；env TUSHARE_TOKEN 作 fallback）
    # 与三态启用开关（None=跟随环境 CROSS_CHECK_ENABLED；true/false=DB 显式覆盖）
    "tushareToken": "",
    "crossCheckEnabled": None,
```

`_normalize_workspace_settings` 中（`data["workspaceName"] = ...` 行之前）追加：

```python
    data["tushareToken"] = str(data.get("tushareToken") or "").strip()[:128]
    if data.get("crossCheckEnabled") not in (True, False):
        data["crossCheckEnabled"] = None
```

- [ ] **Step 4: 跑绿** 同 Step 2 命令 → PASS；再跑 `python -m pytest tests/test_settings_api.py -q --no-cov` 全绿（既有用例零破坏）

- [ ] **Step 5: 提交** `git add backend/storage.py tests/test_settings_api.py && git commit -m "feat: workspace settings 新增 tushareToken 与三态 crossCheckEnabled"`

---

### Task 2: GET 掩码 + PUT 透传（schemas + app.py）

**Files:**
- Modify: `backend/schemas.py`（`SettingsPut`，26-48 行区域尾部）
- Modify: `backend/app.py`（`settings()` GET 端点 ~357-425 行、`update_settings()` ~467-482 行）
- Test: `tests/test_settings_api.py`

**Interfaces:**
- Consumes: Task 1 的两键。
- Produces: GET `data.tushareToken` 恒 `""`；sources.tushare 行含 `tushareConfigured: bool`（DB 或 env 任一）与 `tushareTokenMasked: str`（`****<尾4位>` 或 `""`）；PUT 响应 data 同样掩码。

- [ ] **Step 1: 写失败测试**（追加；文件顶部按需 `from types import SimpleNamespace`）

```python
def test_settings_api_masks_tushare_token_and_reports_configured(monkeypatch):
    from types import SimpleNamespace

    from backend.storage import _normalize_workspace_settings

    monkeypatch.setattr(
        app_module,
        "get_workspace_settings",
        lambda workspace_id="default": _normalize_workspace_settings({"tushareToken": "abcd1234efgh"}),
    )
    monkeypatch.setattr(app_module, "get_settings", lambda: SimpleNamespace(tushare_token=""))
    with TestClient(app_module.create_app()) as client:
        response = client.get("/api/settings")

    payload = response.json()
    assert payload["data"]["tushareToken"] == ""
    assert "abcd1234efgh" not in str(payload)
    tushare = next(s for s in payload["sources"] if s["id"] == "tushare")
    assert tushare["tushareConfigured"] is True
    assert tushare["tushareTokenMasked"] == "****efgh"


def test_settings_api_tushare_env_fallback_and_workspace_priority(monkeypatch):
    from types import SimpleNamespace

    from backend.storage import DEFAULT_WORKSPACE_SETTINGS

    monkeypatch.setattr(app_module, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS))
    monkeypatch.setattr(app_module, "get_settings", lambda: SimpleNamespace(tushare_token="envtoken9999"))
    with TestClient(app_module.create_app()) as client:
        env_only = client.get("/api/settings").json()
        assert next(s for s in env_only["sources"] if s["id"] == "tushare")["tushareTokenMasked"] == "****9999"
    monkeypatch.setattr(
        app_module,
        "get_workspace_settings",
        lambda workspace_id="default": _normalize_workspace_settings({"tushareToken": "abcd1234efgh"}),
    )
    with TestClient(app_module.create_app()) as client:
        both = client.get("/api/settings").json()
        assert next(s for s in both["sources"] if s["id"] == "tushare")["tushareTokenMasked"] == "****efgh"


def test_settings_put_tushare_roundtrip_and_clear(monkeypatch):
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS, _normalize_workspace_settings

    saved: dict[str, dict] = {}

    def fake_save(payload, workspace_id="default"):
        saved[workspace_id] = _normalize_workspace_settings({**saved.get(workspace_id, {}), **payload})
        return saved[workspace_id]

    monkeypatch.setattr(app_module, "save_workspace_settings", fake_save)
    monkeypatch.setattr(
        app_module, "get_workspace_settings", lambda workspace_id="default": saved.get(workspace_id, dict(DEFAULT_WORKSPACE_SETTINGS))
    )
    with TestClient(app_module.create_app()) as client:
        put = client.put("/api/settings", json={"tushareToken": "tok12345", "crossCheckEnabled": True})
        assert put.status_code == 200
        assert put.json()["data"]["tushareToken"] == ""
        client.put("/api/settings", json={"refreshInterval": 30})
        assert saved["default"]["tushareToken"] == "tok12345"  # 缺省=不修改
        assert saved["default"]["crossCheckEnabled"] is True
        client.put("/api/settings", json={"tushareToken": ""})
        assert saved["default"]["tushareToken"] == ""  # ""=清除
```

- [ ] **Step 2: 跑红** `python -m pytest tests/test_settings_api.py -q --no-cov` → 新增 3 用例 FAIL；同时既有 `test_settings_api_returns_default_data_sources_without_secrets` 的 `"tushareToken" not in str(payload)` 断言会因 sources 出现 `tushareTokenMasked` 键而 FAIL（预期内）

- [ ] **Step 3: 实现**——
  a) `schemas.py` `SettingsPut` 尾部（`positionCapPct: float = 25` 之后）追加：

```python
    # 跨源校验（P2.5）：token（GET 永不回显；PUT 缺省=不修改、""=清除）与三态启用（None=跟随环境）
    tushareToken: str = ""
    crossCheckEnabled: bool | None = None
```

  b) `app.py` GET `settings()`：将现有 `tushare_configured = bool(getattr(__import__(...), ...))` 一段替换为（置于 try/except 取 data 之后、sources 构造之前）：

```python
        workspace_token = str(data.get("tushareToken") or "")
        env_token = str(get_settings().tushare_token or "")
        data = {**data, "tushareToken": ""}
        tushare_configured = bool(workspace_token or env_token)
        tushare_masked = f"****{(workspace_token or env_token)[-4:]}" if tushare_configured else ""
```

  并在文件既有 import 区确保 `from backend.settings import get_settings`（`settings()` 内改用直接调用；替换原 `__import__` 写法）。sources 的 tushare 行改为：

```python
                {
                    "id": "tushare",
                    "name": "Tushare",
                    "realtime": False,
                    "history": True,
                    "screener": True,
                    "fundamental": False,
                    "available": False,
                    "installed": tushare_installed,
                    "tushareConfigured": tushare_configured,
                    "tushareTokenMasked": tushare_masked,
                    "reason": "暂未支持切换，适配器开发中" if tushare_configured else "未配置 TUSHARE_TOKEN",
                },
```

  c) `app.py` `update_settings()` 返回改为掩码：`return SettingsPutOut(data={**saved, "tushareToken": ""})`。

  d) 既有 `test_settings_api_returns_default_data_sources_without_secrets` 删除 `"tushareToken" not in str(payload)` 一行断言（掩码不变式已由更强的新用例承担：明文值不出现在 payload 任何位置），其余保留。

- [ ] **Step 4: 跑绿** `python -m pytest tests/test_settings_api.py tests/test_backend_api.py -q --no-cov` → 全绿

- [ ] **Step 5: 提交** `git commit -m "feat: 设置 API 掩码透传 tushareToken 与三态 crossCheckEnabled（明文永不回显）"`（理由单列：`without_secrets` 用例断言升级）

---

### Task 3: cross_check 有效开关/token 解析与运行时门

**Files:**
- Modify: `backend/cross_check.py`（`run`/`fetch_tushare` + 新增 `effective_config`/`_resolve_provider`）
- Test: `tests/test_cross_check.py`

**Interfaces:**
- Produces: `effective_config() -> {"enabled": bool, "token": str}`（workspace `storage.get_workspace_settings("default")` 显式值 > `get_settings()`；异常回空 workspace）；`_resolve_provider(provider, config) -> str | None`（显式 provider 强制；否则未启用→None；启用→有 token=tushare/无=eastmoney）。`fetch_tushare` 的 token 检查移到 `import tushare` 之前。

- [ ] **Step 1: 写失败测试**（追加/修改 `tests/test_cross_check.py`）

```python
def test_effective_config_workspace_overrides_env(monkeypatch):
    class FakeSettings:
        cross_check_enabled = False
        tushare_token = "env-token"

    monkeypatch.setattr(
        cross_check.storage, "get_workspace_settings", lambda workspace_id="default": {"crossCheckEnabled": True, "tushareToken": "ws-token"}
    )
    monkeypatch.setattr("backend.settings.get_settings", lambda: FakeSettings())
    config = cross_check.effective_config()
    assert config == {"enabled": True, "token": "ws-token"}


def test_effective_config_falls_back_to_env(monkeypatch):
    from backend.storage import DEFAULT_WORKSPACE_SETTINGS

    class FakeSettings:
        cross_check_enabled = True
        tushare_token = "env-token"

    monkeypatch.setattr(cross_check.storage, "get_workspace_settings", lambda workspace_id="default": dict(DEFAULT_WORKSPACE_SETTINGS))
    monkeypatch.setattr("backend.settings.get_settings", lambda: FakeSettings())
    assert cross_check.effective_config() == {"enabled": True, "token": "env-token"}


def test_resolve_provider_matrix():
    assert cross_check._resolve_provider(None, {"enabled": False, "token": ""}) is None
    assert cross_check._resolve_provider(None, {"enabled": True, "token": ""}) == "eastmoney"
    assert cross_check._resolve_provider(None, {"enabled": True, "token": "t"}) == "tushare"
    assert cross_check._resolve_provider("eastmoney", {"enabled": False, "token": ""}) == "eastmoney"  # 显式=强制


def test_fetch_tushare_requires_token(monkeypatch):
    monkeypatch.setattr(cross_check, "effective_config", lambda: {"enabled": True, "token": ""})
    import pytest

    with pytest.raises(RuntimeError, match="TUSHARE_TOKEN"):
        cross_check.fetch_tushare(["600000"])
```

并将 `test_disabled_run_updates_health_result` 改为 monkeypatch 开关（离线纪律——run() 现在会读 workspace settings）：

```python
def test_disabled_run_updates_health_result(monkeypatch):
    monkeypatch.setattr(cross_check, "effective_config", lambda: {"enabled": False, "token": ""})
    result = cross_check.run()
    assert result.status == "disabled"
    assert cross_check.last_result()["status"] == "disabled"
```

- [ ] **Step 2: 跑红** `python -m pytest tests/test_cross_check.py -q --no-cov` → `effective_config`/`_resolve_provider` 用例 FAIL（AttributeError）；`test_fetch_tushare_requires_token` FAIL（先 ImportError 后 RuntimeError 语义）；`test_disabled_run...` FAIL（真实 DB 访问路径）

- [ ] **Step 3: 实现**——`cross_check.py`：

```python
def effective_config() -> dict[str, Any]:
    """有效开关与 token：workspace 显式值 > env（离线测试 monkeypatch 本函数）。"""
    from backend.settings import get_settings

    try:
        workspace = storage.get_workspace_settings("default")
    except Exception:
        workspace = {}
    settings = get_settings()
    flag = workspace.get("crossCheckEnabled")
    enabled = bool(flag) if flag is not None else bool(settings.cross_check_enabled)
    token = str(workspace.get("tushareToken") or "") or str(settings.tushare_token or "")
    return {"enabled": enabled, "token": token}


def _resolve_provider(provider: str | None, config: dict[str, Any]) -> str | None:
    if provider:
        return provider
    if not config["enabled"]:
        return None
    return "tushare" if config["token"] else "eastmoney"
```

`run()` 前两段改为：

```python
def run(provider: str | None = None, *, date: str | None = None, sleep: Any = None) -> CrossStats:
    global _last
    provider = _resolve_provider(provider, effective_config())
    if provider is None:
        result = CrossStats(None, 0, [], [], 0, "disabled")
    else:
        try:
            with storage.SessionLocal() as session:
                ...  # 既有查询不变
```

`fetch_tushare` 改为（token 检查先于 import）：

```python
def fetch_tushare(codes: list[str]) -> dict[str, tuple[float | None, float | None]]:
    token = effective_config()["token"]
    if not token:
        raise RuntimeError("TUSHARE_TOKEN 未配置")
    import tushare as ts

    frame = ts.pro_api(token).daily(trade_date=date.today().strftime("%Y%m%d"))
    ...  # 既有转换不变
```

- [ ] **Step 4: 跑绿** `python -m pytest tests/test_cross_check.py -q --no-cov` → 全绿（4 既有 + 5 新增/调整）

- [ ] **Step 5: 提交** `git commit -m "feat: cross_check 运行时解析有效开关与 token（DB 显式值>env），页面开关即时生效"`

---

### Task 4: 调度常驻注册

**Files:**
- Modify: `backend/bars_etl.py`（`register_jobs` crosscheck spec，~419-434 行）
- Test: `tests/test_bars_etl.py`（`test_register_jobs_three_triggers_overlap_flags`）

**Interfaces:**
- Consumes: Task 3 的 `run(provider=None)` 自动路由。
- Produces: 第 4 个 job 恒注册，`kwargs == {}`。

- [ ] **Step 1: 写失败测试**——`test_register_jobs_three_triggers_overlap_flags` 重命名并改断言：

```python
def test_register_jobs_four_triggers_overlap_flags():
    calls = bars_etl.register_jobs(FakeScheduler())
    assert len(calls) == 4
    ids = {c["id"] for c in calls}
    assert ids == {"bars-etl-startup", "bars-etl-daily", "bars-etl-weekly", "bars-crosscheck"}
    crosscheck = next(c for c in calls if c["id"] == "bars-crosscheck")
    assert crosscheck["trigger"] == "cron" and crosscheck["day_of_week"] == "mon-fri"
    assert crosscheck["hour"] == 15 and crosscheck["minute"] == 35
    assert crosscheck["kwargs"] == {}  # 运行时按有效开关/token 自动路由（spec 2026-10-03）
    for c in calls:
        assert c["max_instances"] == 1 and c["coalesce"] is True and c["misfire_grace_time"] == 300
        assert c["replace_existing"] is True
    daily = next(c for c in calls if c["id"] == "bars-etl-daily")
    weekly = next(c for c in calls if c["id"] == "bars-etl-weekly")
    startup = next(c for c in calls if c["id"] == "bars-etl-startup")
    assert (
        daily["trigger"] == "cron"
        and daily["day_of_week"] == "mon-fri"
        and daily["hour"] == 15
        and daily["minute"] == 20
    )
    assert weekly["trigger"] == "cron" and weekly["day_of_week"] == "sat" and weekly["hour"] == 10
    assert startup["trigger"] == "date"  # 一次性 +60s 首查（interval 会每 60s 重跑——非所需）
    assert (startup["run_date"] - datetime.now(SH)).total_seconds() <= 61
```

- [ ] **Step 2: 跑红** `python -m pytest tests/test_bars_etl.py::test_register_jobs_four_triggers_overlap_flags -q --no-cov` → FAIL（len(calls)==3，env 关时无 crosscheck）

- [ ] **Step 3: 实现**——`register_jobs` 内 crosscheck 块去掉 `get_settings().cross_check_enabled` 条件与 `get_settings` import，spec 恒追加且 `"kwargs": {}`：

```python
    try:
        from backend import cross_check

        specs.append(
            {
                "func": cross_check.run,
                "kwargs": {},
                "id": "bars-crosscheck",
                "trigger": "cron",
                "day_of_week": "mon-fri",
                "hour": 15,
                "minute": 35,
                "max_instances": 1,
                "coalesce": True,
                "misfire_grace_time": 300,
                "replace_existing": True,
            }
        )
    except Exception:
        logger.warning("cross_check 任务注册探测失败，跳过", exc_info=True)
```

- [ ] **Step 4: 跑绿** `python -m pytest tests/test_bars_etl.py tests/test_bars_etl_run.py -q --no-cov` → 全绿

- [ ] **Step 5: 提交** `git commit -m "feat: crosscheck 调度常驻注册（语义变更修测试：运行时判定取代注册期 env 门，spec 2026-10-03）"`

---

### Task 5: 前端 store——独立 token 输入与掩码合并

**Files:**
- Modify: `frontend/src/stores/useSettingsStore.ts`

**Interfaces:**
- Consumes: Task 2 的 GET/PUT 语义。
- Produces: store 新成员 `tushareTokenInput: Ref<string>`、`clearTushareToken(): Promise<void>`；`settingsDraft.crossCheckEnabled: boolean | null`（初始 null）；`saveSettings()` 仅在输入非空时携带 `tushareToken`。

- [ ] **Step 1: 写失败测试**（追加到 `tests/frontend/ViewSettings.test.ts`；无需 mount，直接驱动 store）

```ts
import { flushPromises } from '@vue/test-utils';

  it('保存仅在填写 token 时携带 tushareToken，保存后清空输入', async () => {
    const settings = useSettingsStore();
    const workspace = useWorkspaceStore();
    const spy = vi.spyOn(workspace, 'requestJson').mockResolvedValue({ data: {} });
    settings.tushareTokenInput = 'my-token';
    await settings.saveSettings();
    await flushPromises();
    const firstBody = JSON.parse((spy.mock.calls[0][1] as RequestInit).body as string);
    expect(firstBody.tushareToken).toBe('my-token');
    expect(settings.tushareTokenInput).toBe('');
    settings.tushareTokenInput = '';
    await settings.saveSettings();
    await flushPromises();
    const secondBody = JSON.parse((spy.mock.calls[1][1] as RequestInit).body as string);
    expect('tushareToken' in secondBody).toBe(false);
  });

  it('clearTushareToken 显式发送空串清除', async () => {
    const settings = useSettingsStore();
    const workspace = useWorkspaceStore();
    const spy = vi.spyOn(workspace, 'requestJson').mockResolvedValue({ data: {} });
    await settings.clearTushareToken();
    await flushPromises();
    const body = JSON.parse((spy.mock.calls[0][1] as RequestInit).body as string);
    expect(body.tushareToken).toBe('');
  });
```

- [ ] **Step 2: 跑红** `npx vitest run tests/frontend/ViewSettings.test.ts` → FAIL（`tushareTokenInput` undefined）

- [ ] **Step 3: 实现**——`useSettingsStore.ts`：
  a) `settingsDraft` 增加 `crossCheckEnabled: null as boolean | null,`（不放 `tushareToken`——GET 掩码回 ""，若进 draft 会被全量 PUT 误清除）。
  b) 新增独立输入与合并助手：

```ts
  const tushareTokenInput = ref('');
  // GET/PUT 响应 data 中 tushareToken 恒为掩码空串——绝不并入 draft（防全量保存误清除）
  function mergeSettingsData(data: Record<string, unknown> | undefined) {
    const { tushareToken: _masked, ...rest } = data || {};
    Object.assign(settingsDraft, rest);
  }
```

  c) `settingsDirty` 计入未保存的 token 输入：

```ts
  const settingsDirty = computed(
    () =>
      tushareTokenInput.value !== '' ||
      (Boolean(appliedSettings.value) && JSON.stringify(settingsDraft) !== JSON.stringify(appliedSettings.value))
  );
```

  d) `loadSettings`/`saveSettings` 中 `Object.assign(settingsDraft, payload.data || {})` 全部替换为 `mergeSettingsData(payload.data)`；`saveSettings` body 改为：

```ts
      const body: Record<string, unknown> = { ...settingsDraft };
      if (tushareTokenInput.value) body.tushareToken = tushareTokenInput.value;
      const payload = await workspace.requestJson('/api/settings', {
        method: 'PUT',
        body: JSON.stringify(body),
      });
      mergeSettingsData(payload.data);
      tushareTokenInput.value = '';
```

  e) 新增：

```ts
  async function clearTushareToken() {
    settingsLoading.value = true;
    try {
      const payload = await workspace.requestJson('/api/settings', {
        method: 'PUT',
        body: JSON.stringify({ tushareToken: '' }),
      });
      mergeSettingsData(payload.data);
      tushareTokenInput.value = '';
      workspace.showToast('Tushare Token 已清除');
    } catch (error: any) {
      workspace.showToast(error.message || '清除失败', 'error');
    } finally {
      settingsLoading.value = false;
    }
  }
```

  f) store return 增加 `tushareTokenInput, clearTushareToken`。

- [ ] **Step 4: 跑绿** `npx vitest run tests/frontend/ViewSettings.test.ts` → 全绿；`npx vitest run` 全量绿（dirty 语义变化不破坏既有用例）

- [ ] **Step 5: 提交** `git commit -m "feat: 设置 store 支持独立 token 输入与三态 crossCheckEnabled（掩码不回显、缺省不覆盖）"`

---

### Task 6: 设置页 Tushare 行 UI

**Files:**
- Modify: `frontend/src/views/ViewSettings.vue`（connection 模板 ~283-299 行 + script 解构 320 行 + 尾部）
- Modify: `frontend/src/styles.css`（`.tushare-config`/`.tushare-warn` 两个小类）
- Test: `tests/frontend/ViewSettings.test.ts`

**Interfaces:**
- Consumes: Task 5 的 `tushareTokenInput`/`clearTushareToken`/`settingsDraft.crossCheckEnabled`；sources.tushare 行的 `tushareTokenMasked`。

- [ ] **Step 1: 写失败测试**（追加）

```ts
  it('连接标签 Tushare 行提供 token 输入、掩码展示与三态开关', () => {
    const alerts = useAlertsStore();
    const settings = useSettingsStore();
    alerts.hubTab = 'settings';
    settings.settingsTab = 'connection';
    settings.dataSources = [
      { id: 'tencent', name: '腾讯行情', realtime: true, history: true, screener: true, fundamental: false, available: true, reason: '' },
      {
        id: 'tushare', name: 'Tushare', realtime: false, history: true, screener: true, fundamental: false,
        available: false, installed: true, tushareConfigured: true, tushareTokenMasked: '****efgh', reason: '',
      },
    ];
    const wrapper = mount(ViewSettings);
    const tokenInput = wrapper.find('input[aria-label="Tushare Token"]');
    expect(tokenInput.exists()).toBe(true);
    expect((tokenInput.element as HTMLInputElement).type).toBe('password');
    expect(wrapper.text()).toContain('****efgh');
    const select = wrapper.find('select[aria-label="跨源校验开关"]');
    expect(select.exists()).toBe(true);
    expect(wrapper.text()).toContain('对账偏差告警');
  });
```

- [ ] **Step 2: 跑红** `npx vitest run tests/frontend/ViewSettings.test.ts` → FAIL（input 不存在）

- [ ] **Step 3: 实现**——
  a) connection 模板的 `v-for` section 内、badge `</div>` 之后追加（其余 source 不渲染该块）：

```html
            <template v-if="source.id === 'tushare'">
              <div class="tushare-config">
                <input
                  v-model="tushareTokenInput"
                  type="password"
                  autocomplete="off"
                  placeholder="Tushare Token（留空保持不变）"
                  aria-label="Tushare Token"
                /><button
                  v-if="source.tushareTokenMasked"
                  class="text-button"
                  type="button"
                  data-testid="clear-tushare-token"
                  @click="clearTushareToken"
                >清除</button
                ><span v-if="source.tushareTokenMasked" class="setting-status">已配置 {{ source.tushareTokenMasked }}</span>
              </div>
              <div class="tushare-config">
                <select v-model="settingsDraft.crossCheckEnabled" aria-label="跨源校验开关">
                  <option :value="null">跟随环境变量 CROSS_CHECK_ENABLED</option>
                  <option :value="true">启用</option>
                  <option :value="false">停用</option>
                </select>
                <span class="tushare-warn">Tushare 单位对拍（T0）未完成前启用可能出现对账偏差告警（只告警，不改数）</span>
              </div>
            </template>
```

  b) script：320 行解构增加 `tushareTokenInput`，新增 `const { clearTushareToken } = settings;`（函数直接解构，同文件既有风格）。
  c) `styles.css` 追加：

```css
.tushare-config {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 0;
}

.tushare-config input {
  max-width: 260px;
}

.tushare-warn {
  font-size: 11px;
  color: var(--muted);
}
```

- [ ] **Step 4: 跑绿** `npx vitest run tests/frontend/ViewSettings.test.ts` → 全绿；`npx vue-tsc --noEmit` 零错误

- [ ] **Step 5: 提交** `git commit -m "feat: 设置页 Tushare 行提供 token 配置与跨源校验三态开关（含 T0 对拍警告）"`

---

### Task 7: 全量门禁 + 文档收口

**Files:**
- Modify: `AGENTS.md`（`cross_check.py` 布局行）
- Modify: `ROADMAP.md`（P2.5 跨源校验行）

- [ ] **Step 1: 全量回归** `npm run verify`（vitest 220+ / vue-tsc / pytest 604+）+ `python -m ruff check backend tests server.py && python -m ruff format --check backend tests server.py && python -m mypy backend` → 全绿
- [ ] **Step 2: 文档**——AGENTS.md 布局行改为 `cross_check.py 日线最新收盘跨源校验（Tushare 主/东财辅；启用=设置页三态开关或 env CROSS_CHECK_ENABLED，默认关）`；ROADMAP P2.5 跨源校验行尾追加 `；2026-10-03 用户裁定：token 与启用开关移至设置页（DB 三态，env 作初始默认），T0 对拍前启用有偏差告警提示`
- [ ] **Step 3: 提交** `git commit -m "docs: 收口 Tushare token/跨源校验开关的 AGENTS 与 ROADMAP 记录"`
- [ ] **Step 4: `git flow feature finish --no-ff tushare-token-settings` 合入 develop，`git push origin develop`**
