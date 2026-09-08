# 策略定时扫描 + 指令推送 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 已启用的策略每日收盘后自动扫描，命中经提醒中心推送（前端合成），点击代码片 → 草案对话框看时重算 → 人工确认落计划。

**Architecture:** 方案 A（spec §10 决议 5）：扫描状态落两张新表（`screener_scan_configs` / `screener_scan_history`），去重引擎 + 编排器 `backend/screener/scan.py` 复用 `ScreenerPipeline.run`；3.5 个新端点挂在 app.py；前端 `useScanStore` 独立端点拉取 + 合成提醒（不进 workspace 同步）；策略实验室配置区加开关。

**Tech Stack:** FastAPI + SQLAlchemy 2.0 + Alembic + APScheduler（现有 BackgroundScheduler）+ redis-py（现有 `redis_client()`）+ Vue 3 + Pinia + vitest。

**Spec:** `docs/superpowers/specs/2026-09-07-strategy-scan-alert-spec.md`（22 条决议为本计划的约束来源）

## Global Constraints

- UI 全中文；绝不造数（数据缺失 → null + warning）；红线：扫描路径零 plans 写入、零券商依赖
- 新 API 字段只增不改；响应包裹沿用 `/api/strategy/strategies` 风格（顶层键名分组，不加 `{data}` 层）
- 提交：Conventional Commits + 中文主题 + `--no-verify`（CRLF 警告良性）
- 提交前 lint 门禁：`python -m ruff format --check backend tests && python -m ruff check backend tests` + `python -m mypy backend`；前端 `npx vue-tsc --noEmit` + eslint 0 error
- 测试一律只跑目标文件（全量门禁留给 Task 8）：`python -m pytest tests/<file> -q --no-cov`、`npx vitest run tests/frontend/<file>.test.ts`
- 复用清单（禁止重造）：`ScreenerPipeline.run`（缓存/限频/降级）、`storage.redis_client()`、`api_error` + `ERR_*`、`grid_scheduler.scheduler` / `TIMEZONE`、`useAssistStore.openFor`、`useWorkspaceStore.refreshAll` / `requestJson` / `showToast`
- 失败方向：任何任务现场与计划不符（行号漂移、签名差异），以现场为准做最小适配并在报告注明——同 trade-assist 惯例
- TDD 强制：每个任务先失败测试后实现，报告须含 RED/GREEN 证据

## File Structure（本计划产出的全部文件）

```
backend/migrations/versions/<gen>_screener_scan_tables.py   # Create: Alembic 迁移（两表）
backend/storage.py                                          # Modify: +2 模型 +6 助手
backend/screener/scan.py                                    # Create: 去重引擎 + 编排 + 调度注册
backend/app.py                                              # Modify: +4 端点（/api/screener/scan/*）
tests/test_scan.py                                          # Create: 存储助手 + 引擎 + 编排 + 端点测试
frontend/src/stores/useScanStore.ts                         # Create: hits/configs/seen/scanAlerts
frontend/src/stores/useWorkspaceStore.ts                    # Modify: refreshAll tasks + fetchHits
frontend/src/stores/useAlertsStore.ts                       # Modify: 合成提醒进过滤/未读
frontend/src/App.vue                                        # Modify: 提醒中心渲染代码片
frontend/src/views/ViewScreener.vue                         # Modify: 策略配置区开关区
tests/frontend/useScanStore.test.ts                         # Create
tests/frontend/useAlertsStore.test.ts                       # Modify（若存在；否则创建最小测试文件）
tests/frontend/ViewScreener.test.ts                         # Modify
ROADMAP.md / AGENTS.md                                      # Modify: Task 8
```

---

### Task 1: 存储层——两张表 + 助手 + Alembic 迁移

**Files:**
- Modify: `backend/storage.py`（模型区追加 + 助手区追加）
- Create: `backend/migrations/versions/<alembic生成id>_screener_scan_tables.py`
- Test: `tests/test_scan.py`（新建；先读 `tests/test_storage_coverage.py` 头部 ~40 行，沿用其真实 DB 访问/fixture 模式）

**Interfaces:**
- Consumes: `Base`（storage.py 声明式基类）、`SessionLocal`、`JSON` 列先例（`TradePlan.triggered` / `StrategyBacktest.config`）
- Produces（后续任务依赖，签名逐字）:
  - `list_scan_configs() -> list[dict[str, Any]]`
  - `get_scan_config(strategy_id: str) -> dict[str, Any] | None`
  - `list_enabled_scan_configs() -> list[dict[str, Any]]`
  - `upsert_scan_config(strategy_id: str, enabled: bool, mode: str, workspace_id: str = "default") -> dict[str, Any]`
  - `update_scan_state(strategy_id: str, status: str, hits: list[dict[str, Any]], run_at: datetime, new_count: int = 0, require_enabled: bool = True) -> bool`（True=已写入，False=require_enabled 且已关闭→跳过）
  - `insert_scan_history(strategy_id: str, status: str, hit_count: int, new_count: int, elapsed_ms: int, trace_id: str) -> None`
- dict 形状：`{"strategyId","enabled","mode","lastRunAt"(datetime|None),"lastStatus"(str|None),"lastHits"(list[dict]|None),"lastNewCount"(int),"workspaceId"}`

- [ ] **Step 1: 写失败测试**（追加到新建 `tests/test_scan.py`；DB 测试沿用 test_storage_coverage 的真实库模式）

```python
"""策略定时扫描：存储助手 + 去重引擎 + 编排 + 端点。"""
from __future__ import annotations

from typing import Any

import pytest


def _cleanup_scan_tables() -> None:
    from backend.storage import ScreenerScanConfig, ScreenerScanHistory, SessionLocal
    from sqlalchemy import delete

    with SessionLocal() as session:
        session.execute(delete(ScreenerScanHistory))
        session.execute(delete(ScreenerScanConfig))
        session.commit()


def test_upsert_and_get_scan_config() -> None:
    _cleanup_scan_tables()
    from backend.storage import get_scan_config, upsert_scan_config

    cfg = upsert_scan_config("trend_breakout", enabled=True, mode="quick")
    assert cfg["strategyId"] == "trend_breakout"
    assert cfg["enabled"] is True and cfg["mode"] == "quick"
    assert cfg["lastStatus"] is None and cfg["lastHits"] is None
    # 二次 upsert 覆盖（同主键更新不插入）
    cfg2 = upsert_scan_config("trend_breakout", enabled=False, mode="deep")
    assert cfg2["enabled"] is False and cfg2["mode"] == "deep"
    assert get_scan_config("trend_breakout")["mode"] == "deep"
    assert get_scan_config("no_such") is None


def test_update_scan_state_roundtrip_and_guard() -> None:
    _cleanup_scan_tables()
    from datetime import UTC, datetime

    from backend.storage import get_scan_config, update_scan_state, upsert_scan_config

    upsert_scan_config("trend_breakout", enabled=True, mode="quick")
    hits = [{"code": "600519", "name": "贵州茅台", "score": 82.5, "firstSeen": "2026-09-07"}]
    now = datetime.now(UTC)
    assert update_scan_state("trend_breakout", "ok", hits, now, new_count=1) is True
    cfg = get_scan_config("trend_breakout")
    assert cfg["lastStatus"] == "ok" and cfg["lastHits"] == hits and cfg["lastNewCount"] == 1
    # require_enabled 守卫：关闭后写入被拒
    upsert_scan_config("trend_breakout", enabled=False, mode="quick")
    assert update_scan_state("trend_breakout", "ok", hits, now, require_enabled=True) is False
    assert update_scan_state("trend_breakout", "ok", hits, now, require_enabled=False) is True


def test_update_scan_state_bad_json_tolerance() -> None:
    _cleanup_scan_tables()
    from backend.storage import get_scan_config, update_scan_state, upsert_scan_config

    upsert_scan_config("oversold_bounce", enabled=True, mode="quick")
    # 直接把 last_hits 破坏成坏 JSON（模拟外部污染）
    from backend.storage import ScreenerScanConfig, SessionLocal
    from sqlalchemy import update as sa_update

    with SessionLocal() as session:
        session.execute(
            sa_update(ScreenerScanConfig).values(last_hits="{not-json").where(
                ScreenerScanConfig.id == "oversold_bounce"
            )
        )
        session.commit()
    # 读路径容错：坏 JSON → None（不抛异常）
    assert get_scan_config("oversold_bounce")["lastHits"] is None
    # 写路径可正常覆盖恢复
    update_scan_state("oversold_bounce", "ok", [], datetime.now(UTC))
    assert get_scan_config("oversold_bounce")["lastHits"] == []


def test_insert_scan_history_rolling_cleanup() -> None:
    _cleanup_scan_tables()
    from datetime import UTC, datetime

    from backend.storage import insert_scan_history, list_scan_history
    from sqlalchemy import func, select, SessionLocal  # noqa: F401  （SessionLocal 导入见下）

    for i in range(7):
        insert_scan_history("trend_breakout", "ok", hit_count=10 + i, new_count=i, elapsed_ms=100 * i, trace_id=f"t{i}")
    rows = list_scan_history("trend_breakout")
    assert len(rows) == 7 and rows[0]["newCount"] == 6  # 按 run_at 降序，最新在前
```

注意：`list_scan_history` 是本任务第 7 个助手（spec §4.1 未列名，实现为 history 表读取助手，供运维/未来绩效复盘用）：`list_scan_history(strategy_id: str | None = None, limit: int = 50) -> list[dict]`，dict 形状 `{"id","strategyId","runAt","status","hitCount","newCount","elapsedMs","traceId"}`。删除 `from sqlalchemy import ... SessionLocal` 那行的错误导入（SessionLocal 来自 backend.storage），以上注释仅为提示，最终以通过 pytest 为准。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_scan.py -q --no-cov`
Expected: FAIL — `ImportError: cannot import name 'ScreenerScanConfig'`

- [ ] **Step 3: 实现**（storage.py 模型区追加；JSON 列仿 `StrategyBacktest.config` 写法）

```python
class ScreenerScanConfig(Base):
    """策略定时扫描配置（策略本体是包内 JSON，用户状态落库）。"""

    __tablename__ = "screener_scan_configs"

    id: Mapped[str] = mapped_column(String(96), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    enabled: Mapped[bool] = mapped_column(default=False)
    mode: Mapped[str] = mapped_column(String(8), default="quick")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_hits: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    last_new_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class ScreenerScanHistory(Base):
    """扫描运行摘要（FR-12）：仅计数不存明细，全表滚动 500 行。"""

    __tablename__ = "screener_scan_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    strategy_id: Mapped[str] = mapped_column(String(96), index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)
    status: Mapped[str] = mapped_column(String(16))
    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    new_count: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    trace_id: Mapped[str] = mapped_column(String(16), default="")
```

助手（助手区追加；`_scan_config_dict` 仿 `_alert_dict`）：

```python
def _scan_config_dict(cfg: ScreenerScanConfig) -> dict[str, Any]:
    return {
        "strategyId": cfg.id,
        "workspaceId": cfg.workspace_id,
        "enabled": bool(cfg.enabled),
        "mode": cfg.mode,
        "lastRunAt": cfg.last_run_at,
        "lastStatus": cfg.last_status,
        "lastHits": cfg.last_hits,
        "lastNewCount": int(cfg.last_new_count or 0),
    }


def _parse_scan_hits(raw: Any) -> list[dict[str, Any]] | None:
    """last_hits JSON 容错：坏 JSON / 异形结构 → None（视为从未扫描）。"""
    if raw is None:
        return None
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict) and item.get("code")]
    return None


def list_scan_configs() -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(select(ScreenerScanConfig).order_by(ScreenerScanConfig.id)).all()
        return [_scan_config_dict(c) for c in rows]


def get_scan_config(strategy_id: str) -> dict[str, Any] | None:
    with SessionLocal() as session:
        cfg = session.get(ScreenerScanConfig, strategy_id)
        if cfg is None:
            return None
        d = _scan_config_dict(cfg)
        d["lastHits"] = _parse_scan_hits(cfg.last_hits)
        return d


def list_enabled_scan_configs() -> list[dict[str, Any]]:
    with SessionLocal() as session:
        rows = session.scalars(
            select(ScreenerScanConfig).where(ScreenerScanConfig.enabled.is_(True)).order_by(ScreenerScanConfig.id)
        ).all()
        return [_scan_config_dict(c) for c in rows]


def upsert_scan_config(strategy_id: str, enabled: bool, mode: str, workspace_id: str = "default") -> dict[str, Any]:
    with SessionLocal.begin() as session:
        cfg = session.get(ScreenerScanConfig, strategy_id)
        if cfg is None:
            cfg = ScreenerScanConfig(id=strategy_id, workspace_id=workspace_id)
            session.add(cfg)
        cfg.enabled = bool(enabled)
        cfg.mode = mode
        cfg.workspace_id = workspace_id
    return get_scan_config(strategy_id)  # type: ignore[return-value]


def update_scan_state(
    strategy_id: str,
    status: str,
    hits: list[dict[str, Any]],
    run_at: datetime,
    new_count: int = 0,
    require_enabled: bool = True,
) -> bool:
    with SessionLocal.begin() as session:
        cfg = session.get(ScreenerScanConfig, strategy_id)
        if cfg is None:
            return False
        if require_enabled and not cfg.enabled:
            return False
        cfg.last_status = status
        cfg.last_hits = hits
        cfg.last_run_at = run_at
        cfg.last_new_count = int(new_count)
        return True


def insert_scan_history(
    strategy_id: str, status: str, hit_count: int, new_count: int, elapsed_ms: int, trace_id: str
) -> None:
    with SessionLocal.begin() as session:
        session.add(
            ScreenerScanHistory(
                strategy_id=strategy_id, status=status, hit_count=hit_count,
                new_count=new_count, elapsed_ms=elapsed_ms, trace_id=trace_id,
            )
        )
        session.execute(text("DELETE FROM screener_scan_history WHERE id NOT IN (SELECT id FROM screener_scan_history ORDER BY id DESC LIMIT 500)"))


def list_scan_history(strategy_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    with SessionLocal() as session:
        stmt = select(ScreenerScanHistory).order_by(ScreenerScanHistory.id.desc()).limit(limit)
        if strategy_id is not None:
            stmt = stmt.where(ScreenerScanHistory.strategy_id == strategy_id)
        return [
            {
                "id": r.id, "strategyId": r.strategy_id, "runAt": r.run_at, "status": r.status,
                "hitCount": r.hit_count, "newCount": r.new_count, "elapsedMs": r.elapsed_ms, "traceId": r.trace_id,
            }
            for r in session.scalars(stmt).all()
        ]
```

注意：`Integer` 若未导入需并入现有 `from sqlalchemy import ...` 行（只增不改）；`text` 同理（storage.py:205 已在用 `text`，应已导入）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_scan.py -q --no-cov`
Expected: PASS（4 项）

- [ ] **Step 5: Alembic 迁移**

```powershell
alembic revision --autogenerate -m "screener scan tables"
```

生成后**人工修剪**：只保留 `screener_scan_configs` 与 `screener_scan_history` 两表及其索引（`grid_strategies.last_backtest_at/latest_metrics` 等是 storage.py 运行时 raw-SQL 拥有的列，autogenerate 会误报——删除那些 op）。核对 `down_revision` 指向 `c1a08e78583e`，`downgrade()` 完整 drop 两表。执行 `alembic upgrade head` 并跑 `alembic downgrade -1 && alembic upgrade head` 往返验证。

- [ ] **Step 6: lint + 提交**

Run: `python -m ruff format backend/storage.py tests/test_scan.py && python -m ruff format --check backend tests && python -m ruff check backend tests && python -m mypy backend`

```bash
git add backend/storage.py backend/migrations/versions/ tests/test_scan.py
git commit -m "feat: 扫描配置与历史两张表 + 存储助手（Alembic 迁移）" --no-verify
```

---

### Task 2: 去重引擎纯函数（merge_hits）

**Files:**
- Create: `backend/screener/scan.py`
- Test: `tests/test_scan.py`（追加）

**Interfaces:**
- Consumes: 无（纯函数）
- Produces: `merge_hits(prev_hits: list[dict[str, Any]], rows: list[dict[str, Any]], today: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]` → `(newly_entered, new_state)`。entry 形状 `{"code","name","score","firstSeen"}`；`rows` 条目为管道命中行（`code`/`name` 必有，`score` 可缺省 None）。

- [ ] **Step 1: 写失败测试**（追加 tests/test_scan.py）

```python
def test_merge_hits_three_states() -> None:
    from backend.screener.scan import merge_hits

    prev = [
        {"code": "600519", "name": "贵州茅台", "score": 82.5, "firstSeen": "2026-09-04"},
        {"code": "300750", "name": "宁德时代", "score": 77.0, "firstSeen": "2026-09-04"},
    ]
    rows = [
        {"code": "600519", "name": "贵州茅台", "score": 83.0},
        {"code": "510300", "name": "沪深300ETF", "score": 71.2},
    ]
    newly, state = merge_hits(prev, rows, today="2026-09-07")
    # 新进入：510300（600519 滞留保持 firstSeen，300750 跌出）
    assert newly == [{"code": "510300", "name": "沪深300ETF", "score": 71.2, "firstSeen": "2026-09-07"}]
    assert state == [
        {"code": "600519", "name": "贵州茅台", "score": 83.0, "firstSeen": "2026-09-04"},
        {"code": "510300", "name": "沪深300ETF", "score": 71.2, "firstSeen": "2026-09-07"},
    ]


def test_merge_hits_empty_prev_and_empty_rows() -> None:
    from backend.screener.scan import merge_hits

    # 首扫：全部为新
    newly, state = merge_hits([], [{"code": "600519", "name": "贵州茅台"}], today="2026-09-07")
    assert newly == [{"code": "600519", "name": "贵州茅台", "score": None, "firstSeen": "2026-09-07"}]
    # 全部跌出：newly 空，state 空
    prev = [{"code": "600519", "name": "贵州茅台", "score": 82.5, "firstSeen": "2026-09-04"}]
    newly2, state2 = merge_hits(prev, [], today="2026-09-07")
    assert newly2 == [] and state2 == []


def test_merge_hits_ignores_malformed_rows() -> None:
    from backend.screener.scan import merge_hits

    newly, state = merge_hits([], [{"name": "无代码行"}, {"code": "600519", "name": "贵州茅台"}], today="2026-09-07")
    assert len(newly) == 1 and newly[0]["code"] == "600519"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_scan.py -q --no-cov`
Expected: FAIL — `ModuleNotFoundError: No module named 'backend.screener.scan'`

- [ ] **Step 3: 实现**（backend/screener/scan.py 新建）

```python
"""策略定时扫描：去重引擎 + 编排 + 调度注册（spec 2026-09-07，方案 A）。"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger("screener.scan")


def merge_hits(
    prev_hits: list[dict[str, Any]], rows: list[dict[str, Any]], today: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """跌出再报去重（FR-4）：返回 (新进入命中, 新滞留状态)。

    - 新进入：当前 rows 中存在、prev 中不存在的代码，firstSeen=today
    - 滞留：两轮都在，保留原 firstSeen、更新 name/score
    - 跌出：prev 有、rows 无 → 从状态中移除（下次再进算新）
    """
    prev_by_code = {str(p.get("code")): p for p in prev_hits if p.get("code")}
    new_state: list[dict[str, Any]] = []
    newly: list[dict[str, Any]] = []
    for row in rows:
        code = row.get("code")
        if not code:
            continue
        code = str(code)
        entry = {"code": code, "name": str(row.get("name") or ""), "score": row.get("score")}
        prev_entry = prev_by_code.pop(code, None)
        if prev_entry is None:
            entry["firstSeen"] = today
            newly.append(entry)
        else:
            entry["firstSeen"] = str(prev_entry.get("firstSeen") or today)
        new_state.append(entry)
    return newly, new_state
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_scan.py -q --no-cov`
Expected: PASS（7 项）

- [ ] **Step 5: lint + 提交**

```bash
git add backend/screener/scan.py tests/test_scan.py
git commit -m "feat: 扫描跌出再报去重引擎（纯函数）" --no-verify
```

---

### Task 3: 扫描编排 + 护栏（run_scan / run_all_scans / register_scan_jobs）

**Files:**
- Modify: `backend/screener/scan.py`（编排区追加）
- Test: `tests/test_scan.py`（追加）

**Interfaces:**
- Consumes: `merge_hits`（Task 2）、`ScreenerPipeline.run`（backend/screener/pipeline.py，返回 dict 含 `rows`/`total`/`stale`/`elapsedMs`/`referenceDate`）、storage 助手（Task 1）、`storage.redis_client()`（storage.py:209，socket 超时 2s）、`grid_scheduler.scheduler` + `grid_scheduler.TIMEZONE`
- Produces:
  - `run_scan(strategy_id: str, mode: str = "quick", pipeline: Any | None = None, now: datetime | None = None) -> dict` → `{"strategyId","status","hitCount","newCount","elapsedMs","traceId","stale"}`
  - `run_all_scans() -> list[dict]`（顺序执行所有 enabled）
  - `run_scan_retry(strategy_id: str) -> dict | None`（重试入口，enabled 前置校验）
  - `register_scan_jobs() -> None`（幂等；在 `grid_scheduler.start_scheduler()` 末尾被调用——本任务同时改 grid_scheduler.py 一行）

- [ ] **Step 1: 写失败测试**（追加；Redis 用 FakeRedis 替身、管道用 FakePipeline，**不起真调度器**——register 的单测只断言 job 注册调用参数）

```python
class _FakeRedis:
    """SET NX PX / GET / 评估释放的最小替身（同进程语义即可）。"""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def set(self, key: str, value: str, nx: bool = False, px: int = 0) -> bool | None:
        if nx and key in self.store:
            return None
        self.store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def delete(self, key: str) -> int:
        return 1 if self.store.pop(key, None) is not None else 0

    def eval(self, script: str, numkeys: int, *keys_and_args: Any) -> Any:  # 释放脚本原样执行语义
        key, token = keys_and_args[0], keys_and_args[1]
        return 1 if self.store.get(key) == token else 0


class _FakePipeline:
    """run() 返回预设 rows；可注入异常。"""

    def __init__(self, rows: list[dict[str, Any]] | None = None, error: Exception | None = None) -> None:
        self.rows = rows or []
        self.error = error
        self.calls: list[tuple[str, str]] = []

    def run(self, strategy_id: str, mode: str = "quick", refresh: bool = False, reference_date: str | None = None) -> dict[str, Any]:
        if self.error:
            raise self.error
        self.calls.append((strategy_id, mode))
        return {"strategy": strategy_id, "name": strategy_id, "mode": mode, "referenceDate": "2026-09-05",
                "provider": "腾讯", "rows": self.rows, "total": len(self.rows), "cached": False,
                "stale": False, "elapsedMs": 123}


_ROWS_TWO = [
    {"code": "600519", "name": "贵州茅台", "score": 82.5},
    {"code": "300750", "name": "宁德时代", "score": 77.0},
]


def _setup_one_enabled(monkeypatch: Any, strategy_id: str = "trend_breakout") -> None:
    _cleanup_scan_tables()
    from backend.storage import upsert_scan_config

    upsert_scan_config(strategy_id, enabled=True, mode="quick")


def test_run_scan_first_scan_creates_state(monkeypatch: Any) -> None:
    _setup_one_enabled(monkeypatch)
    from backend.screener import scan as scan_module

    fake = _FakeRedis()
    monkeypatch.setattr(scan_module, "redis_client", lambda: fake)
    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: _FakePipeline(rows=_ROWS_TWO))
    result = scan_module.run_scan("trend_breakout")
    assert result["status"] == "ok" and result["hitCount"] == 2 and result["newCount"] == 2
    from backend.storage import get_scan_config
    cfg = get_scan_config("trend_breakout")
    assert cfg["lastStatus"] == "ok" and len(cfg["lastHits"]) == 2
    assert all(h["firstSeen"] == result["traceId"] or True for h in cfg["lastHits"])  # firstSeen = 扫描日
    # 历史摘要已插入
    from backend.storage import list_scan_history
    assert list_scan_history("trend_breakout")[0]["newCount"] == 2


def test_run_scan_failure_isolated_and_records_failed(monkeypatch: Any) -> None:
    _setup_one_enabled(monkeypatch)
    from backend.screener import scan as scan_module

    monkeypatch.setattr(scan_module, "redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: _FakePipeline(error=RuntimeError("upstream down")))
    result = scan_module.run_scan("trend_breakout")
    assert result["status"] == "failed"
    from backend.storage import get_scan_config
    assert get_scan_config("trend_breakout")["lastStatus"] == "failed"


def test_run_all_scans_sequential_and_failure_isolation(monkeypatch: Any) -> None:
    _cleanup_scan_tables()
    from backend.storage import upsert_scan_config
    upsert_scan_config("trend_breakout", enabled=True, mode="quick")
    upsert_scan_config("oversold_bounce", enabled=True, mode="quick")
    from backend.screener import scan as scan_module

    monkeypatch.setattr(scan_module, "redis_client", lambda: _FakeRedis())
    # 第一个策略炸、第二个正常：验证继续执行（失败隔离）
    def fake_run(strategy_id: str, mode: str = "quick", **kwargs: Any) -> dict[str, Any]:
        if strategy_id == "trend_breakout":
            raise RuntimeError("boom")
        return _FakePipeline(rows=_ROWS_TWO).run(strategy_id, mode)
    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: type("P", (), {"run": staticmethod(fake_run)})())
    results = scan_module.run_all_scans()
    assert len(results) == 2
    assert {r["strategyId"]: r["status"] for r in results} == {
        "trend_breakout": "failed", "oversold_bounce": "ok",
    }


def test_run_all_scans_disabled_midway_skips_state_write(monkeypatch: Any) -> None:
    _setup_one_enabled(monkeypatch)
    from backend.screener import scan as scan_module

    monkeypatch.setattr(scan_module, "redis_client", lambda: _FakeRedis())
    calls: list[str] = []

    def fake_run(strategy_id: str, mode: str = "quick", **kwargs: Any) -> dict[str, Any]:
        calls.append(strategy_id)
        # 首次调用后关闭开关（模拟扫描中途用户关闭）
        from backend.storage import upsert_scan_config
        upsert_scan_config(strategy_id, enabled=False, mode="quick")
        return _FakePipeline(rows=_ROWS_TWO).run(strategy_id, mode)

    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: type("P", (), {"run": staticmethod(fake_run)})())
    result = scan_module.run_scan("trend_breakout")
    # FR-13⑤：require_enabled 拦截 → last_status 不被覆盖
    from backend.storage import get_scan_config
    assert get_scan_config("trend_breakout")["lastStatus"] is None
    assert result["status"] == "skipped"


def test_run_all_scans_lock_blocks_second_runner(monkeypatch: Any) -> None:
    _setup_one_enabled(monkeypatch)
    from backend.screener import scan as scan_module

    fake = _FakeRedis()
    fake.set("scan:lock", "other-worker", nx=True, px=900_000)  # 他人持锁
    monkeypatch.setattr(scan_module, "redis_client", lambda: fake)
    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: _FakePipeline(rows=_ROWS_TWO))
    results = scan_module.run_all_scans()
    assert results == []  # 未获锁直接返回空，不执行


def test_run_all_scans_degrades_without_redis(monkeypatch: Any) -> None:
    _setup_one_enabled(monkeypatch)
    from backend.screener import scan as scan_module

    def boom() -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr(scan_module, "redis_client", boom)
    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: _FakePipeline(rows=_ROWS_TWO))
    results = scan_module.run_all_scans()
    assert len(results) == 1 and results[0]["status"] == "ok"  # 降级无锁继续


def test_register_scan_jobs_registers_two_crons_and_misfire_listener(monkeypatch: Any) -> None:
    from backend.grid_scheduler import TIMEZONE
    from backend.screener import scan as scan_module

    added: list[tuple[str, str, str]] = []

    class _FakeScheduler:
        running = True

        def add_job(self, func: Any, trigger: Any, id: str, replace_existing: bool = True, **kwargs: Any) -> None:
            added.append((id, str(trigger), str(kwargs.get("misfire_grace_time"))))

        def get_job(self, job_id: str) -> None:
            return None

        def remove_job(self, job_id: str) -> None:
            pass

        def add_listener(self, cb: Any, mask: int | None = None) -> None:
            added.append(("listener", str(mask), ""))

    fake_sched = _FakeScheduler()
    monkeypatch.setattr(scan_module, "_scheduler", fake_sched)
    scan_module.register_scan_jobs()
    ids = [a[0] for a in added]
    assert "scan:weekday" in ids and "scan:weekend" in ids and any(i == "listener" for i in ids)
    # cron 时刻正确（15:40 / 10:00）且时区为 Asia/Shanghai
    weekday = next(a for a in added if a[0] == "scan:weekday")
    assert "15" in weekday[1] and "40" in weekday[1] and "Asia/Shanghai" in weekday[1]
    weekend = next(a for a in added if a[0] == "scan:weekend")
    assert "10" in weekend[1] and "Asia/Shanghai" in weekend[1]
```

注意：`test_run_scan_first_scan_creates_state` 里 firstSeen 断言那行 `or True` 是占位痕迹——**最终断言应为** `assert all(h["firstSeen"] for h in cfg["lastHits"])` 且 `now` 参数可控：`run_scan` 接受 `now: datetime | None`，测试传 `datetime(2026, 9, 7, 7, 40, tzinfo=UTC)`，断言 `all(h["firstSeen"] == "2026-09-07" ...)`。写测试时直接用后者，勿留 or True。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_scan.py -q --no-cov`
Expected: FAIL — `AttributeError: module 'backend.screener.scan' has no attribute 'run_scan'`

- [ ] **Step 3: 实现**（scan.py 编排区追加；grid_scheduler.py start_scheduler 末尾加一行）

```python
# ---- 编排（Task 3 追加区） ----
import threading

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from backend.grid_scheduler import TIMEZONE, scheduler as _scheduler
from backend.storage import (
    get_scan_config,
    insert_scan_history,
    list_enabled_scan_configs,
    update_scan_state,
)

_LOCK_KEY = "scan:lock"
_LOCK_TTL_MS = 15 * 60 * 1000
_LOCK_TOKEN = uuid.uuid4().hex
_RELEASE_LUA = (
    "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
)
_pipeline: Any | None = None
_pipeline_lock = threading.Lock()


def _get_pipeline() -> Any:
    """单例管道：与 app.py _strategy_pipeline 同模式（懒建，测试可 monkeypatch 本函数）。"""
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            from backend.screener.pipeline import ScreenerPipeline
            from backend.sources import build_router
            from backend.storage import get_workspace_settings

            _pipeline = ScreenerPipeline(build_router(), settings_getter=lambda: get_workspace_settings("default"))
        return _pipeline


def _try_acquire_lock() -> tuple[bool, Any]:
    try:
        client = redis_client()
        got = client.set(_LOCK_KEY, _LOCK_TOKEN, nx=True, px=_LOCK_TTL_MS)
        if not got:
            return False, client
        return True, client
    except Exception:
        logger.warning("screener.scan_lock_unavailable", extra={"reason": "redis 不可用，降级无锁"})
        return True, None


def _release_lock(client: Any) -> None:
    if client is None:
        return
    try:
        client.eval(_RELEASE_LUA, 1, _LOCK_KEY, _LOCK_TOKEN)
    except Exception:
        logger.warning("screener.scan_lock_release_failed", extra={"reason": "锁释放失败，等 TTL 到期"})


def run_scan(
    strategy_id: str,
    mode: str = "quick",
    pipeline: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """单策略扫描：管道 → 去重 → 状态/历史写入（含 enabled 前置校验 FR-13⑤）。"""
    started = time.monotonic()
    trace_id = uuid.uuid4().hex[:12]
    now = now or datetime.now(UTC)
    today = now.astimezone(TIMEZONE).date().isoformat()
    engine = pipeline or _get_pipeline()
    try:
        result = engine.run(strategy_id, mode=mode, refresh=False)
        rows = list(result.get("rows") or [])
        stale = bool(result.get("stale"))
    except Exception as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        logger.error(
            "screener.scan_failed",
            extra={"trace_id": trace_id, "strategy_id": strategy_id, "mode": mode, "error": str(exc)[:200]},
        )
        update_scan_state(strategy_id, "failed", [], now)  # require_enabled 默认 True
        insert_scan_history(strategy_id, "failed", 0, 0, elapsed, trace_id)
        return {"strategyId": strategy_id, "status": "failed", "hitCount": 0, "newCount": 0,
                "elapsedMs": elapsed, "traceId": trace_id, "stale": False}
    prev_hits = (get_scan_config(strategy_id) or {}).get("lastHits") or []
    newly, new_state = merge_hits(prev_hits, rows, today=today)
    elapsed = int((time.monotonic() - started) * 1000)
    written = update_scan_state(strategy_id, "ok", new_state, now, new_count=len(newly))
    insert_scan_history(strategy_id, "ok", len(new_state), len(newly), elapsed, trace_id)
    if not written:
        # 扫描中途被关闭（FR-13⑤）：状态不覆盖，结果仅入历史
        return {"strategyId": strategy_id, "status": "skipped", "hitCount": len(new_state),
                "newCount": len(newly), "elapsedMs": elapsed, "traceId": trace_id, "stale": stale}
    logger.info(
        "screener.scan",
        extra={"trace_id": trace_id, "strategy_id": strategy_id, "mode": mode,
               "hit_count": len(new_state), "new_count": len(newly), "elapsed_ms": elapsed, "stale": stale},
    )
    return {"strategyId": strategy_id, "status": "ok", "hitCount": len(new_state),
            "newCount": len(newly), "elapsedMs": elapsed, "traceId": trace_id, "stale": stale}


def _schedule_retry(strategy_id: str) -> None:
    from datetime import timedelta

    _scheduler.add_job(
        run_scan_retry,
        DateTrigger(run_date=datetime.now(TIMEZONE) + timedelta(minutes=10)),
        args=[strategy_id],
        id=f"scan:retry:{strategy_id}",
        replace_existing=True,
    )


def run_scan_retry(strategy_id: str) -> dict[str, Any] | None:
    """单次重试（FR-13②）：触发时先校验 enabled，已关闭直接跳过（不跑管道）。"""
    cfg = get_scan_config(strategy_id)
    if cfg is None or not cfg["enabled"]:
        logger.info("screener.scan_retry_skipped", extra={"strategy_id": strategy_id, "reason": "已关闭"})
        return None
    return run_scan(strategy_id)


def run_all_scans() -> list[dict[str, Any]]:
    """顺序扫描全部启用策略；Redis 锁互斥（FR-13①）；失败隔离 + 单次重试武装。"""
    acquired, client = _try_acquire_lock()
    if not acquired:
        logger.info("screener.scan_skipped_locked", extra={"reason": "其他 worker 持锁"})
        return []
    try:
        results: list[dict[str, Any]] = []
        for cfg in list_enabled_scan_configs():
            strategy_id = cfg["strategyId"]
            result = run_scan(strategy_id, mode=str(cfg.get("mode") or "quick"))
            results.append(result)
            if result["status"] == "failed":
                _schedule_retry(strategy_id)
        return results
    finally:
        _release_lock(client)


def _on_job_missed(event: Any) -> None:
    logger.warning("screener.scan_job_missed", extra={"job_id": getattr(event, "job_id", "")})


def register_scan_jobs() -> None:
    """两个 cron（FR-2）+ misfire 监听（FR-13③）；幂等（replace_existing）。"""
    _scheduler.add_job(
        run_all_scans,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=40, timezone=TIMEZONE),
        id="scan:weekday",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        run_all_scans,
        CronTrigger(day_of_week="sat,sun", hour=10, minute=0, timezone=TIMEZONE),
        id="scan:weekend",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    from apscheduler.events import EVENT_JOB_MISSED

    _scheduler.add_listener(_on_job_missed, EVENT_JOB_MISSED)
```

grid_scheduler.py 改动（唯一一行）：

```python
def start_scheduler() -> None:
    if not scheduler.running:
        scheduler.start()
    for strategy in list_scheduled_grid_strategies():
        schedule_strategy(strategy)
    for strategy in list_scheduled_strategies():
        schedule_strategy(strategy)
    from backend.screener.scan import register_scan_jobs  # 本地导入避免模块加载期循环

    register_scan_jobs()
```

注意循环导入风险：scan.py 顶部 `from backend.grid_scheduler import ...` 与 grid_scheduler 函数体内 `from backend.screener.scan import ...`——函数内本地导入打破环（上面已如此写）。若实测仍有环，改 scan.py 顶部为函数内惰性获取（报告注明）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_scan.py -q --no-cov`
Expected: PASS（全部，含 Task 1/2 项）

- [ ] **Step 5: lint + 提交**

```bash
git add backend/screener/scan.py backend/grid_scheduler.py tests/test_scan.py
git commit -m "feat: 扫描编排与护栏（Redis 锁/单次重试/misfire 监听/降级）" --no-verify
```

---

### Task 4: API 端点（configs / hits / now）

**Files:**
- Modify: `backend/app.py`（在 `/api/screener/strategy` 端点之后、`/api/assist/plan-draft` 之前插入 4 条路由）
- Test: `tests/test_scan.py`（追加）

**Interfaces:**
- Consumes: Task 1/3 的助手与 `run_scan`；`load_strategy`（backend/screener/loader.py，未知 id 抛 ValueError）；`api_error` + `ERR_VALIDATION_ERROR` / `ERR_UPSTREAM_UNAVAILABLE`；`get_workspace_settings`（module-level，测试可 monkeypatch app 模块名）
- Produces（前端 Task 5 依赖）:
  - `GET /api/screener/scan/configs` → `{"configs": [{"strategyId","strategyName","enabled","mode","lastRunAt","lastStatus","hitCount","newCount"}]}`
  - `PUT /api/screener/scan/configs` ← `{"strategyId","enabled","mode"}` → `{"config": <单条>}`；422 未知策略/非法 mode
  - `POST /api/screener/scan/now` ← `{"strategyId"}` → `{"config": <单条>, "alerted": int}`；422 未知策略；502 管道失败
  - `GET /api/screener/scan/hits` → `{"hits": [{"strategyId","strategyName","scannedAt","status","codes":[...]}]}`

- [ ] **Step 1: 写失败测试**（追加；client 模式仿 test_settings_api.py 的 inline TestClient——先读该文件头 30 行确认现场 fixture 写法）

```python
def _scan_client(monkeypatch: Any) -> Any:
    from fastapi.testclient import TestClient

    from backend import app as app_module

    monkeypatch.setattr(app_module, "get_workspace_settings", lambda *_a, **_k: {"defaultCapital": 100000})
    return TestClient(app_module.create_app())


def test_scan_configs_lists_with_names(monkeypatch: Any) -> None:
    _cleanup_scan_tables()
    from backend.storage import upsert_scan_config
    upsert_scan_config("trend_breakout", enabled=True, mode="quick")
    client = _scan_client(monkeypatch)
    resp = client.get("/api/screener/scan/configs")
    assert resp.status_code == 200
    cfg = resp.json()["configs"][0]
    assert cfg["strategyId"] == "trend_breakout"
    assert cfg["strategyName"] and cfg["strategyName"] != "（策略已不存在）"
    assert cfg["hitCount"] == 0 and cfg["newCount"] == 0


def test_scan_put_validates(monkeypatch: Any) -> None:
    _cleanup_scan_tables()
    client = _scan_client(monkeypatch)
    assert client.put("/api/screener/scan/configs", json={"strategyId": "no_such_strategy", "enabled": True, "mode": "quick"}).status_code == 422
    assert client.put("/api/screener/scan/configs", json={"strategyId": "trend_breakout", "enabled": True, "mode": "macd"}).status_code == 422
    ok = client.put("/api/screener/scan/configs", json={"strategyId": "trend_breakout", "enabled": True, "mode": "deep"})
    assert ok.status_code == 200 and ok.json()["config"]["mode"] == "deep" and ok.json()["config"]["enabled"] is True


def test_scan_now_runs_and_returns(monkeypatch: Any) -> None:
    _cleanup_scan_tables()
    client = _scan_client(monkeypatch)
    from backend.screener import scan as scan_module

    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: _FakePipeline(rows=_ROWS_TWO))
    monkeypatch.setattr(scan_module, "redis_client", lambda: _FakeRedis())
    # PUT 走真实路径（写 DB），POST now 被 monkeypatch 的 pipeline 驱动
    client.put("/api/screener/scan/configs", json={"strategyId": "trend_breakout", "enabled": True, "mode": "quick"})
    resp = client.post("/api/screener/scan/now", json={"strategyId": "trend_breakout"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["alerted"] == 2 and body["config"]["hitCount"] == 2
    # 失败路径 → 502
    monkeypatch.setattr(scan_module, "_get_pipeline", lambda: _FakePipeline(error=RuntimeError("down")))
    assert client.post("/api/screener/scan/now", json={"strategyId": "trend_breakout"}).status_code == 502


def test_scan_hits_only_enabled(monkeypatch: Any) -> None:
    _cleanup_scan_tables()
    from datetime import UTC, datetime

    from backend.storage import update_scan_state, upsert_scan_config
    upsert_scan_config("trend_breakout", enabled=True, mode="quick")
    upsert_scan_config("oversold_bounce", enabled=False, mode="quick")
    update_scan_state("trend_breakout", "ok", _ROWS_TWO_FIRSTSEEN := [
        {"code": "600519", "name": "贵州茅台", "score": 82.5, "firstSeen": "2026-09-05"}
    ], datetime(2026, 9, 5, 7, 40, tzinfo=UTC))
    client = _scan_client(monkeypatch)
    resp = client.get("/api/screener/scan/hits")
    hits = resp.json()["hits"]
    assert len(hits) == 1 and hits[0]["strategyId"] == "trend_breakout"
    assert hits[0]["codes"][0]["firstSeen"] == "2026-09-05" and hits[0]["scannedAt"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_scan.py -q --no-cov`
Expected: FAIL — 404（路由不存在）

- [ ] **Step 3: 实现**（app.py 端点区追加；import 区加 `from backend.screener.scan import run_scan`——与 `_strategy_pipeline` 同区）

```python
    _scan_pipeline_probe: dict[str, Any] = {}

    def _scan_config_out(cfg: dict[str, Any]) -> dict[str, Any]:
        from backend.screener.loader import load_strategy

        try:
            name = str(load_strategy(cfg["strategyId"]).name)
        except ValueError:
            name = "（策略已不存在）"
        return {
            "strategyId": cfg["strategyId"],
            "strategyName": name,
            "enabled": cfg["enabled"],
            "mode": cfg["mode"],
            "lastRunAt": cfg["lastRunAt"].isoformat() if cfg["lastRunAt"] else None,
            "lastStatus": cfg["lastStatus"],
            "hitCount": len(cfg["lastHits"] or []),
            "newCount": int(cfg["lastNewCount"] or 0),
        }

    @app.get("/api/screener/scan/configs")
    def scan_configs_list() -> dict[str, Any]:
        return {"configs": [_scan_config_out(c) for c in list_scan_configs()]}

    @app.put("/api/screener/scan/configs")
    def scan_configs_put(payload: dict[str, Any]) -> dict[str, Any]:
        strategy_id = str(payload.get("strategyId") or "")
        mode = str(payload.get("mode") or "quick")
        if not isinstance(payload.get("enabled"), bool) or mode not in ("quick", "deep"):
            raise api_error(422, ERR_VALIDATION_ERROR, "enabled 必须为 bool，mode 须为 quick|deep")
        try:
            from backend.screener.loader import load_strategy

            load_strategy(strategy_id)
        except ValueError as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc))
        cfg = upsert_scan_config(strategy_id, bool(payload["enabled"]), mode)
        # 审计日志（二轮决议 14）：本地单用户，记录变更本身
        logger.info("screener.scan_config_changed", extra={"strategy_id": strategy_id, "enabled": bool(payload["enabled"]), "mode": mode})
        return {"config": _scan_config_out(cfg)}

    @app.post("/api/screener/scan/now")
    def scan_now(payload: dict[str, Any]) -> dict[str, Any]:
        strategy_id = str(payload.get("strategyId") or "")
        try:
            from backend.screener.loader import load_strategy

            load_strategy(strategy_id)
        except ValueError as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc))
        from backend.screener.scan import run_scan

        result = run_scan(strategy_id)
        if result["status"] == "failed":
            raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, "扫描失败（上游不可用），稍后可重试")
        cfg = get_scan_config(strategy_id) or {}
        return {"config": _scan_config_out(cfg), "alerted": int(result["newCount"])}

    @app.get("/api/screener/scan/hits")
    def scan_hits() -> dict[str, Any]:
        from backend.screener.loader import load_strategy

        hits: list[dict[str, Any]] = []
        for cfg in list_enabled_scan_configs():
            try:
                name = str(load_strategy(cfg["strategyId"]).name)
            except ValueError:
                continue  # 策略已不存在 → 不进 hits
            codes = [
                {"code": h.get("code"), "name": h.get("name"), "score": h.get("score"), "firstSeen": h.get("firstSeen")}
                for h in (cfg["lastHits"] or [])
            ]
            hits.append({
                "strategyId": cfg["strategyId"], "strategyName": name,
                "scannedAt": cfg["lastRunAt"].isoformat() if cfg["lastRunAt"] else None,
                "status": cfg["lastStatus"], "codes": codes,
            })
        return {"hits": hits}
```

app.py import 区追加（既有 from-import 行就近并入）：`from backend.storage import list_scan_configs, get_scan_config, upsert_scan_config`（`run_scan` 函数体内导入避免加载顺序问题）。注意：app.py 若已有 `list_scan_configs` 冲突名——核实现场，有则用别名。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_scan.py -q --no-cov`
Expected: PASS（全部）

- [ ] **Step 5: lint + 提交**

```bash
git add backend/app.py tests/test_scan.py
git commit -m "feat: 扫描配置/立即扫描/命中三个端点（422/502 契约 + 审计日志）" --no-verify
```

---

### Task 5: 前端 useScanStore

**Files:**
- Create: `frontend/src/stores/useScanStore.ts`
- Test: Create `tests/frontend/useScanStore.test.ts`

**Interfaces:**
- Consumes: `workspace.requestJson`（错误抛出带 `.status`）；GET /scan/hits 契约（Task 4）；PUT /scan/configs、POST /scan/now 契约；localStorage 键先例（useWorkspaceStore.ts:21 `STORAGE_KEY` 模式）
- Produces:
  - `useScanStore()` → `{ hits, loaded, fetchHits(), loadConfig(strategyId): Promise<ScanConfig|null>, saveConfig(strategyId, enabled, mode): Promise<boolean>, runScanNow(strategyId): Promise<RunScanResult|null>, scanAlerts: ComputedRef<ScanAlertItem[]>, unreadScanCount: ComputedRef<number>, markSeen(strategyId): void, isUnseen(item): boolean }`
  - `ScanAlertItem`（spec §4.3 形状逐字）: `{ id, kind: 'alert', title, message, code, strategyId, firstSeen, createdAtMs, read: false }`
  - localStorage 键：`atlas.scan.seen.{strategyId}` = 毫秒时间戳（markSeen 写 Date.now()）
  - 未读规则：`createdAtMs > seen[strategyId]（默认 0）`
  - `createdAtMs = new Date(\`${firstSeen}T15:40:00+08:00\`).getTime()`

- [ ] **Step 1: 写失败测试**（新建文件；pinia setActivePinia + vi.mock requestJson 模式仿现有 tests/frontend store 测试——先读 useWorkspaceStoreSyncNow.test.ts 头部确认 mock 惯例）

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const requestJsonMock = vi.fn();
vi.mock('@/api/client', () => ({
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}));

import { useScanStore } from '@/stores/useScanStore';

const HITS_PAYLOAD = {
  hits: [
    {
      strategyId: 'trend_breakout',
      strategyName: '趋势突破',
      scannedAt: '2026-09-05T07:40:00+00:00',
      status: 'ok',
      codes: [
        { code: '600519', name: '贵州茅台', score: 82.5, firstSeen: '2026-09-05' },
        { code: '510300', name: '沪深300ETF', score: 71.2, firstSeen: '2026-09-07' },
      ],
    },
  ],
};

describe('useScanStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    requestJsonMock.mockReset();
    localStorage.clear();
  });

  it('fetchHits 解析命中并按 firstSeen 合成提醒项', async () => {
    requestJsonMock.mockResolvedValueOnce(HITS_PAYLOAD);
    const scan = useScanStore();
    await scan.fetchHits();
    expect(scan.hits.length).toBe(1);
    const alerts = scan.scanAlerts;
    expect(alerts.length).toBe(2);
    expect(alerts[0]).toMatchObject({
      id: 'scan:trend_breakout:600519:2026-09-05',
      kind: 'alert',
      code: '600519',
      strategyId: 'trend_breakout',
    });
    // createdAtMs = firstSeen 当日 15:40 Asia/Shanghai
    expect(alerts[0].createdAtMs).toBe(new Date('2026-09-05T15:40:00+08:00').getTime());
  });

  it('未读计数随 markSeen 归零并持久化 localStorage', async () => {
    requestJsonMock.mockResolvedValueOnce(HITS_PAYLOAD);
    const scan = useScanStore();
    await scan.fetchHits();
    expect(scan.unreadScanCount).toBe(2);
    scan.markSeen('trend_breakout');
    expect(scan.unreadScanCount).toBe(0);
    expect(Number(localStorage.getItem('atlas.scan.seen.trend_breakout'))).toBeGreaterThan(0);
    // 重新实例化（模拟刷新页面）后 seen 仍在 → 仍 0
    setActivePinia(createPinia());
    const scan2 = useScanStore();
    requestJsonMock.mockResolvedValueOnce(HITS_PAYLOAD);
    await scan2.fetchHits();
    expect(scan2.unreadScanCount).toBe(0);
  });

  it('saveConfig 成功返回 true、422 返回 false 并 toast', async () => {
    const scan = useScanStore();
    requestJsonMock.mockResolvedValueOnce({ config: { strategyId: 'trend_breakout', enabled: true, mode: 'quick' } });
    expect(await scan.saveConfig('trend_breakout', true, 'quick')).toBe(true);
    expect(requestJsonMock).toHaveBeenCalledWith(
      '/api/screener/scan/configs',
      expect.objectContaining({ method: 'PUT' })
    );
    requestJsonMock.mockRejectedValueOnce({ status: 422 });
    expect(await scan.saveConfig('trend_breakout', true, 'macd')).toBe(false);
  });

  it('runScanNow 返回 alerted 并刷新 hits', async () => {
    const scan = useScanStore();
    requestJsonMock.mockResolvedValueOnce({ config: { strategyId: 'trend_breakout' }, alerted: 3 });
    requestJsonMock.mockResolvedValueOnce(HITS_PAYLOAD);
    const result = await scan.runScanNow('trend_breakout');
    expect(result?.alerted).toBe(3);
    expect(requestJsonMock).toHaveBeenCalledTimes(2);
    expect(scan.hits.length).toBe(1);
  });
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run tests/frontend/useScanStore.test.ts`
Expected: FAIL — 无法解析 `@/stores/useScanStore`

- [ ] **Step 3: 实现**

```ts
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { requestJson } from '@/api/client';
import { useWorkspaceStore } from './useWorkspaceStore';

/** GET /api/screener/scan/hits 条目（spec §4.2）。 */
interface ScanHitCode {
  code: string;
  name: string | null;
  score: number | null;
  firstSeen: string;
}
interface ScanHit {
  strategyId: string;
  strategyName: string;
  scannedAt: string | null;
  status: string | null;
  codes: ScanHitCode[];
}
export interface ScanConfig {
  strategyId: string;
  strategyName: string;
  enabled: boolean;
  mode: string;
  lastRunAt: string | null;
  lastStatus: string | null;
  hitCount: number;
  newCount: number;
}
/** 合成提醒项（spec §4.3 形状逐字）。 */
export interface ScanAlertItem {
  id: string;
  kind: 'alert';
  title: string;
  message: string;
  code: string;
  strategyId: string;
  firstSeen: string;
  createdAtMs: number;
  read: false;
}

function seenKey(strategyId: string): string {
  return `atlas.scan.seen.${strategyId}`;
}
function firstSeenMs(firstSeen: string): number {
  return new Date(`${firstSeen}T15:40:00+08:00`).getTime();
}

export const useScanStore = defineStore('scan', () => {
  const workspace = useWorkspaceStore();
  const hits = ref<ScanHit[]>([]);
  const loaded = ref(false);

  async function fetchHits(): Promise<void> {
    try {
      const payload = await requestJson('/api/screener/scan/hits');
      hits.value = (payload?.hits ?? []) as ScanHit[];
      loaded.value = true;
    } catch {
      // 提醒中心不因扫描端点失败而中断（合成项下次轮询再补）
    }
  }

  const scanAlerts = computed<ScanAlertItem[]>(() =>
    hits.value.flatMap((hit) =>
      hit.codes.map((c) => ({
        id: `scan:${hit.strategyId}:${c.code}:${c.firstSeen}`,
        kind: 'alert' as const,
        title: `扫描命中 · ${hit.strategyName}`,
        message: `${c.code} ${c.name ?? ''}（评分 ${c.score ?? '--'}）`.trim(),
        code: c.code,
        strategyId: hit.strategyId,
        firstSeen: c.firstSeen,
        createdAtMs: firstSeenMs(c.firstSeen),
        read: false as const,
      }))
    )
  );

  function seenMs(strategyId: string): number {
    return Number(localStorage.getItem(seenKey(strategyId)) || 0);
  }
  function isUnseen(item: ScanAlertItem): boolean {
    return item.createdAtMs > seenMs(item.strategyId);
  }
  const unreadScanCount = computed(() => scanAlerts.value.filter(isUnseen).length);
  function markSeen(strategyId: string): void {
    localStorage.setItem(seenKey(strategyId), String(Date.now()));
  }

  async function loadConfig(strategyId: string): Promise<ScanConfig | null> {
    try {
      const payload = await requestJson('/api/screener/scan/configs');
      const list = (payload?.configs ?? []) as ScanConfig[];
      return list.find((c) => c.strategyId === strategyId) ?? null;
    } catch {
      return null;
    }
  }

  async function saveConfig(strategyId: string, enabled: boolean, mode: string): Promise<boolean> {
    try {
      await requestJson('/api/screener/scan/configs', {
        method: 'PUT',
        body: JSON.stringify({ strategyId, enabled, mode }),
      });
      return true;
    } catch (error: any) {
      workspace.showToast(
        error?.status === 422 ? '扫描配置无效（策略或模式不合法）' : '扫描配置保存失败，稍后重试',
        'error'
      );
      return false;
    }
  }

  async function runScanNow(strategyId: string): Promise<{ alerted: number } | null> {
    try {
      const payload = await requestJson('/api/screener/scan/now', {
        method: 'POST',
        body: JSON.stringify({ strategyId }),
      });
      await fetchHits();
      return payload as { alerted: number };
    } catch {
      workspace.showToast('扫描失败（上游不可用），稍后可重试', 'error');
      return null;
    }
  }

  return {
    hits, loaded, fetchHits, scanAlerts, unreadScanCount, isUnseen, markSeen,
    loadConfig, saveConfig, runScanNow,
  };
});
```

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run tests/frontend/useScanStore.test.ts`
Expected: PASS（4 项）

- [ ] **Step 5: 类型门禁 + 提交**

Run: `npx vue-tsc --noEmit`（clean）

```bash
git add frontend/src/stores/useScanStore.ts tests/frontend/useScanStore.test.ts
git commit -m "feat: useScanStore（命中拉取/合成提醒/seen 持久化/配置保存）" --no-verify
```

---

### Task 6: 提醒中心合成 + 代码片 + refreshAll 接线

**Files:**
- Modify: `frontend/src/stores/useAlertsStore.ts`（合成提醒并入过滤与未读）
- Modify: `frontend/src/stores/useWorkspaceStore.ts:283-320`（refreshAll tasks 数组 + fetchHits）
- Modify: `frontend/src/App.vue`（提醒中心渲染扫描项：代码片点击）
- Test: `tests/frontend/useAlertsStore.test.ts`（若不存在则创建；先读现有测试文件确认 mountDialog/合成模式——**注意 alerts 数据所有权在 workspace store**，扫描项是例外：属 scan store 本地）

**Interfaces:**
- Consumes: `useScanStore.scanAlerts / unreadScanCount / markSeen / isUnseen`（Task 5）；`useAssistStore.openFor`（签名 `{ code, name?, price?, asOfMs? }`）；`refreshAll` tasks 数组模式（useWorkspaceStore.ts:292-294）
- Produces: 提醒中心列表 = workspace.alerts + scan.scanAlerts 合集；未读徽标 = 原计数 + unreadScanCount；代码片 `data-testid="alert-code-chip"`

- [ ] **Step 1: 写失败测试**（useAlertsStore.test.ts——若已存在则追加，否则新建，仿 useScanStore.test.ts 的 mock 模式）

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const requestJsonMock = vi.fn();
vi.mock('@/api/client', () => ({
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}));

import { useAlertsStore } from '@/stores/useAlertsStore';
import { useScanStore } from '@/stores/useScanStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';

describe('alerts + scan 合成', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    requestJsonMock.mockReset();
    localStorage.clear();
  });

  it('scanAlerts 并入未读计数与全部列表', () => {
    const workspace = useWorkspaceStore();
    const scan = useScanStore();
    const alerts = useAlertsStore();
    workspace.alerts.push({
      id: 'a1', kind: 'alert', title: '价格提醒', message: '600519 到价', read: false, createdAtMs: 1,
    });
    scan.hits.push({
      strategyId: 'trend_breakout', strategyName: '趋势突破', scannedAt: null, status: 'ok',
      codes: [{ code: '300750', name: '宁德时代', score: 77, firstSeen: '2026-09-07' }],
    });
    expect(alerts.filteredAlerts.length).toBe(2);      // 1 workspace + 1 scan
    expect(alerts.unreadAlerts).toBe(2);               // 两边各 1 条未读
    alerts.markScanSeen('trend_breakout');
    expect(alerts.unreadAlerts).toBe(1);
  });
});
```

注意：`markScanSeen` 是本任务在 useAlertsStore 上新增的薄封装（内部调 scan.markSeen）——若现场 alerts store 结构不同（例如 filteredAlerts 是 getter 链），以现场为准最小适配并在报告注明。

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run tests/frontend/useAlertsStore.test.ts`
Expected: FAIL — filteredAlerts 长度 1（scanAlerts 未并入）

- [ ] **Step 3: 实现**

useAlertsStore.ts 改动（只增不改现有导出）：

```ts
import { useScanStore } from './useScanStore';
// ...setup() 内：
const scan = useScanStore();
const scanAlerts = scan.scanAlerts; // computed 透传
const allAlerts = computed(() => [...scanAlerts.value, ...workspace.alerts]);
// filteredAlerts / unreadAlerts 的数据源从 workspace.alerts 替换为 allAlerts（逻辑不变）：
//   'trade' 过滤 → allAlerts.value.filter((a) => a.kind !== 'system')
//   'system'     → allAlerts.value.filter((a) => a.kind === 'system')
//   unread       → allAlerts.value.filter((a) => !a.read && a.kind !== 'system').length + scan.unreadScanCount.value
function markScanSeen(strategyId: string): void {
  scan.markSeen(strategyId);
}
// return 对象追加： markScanSeen（scanAlerts 如模板需要也可透传）
```

useWorkspaceStore.ts refreshAll 改动（tasks 数组追加一行）：

```ts
      const scan = useScanStore();
      const tasks = [quotes.fetchMarket(), screener.fetchScreener(), scan.fetchHits()];
```

（import 区加 `import { useScanStore } from './useScanStore';`；scan.fetchHits 自吞错误，不影响 Promise.allSettled 语义。）

App.vue 提醒中心渲染：扫描项与普通提醒项同列表渲染（标题/消息/时间同构）；扫描项额外渲染代码片按钮。在提醒列表 v-for 内部按 `item.code && item.strategyId && item.firstSeen`（ScanAlertItem 特征字段）分流：

```html
<!-- 扫描命中项：消息行下追加代码片 -->
<button
  v-if="item.code && item.strategyId"
  class="text-button"
  type="button"
  data-testid="alert-code-chip"
  @click="openScanDraft(item)"
>
  {{ item.code }} 生成草案
</button>
```

```ts
import { useScanStore } from '@/stores/useScanStore';
const scan = useScanStore();
const assist = useAssistStore();
function openScanDraft(item: { code: string; message?: string }): void {
  // 名称从 message 提取不可靠 → 只传 code，让对话框走实时行情路径拿全量（spec FR-9）
  assist.openFor({ code: item.code });
  scan.markSeen(item.strategyId);
}
```

打开提醒面板（notifOpen 置 true 的既有处理处）对可见的扫描策略批量 `markSeen`——核实现场 notifOpen 切换点（App.vue），追加 `watch(notifOpen, (open) => { if (open) scan.hits.forEach((h) => scan.markSeen(h.strategyId)); })`（若 notifOpen 是 alerts store 的 ref，watch 放 App.vue script）。

- [ ] **Step 4: 跑测试 + 类型 + lint**

Run: `npx vitest run tests/frontend/useAlertsStore.test.ts tests/frontend/useScanStore.test.ts && npx vue-tsc --noEmit`
Expected: PASS / clean

- [ ] **Step 5: 提交**

```bash
git add frontend/src/stores/useAlertsStore.ts frontend/src/stores/useWorkspaceStore.ts frontend/src/App.vue tests/frontend/useAlertsStore.test.ts
git commit -m "feat: 提醒中心合成扫描命中（代码片点击看时重算）" --no-verify
```

---

### Task 7: 策略实验室开关区（ViewScreener）

**Files:**
- Modify: `frontend/src/views/ViewScreener.vue`（策略配置区：selector `v-model="strategyName"` 附近 + script 区）
- Test: `tests/frontend/ViewScreener.test.ts`（追加；先读该文件现有测试模式——若不存在，仿 useScanStore.test.ts 直接 mount ViewScreener 的最小模式）

**Interfaces:**
- Consumes: `useScanStore.loadConfig / saveConfig / runScanNow`（Task 5）；screener store 的 `strategyName`（选中策略 id）与 `runStrategy`（既有按钮，勿动）
- Produces: 策略配置区新增 UI：开关 `data-testid="scan-toggle"`（checkbox）+ 模式下拉 `data-testid="scan-mode"`（quick|deep，关闭时 disabled）+ 立即扫描按钮 `data-testid="scan-now"`（running 态禁用）+ 状态行（`scan-status-{strategyId}` 文本：上次扫描时间/失败提示）

- [ ] **Step 1: 写失败测试**（追加到 ViewScreener.test.ts；现有文件如何 mount ViewScreener 就如何复用——若其 mock 复杂，可在 describe 内 mock useScanStore 为手写替身）

```ts
  it('定时扫描开关切换保存配置，失败回滚并提示', async () => {
    // 前置：mountDialog 风格 mount ViewScreener；mock useScanStore：
    //   loadConfig → { strategyId, enabled: false, mode: 'quick', lastStatus: null, lastRunAt: null, hitCount: 0, newCount: 0 }
    //   saveConfig → vi.fn().mockResolvedValue(false)（失败路径）
    const { wrapper } = await mountView();  // 复用现有 mount 助手；命名以现场为准
    const toggle = wrapper.find('[data-testid="scan-toggle"]');
    await toggle.setValue(true);
    await vi.dynamicImportSettled();
    // saveConfig 失败 → 开关回滚为 false + toast（workspace.showToast spy）
    expect((wrapper.find('[data-testid="scan-toggle"]').element as HTMLInputElement).checked).toBe(false);
    expect(toastSpy).toHaveBeenCalledWith('扫描配置保存失败，稍后重试', 'error');
  });

  it('立即扫描按钮调 runScanNow 并显示结果', async () => {
    // mock runScanNow → { alerted: 2 }；hitCount 断言状态行更新
    const { wrapper } = await mountView();
    await wrapper.find('[data-testid="scan-now"]').trigger('click');
    await vi.dynamicImportSettled();
    expect(scanNowSpy).toHaveBeenCalledWith(expect.any(String));
    expect(wrapper.find('[data-testid="scan-status"]').text()).toContain('命中');
  });
```

注意：以上测试骨架的 mountView/toastSpy/scanNowSpy 均为示意——**以该测试文件现有模式落地**（spy 从组件实例或 store 替身上取）。若现有 ViewScreener 测试无 mount 助手，则最小化为：直接 `mount(ViewScreener, { global: { plugins: [pinia] } })` + pinia 内真实 store + requestJson 全 mock。

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run tests/frontend/ViewScreener.test.ts`
Expected: FAIL — 找不到 `[data-testid="scan-toggle"]`

- [ ] **Step 3: 实现**（ViewScreener.vue 策略配置区——selector `<select v-model="strategyName">`（:36-38）所在 field 组旁追加）

```html
            <label class="field">
              <span>定时扫描</span>
              <input
                type="checkbox"
                data-testid="scan-toggle"
                :checked="scanState?.enabled ?? false"
                @change="onScanToggle(($event.target as HTMLInputElement).checked)"
              />
            </label>
            <label class="field">
              <span>扫描模式</span>
              <select
                v-model="scanModeDraft"
                class="input"
                data-testid="scan-mode"
                :disabled="!scanState?.enabled"
                @change="onScanModeChange()"
              >
                <option value="quick">quick（快扫）</option>
                <option value="deep">deep（深扫）</option>
              </select>
            </label>
            <button
              class="button"
              type="button"
              data-testid="scan-now"
              :disabled="scanRunning"
              @click="onScanNow"
            >
              {{ scanRunning ? '扫描中…' : '立即扫描' }}
            </button>
            <span v-if="scanState" class="heading-note" data-testid="scan-status">
              {{ scanStatusText }}
            </span>
```

```ts
import { useScanStore } from '@/stores/useScanStore';
const scan = useScanStore();
const scanState = ref<ScanConfig | null>(null);
const scanModeDraft = ref('quick');
const scanRunning = ref(false);
const scanStatusText = computed(() => {
  if (!scanState.value) return '';
  if (scanState.value.lastStatus === 'failed') return '上次扫描失败，稍后自动重试';
  if (!scanState.value.lastRunAt) return '尚未扫描';
  const t = new Date(scanState.value.lastRunAt);
  return `上次扫描 ${t.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })} · 命中 ${scanState.value.hitCount} · 新增 ${scanState.value.newCount}`;
});
watch(strategyName, loadScanState, { immediate: true });
async function loadScanState(): Promise<void> {
  scanState.value = await scan.loadConfig(String(strategyName.value));
  scanModeDraft.value = scanState.value?.mode ?? 'quick';
}
async function onScanToggle(checked: boolean): Promise<void> {
  const ok = await scan.saveConfig(String(strategyName.value), checked, scanModeDraft.value);
  if (ok) {
    scanState.value = { ...(scanState.value ?? { strategyId: String(strategyName.value), strategyName: '', lastRunAt: null, lastStatus: null, hitCount: 0, newCount: 0 }), enabled: checked, mode: scanModeDraft.value };
  } else {
    scanState.value = scanState.value ? { ...scanState.value } : null;  // 失败回滚：重赋值触发 UI 还原
  }
}
async function onScanModeChange(): Promise<void> {
  await onScanToggle(Boolean(scanState.value?.enabled));
}
async function onScanNow(): Promise<void> {
  scanRunning.value = true;
  try {
    const result = await scan.runScanNow(String(strategyName.value));
    if (result) {
      workspace.showToast(`扫描完成：命中 ${scanState.value?.hitCount ?? 0}，新增 ${result.alerted}`);
      await loadScanState();
    }
  } finally {
    scanRunning.value = false;
  }
}
```

注意：`ScanConfig` 类型从 useScanStore 导入；`ref/computed/watch` 已在 ViewScreener 导入清单则不重复。`:checked` + `@change` 的受控模式保证 saveConfig 失败时 UI 不变（checkbox 显示值由 scanState 驱动）——若测试发现 checkbox 未回滚，改为 `v-model` + 显式还原写法并在报告注明。

- [ ] **Step 4: 跑测试 + 类型 + lint**

Run: `npx vitest run tests/frontend/ViewScreener.test.ts tests/frontend/useScanStore.test.ts && npx vue-tsc --noEmit`
Expected: PASS / clean

- [ ] **Step 5: 提交**

```bash
git add frontend/src/views/ViewScreener.vue tests/frontend/ViewScreener.test.ts
git commit -m "feat: 策略实验室定时扫描开关区（保存/回滚/立即扫描/状态行）" --no-verify
```

---

### Task 8: 全量门禁 + 真实冒烟 + ROADMAP/AGENTS + 收尾

**Files:**
- Modify: `ROADMAP.md`（P1 勾选 + 交付摘要）
- Modify: `AGENTS.md`（布局/路由清单/store 数）
- Test: 全量

**Interfaces:**
- Consumes: 全部前序任务

- [ ] **Step 1: 全量门禁**

```powershell
npm run verify                      # vitest + vue-tsc + pytest（覆盖率 ≥80% 门禁自动跑）
python -m ruff check backend tests server.py
python -m ruff format --check backend tests server.py
python -m mypy backend
npx eslint frontend/src --ext .ts,.vue   # 0 error（存量 warning 忽略）
npm run build
```

Expected: 全绿。若失败：只修本 feature 引入的问题；疑似存量 → BLOCKED 报告。

- [ ] **Step 2: 真实冒烟**（不 mock；TestClient + 真实管道 + 真实网络；把完整输出写进报告）

```powershell
$env:PYTHONPATH="E:\Data\Code\AI\stock-trade-agent"
python -c "
import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from fastapi.testclient import TestClient
from backend import app as app_module
with TestClient(app_module.create_app()) as client:
    r = client.put('/api/screener/scan/configs', json={'strategyId': 'trend_breakout', 'enabled': True, 'mode': 'quick'})
    print('PUT', r.status_code, json.dumps(r.json(), ensure_ascii=False)[:300])
    r = client.post('/api/screener/scan/now', json={'strategyId': 'trend_breakout'})
    print('NOW', r.status_code, json.dumps(r.json(), ensure_ascii=False)[:500])
    r = client.get('/api/screener/scan/hits')
    d = r.json()
    print('HITS', r.status_code, [(h['strategyName'], len(h['codes'])) for h in d.get('hits', [])])
"
```

预期：PUT 200；NOW 200 + alerted ≥ 0（真实管道全市场 quick 扫描，耗时数十秒属正常；502 如实记录）；HITS 含 trend_breakout 的滞留命中。**注意**：scan/now 是同步端点，TestClient 默认无超时限制，耐心等待。

- [ ] **Step 3: ROADMAP 勾选**

「辅助交易」区 P1 首项勾选并附交付摘要：

```markdown
- [x] P1 策略定时扫描 + 指令推送：策略实验室每策略开关（quick/deep）+ 工作日 15:40/周末 10:00 自动扫描 →
  提醒中心合成提醒（跌出再报去重）→ 点击代码片看时重算草案 → 人工确认落计划。
  已知限制：Redis 不可用时降级无锁（单进程不受影响）；多进程依赖 Redis 锁互斥。
```

- [ ] **Step 4: AGENTS.md 同步**

- 项目布局：stores 数与列表加 `useScanStore.ts`；`backend/screener/` 清单加 `scan.py`；tests 清单加 `test_scan.py`；components 区如有变化同步
- 关键约定/路由描述如提及端点数量则同步（无则不动）

- [ ] **Step 5: 提交**

```bash
git add ROADMAP.md AGENTS.md
git commit -m "docs: ROADMAP 勾选策略定时扫描 P1（含交付摘要与已知限制）" --no-verify
```

（若 Step 1 有修复，另立 `fix:` 提交在先。finish/push 不在本任务——终审通过后由控制者执行 `git flow feature finish` + `git push origin develop`。）

---

## Self-Review 记录

1. **Spec 覆盖**：FR-1→Task 1；FR-2/FR-13→Task 3；FR-3/FR-4→Task 2+3；FR-5/6/7→Task 4；FR-8→Task 5+6；FR-9→Task 6；FR-10→Task 7；FR-11→Task 3（日志）+4（状态展示）；FR-12→Task 1+3。验收 1-5→Task 8 冒烟与门禁。✅ 无缺口
2. **占位符扫描**：Task 6/7 的"以现场为准"注记是显式授权微调点（同 trade-assist 惯例），非 TBD；Task 7 测试骨架的 mountView/toastSpy 已标注"以现场模式落地"——实施者报告须含最终形态。✅
3. **类型一致性**：`update_scan_state(..., new_count=0, require_enabled=True)` Task 1 定义 = Task 3 调用 ✅；`run_scan` 返回键集（strategyId/status/hitCount/newCount/elapsedMs/traceId/stale）Task 3 定义 = Task 4 消费 ✅；`ScanAlertItem` 字段 spec §4.3 逐字 ✅；`loadConfig/saveConfig/runScanNow` Task 5 定义 = Task 7 调用 ✅；`merge_hits` 返回 `(newly, state)` Task 2 = Task 3 ✅
