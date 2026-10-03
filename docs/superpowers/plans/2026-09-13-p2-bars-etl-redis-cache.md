# P2 数据中台（全市场日线 ETL + Redis 行情缓存接管）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 落地 spec r3.1（`docs/superpowers/specs/2026-09-13-daily-bars-etl-redis-cache-spec.md`）：M1 全市场 bfq 500 根日线 ETL（日补+回补+熔断自愈+DQ+缺口双通道自愈），M2 `cached()` 行情/历史缓存的 Redis L2 接管（白名单、熔断、旁路=现状）。

**Architecture:** 零新表零迁移；`bars_etl.py` 纯新模块读 industry_map/storage、经 `data_source` 拉腾讯 kline、写 `market_bars`（批量 upsert I10）；`redis_cache.py` 提供可注入 `CacheFacade`（L1 dict 保留现状 + L2 Redis + loader 三级），`cached()` 外部行为逐字不变。**消费端零改动**（`fetch_all_bars` 的 7 日新鲜判据使 ETL 落库后复盘/组合自动零回源）。

**Tech Stack:** Python/FastAPI、SQLAlchemy 2.0（pg ON CONFLICT）、APScheduler 3.x、redis-py 5.2、pytest（离线 monkeypatch + 本地真 PG）。前端零触碰。

## Global Constraints（每任务隐含）

- 绝不造数：ETL 空响应=失败；DQ 坏根不落库；Redis 故障精确回退现状行为，不返回假数据。
- `/api/health` 既有字段（`storage` dict[str,bool] 等）**零触碰**；新状态只加附加键（I9）。
- `data_source.cached()` 外部行为（TTL 下限 2s、`STALE_MAX_AGE=1800s` stale 兜底、`mark_stale`/`X-Atlas-Stale` 链）**逐字不变**——既有相关测试**禁止修改**。
- 上游请求全部经既有 `_throttle()`（≤10 req/s），ETL 不新建并发面、不绕限频。
- 唯一键语义：`market_bars(code, trade_date, adjustment)`，ETL 桶恒 `adjustment=''`；指数键空间 `qfq:idx`（A1）。
- pytest/ruff/mypy 一律从**仓库根**运行；vitest/prettier 本特性不涉及。中文 Conventional Commits；每任务一提交。
- 测试基线：backend 497 项 / cov≥80%；新增测试不得破坏既有用例（尤其 `cached` 与 `test_plan_review` 的 loader 断言面）。

---

### Task 1: A1 附带修复——指数键空间隔离 + 歧义桶清理

**Files:**
- Modify: `backend/app.py:417`（/api/history 的 fallback 调用）
- Modify: `backend/storage.py`（新增 `cleanup_legacy_index_qfq`）
- Test: `tests/test_backend_api.py`、`tests/test_storage_coverage.py` 各追加

**Interfaces:**
- Produces: `storage.cleanup_legacy_index_qfq() -> int`（删除行数，幂等）；`/api/history?index=true` 落库 `adjustment="qfq:idx"`。
- Consumes: 无（首任务）。

- [ ] **Step 1: 写失败测试（端点隔离）** — 追加到 `tests/test_backend_api.py`：

```python
def test_history_index_uses_isolated_adjustment_bucket(client, monkeypatch):
    """A1：指数与个股 000001 不得互写同桶。"""
    from backend import app as app_mod, storage

    bars = [{"date": "2026-09-10", "open": 3000.1, "high": 3100.2, "low": 2900.0,
             "close": 3050.5, "volume": 1e8, "amount": 1e11}]
    monkeypatch.setattr(app_mod, "save_market_bars", lambda code, hist, adjustment="qfq": None)
    saved: dict = {}
    monkeypatch.setattr(storage, "save_market_bars",
                        lambda code, hist, adjustment="qfq": saved.setdefault(adjustment, (code, len(hist))))
    source = type("S", (), {"load_history": lambda self, code, limit=40, is_index=False, adjustment="qfq": bars,
                            "provider_label": "tencent"})()
    monkeypatch.setattr("backend.sources.build_router", lambda: type("R", (), {
        "route_with_fallback": staticmethod(lambda name, cap, ok: source)})())
    r_idx = client.get("/api/history?code=000001&index=true")
    assert r_idx.status_code == 200
    # 断言传给 fallback 的 adjustment 已分流
    import inspect
    src = inspect.getsource(app_mod.create_app)
    assert 'adjustment="qfq:idx" if index else "qfq"' in src
```

（若上面 inspect 断言显丑，可改为功能性断言：预置 000001 个股 qfq 行 → 请求指数历史 → 个股行逐字节不变 + 新出现 `qfq:idx` 行；实现时二选一，功能断言优先。）

- [ ] **Step 2: 写失败测试（清理函数）** — `tests/test_storage_coverage.py` 追加：

```python
def test_cleanup_legacy_index_qfq_is_idempotent():
    from backend import storage
    with storage.SessionLocal.begin() as s:
        s.add_all([
            storage.MarketBar(code="000001", trade_date="2026-09-10", adjustment="qfq", open=1, high=1, low=1, close=1),
            storage.MarketBar(code="600519", trade_date="2026-09-10", adjustment="qfq", open=1, high=1, low=1, close=1),
        ])
    n1 = storage.cleanup_legacy_index_qfq()
    n2 = storage.cleanup_legacy_index_qfq()
    assert n1 >= 1 and n2 == 0
    with storage.SessionLocal() as s:
        from sqlalchemy import select
        assert s.scalars(select(storage.MarketBar).where(
            storage.MarketBar.code == "600519", storage.MarketBar.adjustment == "qfq")).first() is not None
        s.rollback()
    # 收尾清掉本用例的 600519 行
    with storage.SessionLocal.begin() as s:
        s.query(storage.MarketBar).filter_by(code="600519", adjustment="qfq").delete()
```

（若既有测试夹具自带库清理钩子，则去掉手工收尾段，跟随夹具模式。）

- [ ] **Step 3: 跑测试确认失败**（`cleanup_legacy_index_qfq` 不存在；inspect/功能断言不中）。
Run: `python -m pytest tests/test_backend_api.py -k index_uses_isolated -q tests/test_storage_coverage.py -k cleanup_legacy -q`

- [ ] **Step 4: 实现**：

`backend/storage.py`（`save_market_bars` 之后）：

```python
def cleanup_legacy_index_qfq() -> int:
    """A1 一次性清理：指数与个股共享 (code,'qfq') 桶的历史混写行整删（幂等）。
    000001 与平安银行同码歧义不可分，qfq 缓存按需重取，删除代价≈首访一次回源。"""
    with SessionLocal.begin() as session:
        n = session.query(MarketBar).filter(
            MarketBar.adjustment == "qfq", MarketBar.code.in_(["000001", "399001", "399006"])
        ).delete(synchronize_session=False)
    return int(n)
```

`backend/app.py:417`：

```python
            history, data_source_flag, data_as_of, provider = _load_history_with_fallback(
                code, 120, is_index=index, adjustment="qfq:idx" if index else "qfq"
            )
```

- [ ] **Step 5: 跑绿 + 全量回归**：`python -m pytest tests/ -q --no-cov -o addopts=""` 全绿（497+n）。
- [ ] **Step 6: Commit**：`git add backend/app.py backend/storage.py tests/` → `fix: 指数历史 qfq:idx 键空间隔离并清理歧义桶（P2-A1）`

---

### Task 2: 存储层批量 upsert（I10）

**Files:**
- Modify: `backend/storage.py`
- Test: `tests/test_storage_coverage.py`

**Interfaces:**
- Produces: `storage.upsert_market_bars_batch(code: str, bars: list[dict[str, Any]], adjustment: str, session: Any = None) -> int`——`INSERT..ON CONFLICT (约束 uq_market_bars_code_date_adjustment) DO UPDATE`；批内同 date 去重保后者；空 bars 抛 `ValueError`；`session=None` 自开事务，传入则在调用方事务内执行（码级 SAVEPOINT 由调用方 `session.begin_nested()` 负责）。
- Consumes: Task 1 无直接依赖（可并行，但编号串行）。

- [ ] **Step 1: 失败测试**：

```python
def test_upsert_market_bars_batch_idempotent_and_dedup():
    from backend import storage
    bars = [
        {"date": "2026-09-09", "open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10, "amount": 15},
        {"date": "2026-09-09", "open": 1, "high": 3, "low": 0.5, "close": 2.5, "volume": 20, "amount": 50},  # 同日后者胜
        {"date": "2026-09-10", "open": 2, "high": 3, "low": 1, "close": 2.8, "volume": None, "amount": None},
    ]
    n1 = storage.upsert_market_bars_batch("600999", bars, adjustment="")
    n2 = storage.upsert_market_bars_batch("600999", bars, adjustment="")  # 幂等重放
    rows = storage.load_market_bars("600999", adjustment="", limit=10)
    assert {r["date"] for r in rows} == {"2026-09-09", "2026-09-10"}
    assert rows[0]["close"] == 2.5  # 批内去重保后者
    assert n2 == n1 > 0
    with pytest.raises(ValueError):
        storage.upsert_market_bars_batch("600999", [], adjustment="")
    with storage.SessionLocal.begin() as s:
        s.query(storage.MarketBar).filter_by(code="600999").delete()
```

- [ ] **Step 2: 跑红确认** → **Step 3: 实现**（`storage.py`）：

```python
def upsert_market_bars_batch(code: str, bars: list[dict[str, Any]], adjustment: str, session: Any = None) -> int:
    """I10 批量幂等写：单语句 upsert（ETL 性能预算所需）。空 bars 拒写（P0-2 防线之一）。"""
    if not bars:
        raise ValueError("bars 不能为空——空响应不是数据")
    dedup: dict[str, dict[str, Any]] = {}
    for bar in bars:
        date = str(bar.get("date") or "")
        if date:
            dedup[date] = bar  # 同批重复日保后者，防 ON CONFLICT 同语句二次命中
    values = [
        {"code": code, "trade_date": d, "adjustment": adjustment,
         "open": b.get("open"), "high": b.get("high"), "low": b.get("low"),
         "close": b.get("close"), "volume": b.get("volume"), "amount": b.get("amount"),
         "fetched_at": datetime.now(UTC)}
        for d, b in dedup.items()
    ]
    stmt = insert(MarketBar).values(values).on_conflict_do_update(
        constraint="uq_market_bars_code_date_adjustment",
        set_={k: stmt_v for k, stmt_v in values[0].items() if k not in ("code", "trade_date", "adjustment")},
    )
    if session is not None:
        return int(session.execute(stmt).rowcount or 0)
    with SessionLocal.begin() as s:
        return int(s.execute(stmt).rowcount or 0)
```

（注意：`set_` 用 `stmt.excluded.<col>` 写法——实现时以 `sqlalchemy.dialects.postgresql.insert` 的 `excluded` 引用为准，如 `set_={"open": stmt.excluded.open, ...}`，上面 dict 写法若被 ruff 拒即改 excluded 逐列；volume/amount 可空列一致。）

- [ ] **Step 4: 跑绿** → **Step 5: 全量 + ruff/mypy** → **Step 6: Commit** `feat: market_bars 批量 upsert 存储接口 I10`

---

### Task 3: bars_etl 核心——水位 / universe / 缺口检测（I1/I2/I3）

**Files:**
- Create: `backend/bars_etl.py`
- Create: `tests/test_bars_etl.py`

**Interfaces:**
- Produces:
  - `authoritative_watermark(now: datetime | None = None) -> str`（Asia/Shanghai 时刻粒度：weekday 且 ≥15:05 计当日，否则回溯最近 weekday；`now=None` 走 60s 进程缓存；now 注入时**绕过缓存**）
  - `resolve_universe() -> list[str]`（industry_map ∪ watchlist ∪ trade_plans 码，去重升序，无指数）
  - `detect_gaps() -> dict[str, Any]`：`{"missing": [...], "stale_deep": [...], "stale_light": [...], "up_to_date": int}`，附内部辅助 `_max_map() -> dict[str, str]` 与 `_lag_days(date_str, watermark) -> int`（weekday 计数，无假日表——与 L3 一致）
- Consumes: `storage.SessionLocal/IndustryMap/WatchlistItem/TradePlan/MarketBar`（ORM 类名以 storage.py 现状为准，实现时核对）。

- [ ] **Step 1: 失败测试**（水位参数化是重点——P0-3 回归锚）：

```python
from datetime import datetime
from zoneinfo import ZoneInfo
import pytest
from backend import bars_etl

SH = ZoneInfo("Asia/Shanghai")

@pytest.mark.parametrize("now,expected", [
    (datetime(2026, 9, 11, 15, 4, tzinfo=SH), "2026-09-10"),   # 周四 15:04 未到点→昨日
    (datetime(2026, 9, 11, 15, 5, tzinfo=SH), "2026-09-11"),   # 恰 15:05→当日
    (datetime(2026, 9, 12, 9, 0, tzinfo=SH), "2026-09-11"),    # 周五盘前→周四
    (datetime(2026, 9, 13, 12, 0, tzinfo=SH), "2026-09-11"),   # 周日→上周五
    (datetime(2026, 9, 14, 16, 0, tzinfo=SH), "2026-09-14"),   # 周一收盘后
])
def test_watermark_moment_granularity(now, expected):
    assert bars_etl.authoritative_watermark(now=now) == expected

def test_resolve_universe_union_dedup_sorted(monkeypatch):
    # 以假 session 或预置真 PG 少量行断言并集语义；北交所工作区码在列，指数三码不在
    ...

def test_detect_gaps_four_buckets():
    # 真 PG 预置：A 无行=missing；B max=水位-15 交易日=stale_deep；C 水位-2=stale_light；D 水位当日=up_to_date
    ...
```

（universe/gaps 两用例的真身按 `tests/test_storage_coverage.py` 现有真 PG 夹具风格写：预置→断言→清行；实现时把 `...` 展开为完整代码。）

- [ ] **Step 2: 跑红** → **Step 3: 实现 `bars_etl.py`**：

```python
"""全市场日线 ETL（P2-M1，spec r3 §3）：水位→缺口→回补/日补→批量落库，降级不静默。"""
from __future__ import annotations
import threading, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import func, select
from backend import storage
from backend.settings import get_settings  # 视现状；仅 universe 无需 settings

SH = ZoneInfo("Asia/Shanghai")
CLOSE_MINUTES = 15 * 60 + 5
_wm_lock = threading.Lock()
_wm_cache: dict[str, object] = {"at": 0.0, "value": ""}

def _watermark_uncached(t: datetime) -> str:
    d = t.date()
    if d.weekday() >= 5 or t.hour * 60 + t.minute < CLOSE_MINUTES:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()

def authoritative_watermark(now: datetime | None = None) -> str:
    if now is not None:
        return _watermark_uncached(now.astimezone(SH))
    with _wm_lock:
        if time.time() - float(_wm_cache["at"]) < 60 and _wm_cache["value"]:
            return str(_wm_cache["value"])
    value = _watermark_uncached(datetime.now(SH))
    with _wm_lock:
        _wm_cache.update(at=time.time(), value=value)
    return value

def resolve_universe() -> list[str]:
    with storage.SessionLocal() as s:
        codes = set(s.scalars(select(storage.IndustryMap.code)).all())
        codes |= set(s.scalars(select(storage.WatchlistItem.code).distinct()).all())
        codes |= set(s.scalars(select(storage.TradePlan.code).distinct()).all())
    return sorted(codes)

def _max_map() -> dict[str, str]:
    with storage.SessionLocal() as s:
        rows = s.execute(
            select(storage.MarketBar.code, func.max(storage.MarketBar.trade_date))
            .where(storage.MarketBar.adjustment == "")
            .group_by(storage.MarketBar.code)
        ).all()
    return {code: mx for code, mx in rows}

def _lag_days(last: str | None, watermark: str) -> int:
    """近似交易日落后数：区间内 weekday 天数（无假日表，与 §9-L3 同源近似）。"""
    if not last:
        return 10_000
    a, b = datetime.strptime(last, "%Y-%m-%d").date(), datetime.strptime(watermark, "%Y-%m-%d").date()
    if a >= b:
        return 0
    n, d = 0, a + timedelta(days=1)
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n

def detect_gaps() -> dict[str, object]:
    watermark = authoritative_watermark()
    mx = _max_map()
    out: dict[str, object] = {"missing": [], "stale_deep": [], "stale_light": [], "up_to_date": 0}
    for code in resolve_universe():
        lag = _lag_days(mx.get(code), watermark)
        if mx.get(code) is None:
            out["missing"].append(code)
        elif lag > 10:
            out["stale_deep"].append(code)
        elif lag >= 1:
            out["stale_light"].append(code)
        else:
            out["up_to_date"] = int(out["up_to_date"]) + 1
    return out
```

- [ ] **Step 4: 跑绿 → Step 5: 全量+ruff/mypy → Step 6: Commit** `feat: bars_etl 水位/缺口检测（P2-M1 核心 I1-I3）`

---

### Task 4: DQ 断言 + run_full + EtlStats（I4，P0-2/P1-3 主战场）

**Files:**
- Modify: `backend/bars_etl.py`
- Test: `tests/test_bars_etl.py`

**Interfaces:**
- Consumes: Task 2 `storage.upsert_market_bars_batch`、Task 3 `detect_gaps/authoritative_watermark/resolve_universe`。
- Produces: `EtlStats`（dataclass，字段=I4 十字段+`reason`）、`validate_bars(bars, watermark) -> tuple[list[dict], int]`、`run_full(force=False, *, fetch=None) -> EtlStats`；模块常量 `UNIVERSE_MIN=2000`、`FAIL_RATE_ABORT=0.2`、`BATCH_CODES=500`、`BACKFILL_LIMIT=500`、`_RUN_LOCK = threading.Lock()`。

- [ ] **Step 1: 失败测试**（节选——全部展开写进代码文件）：

```python
def _mk_bar(date, **kw):
    b = {"date": date, "open": 10.0, "high": 11.0, "low": 9.0, "close": 10.5, "volume": 100, "amount": 1000}
    b.update(kw); return b

@pytest.mark.parametrize("bad", [
    {"high": 1.0},            # OHLC 颠倒
    {"low": -1.0},            # 负价
    {"volume": -5},           # 负量
    {"date": "2099-01-01"},   # 未来（watermark 注入 2026-09-11）
])
def test_dq_rejects_bad_bars(bad):
    from backend.bars_etl import validate_bars
    clean, rejected = validate_bars([_mk_bar("2026-09-11", **bad)], "2026-09-11")
    assert clean == [] and rejected == 1

def test_run_full_empty_response_is_failure(monkeypatch):
    import backend.bars_etl as be
    monkeypatch.setattr(be, "resolve_universe", lambda: [f"60{i:04d}" for i in range(10)])
    monkeypatch.setattr(be, "detect_gaps", lambda: {"missing": [f"60{i:04d}" for i in range(10)],
                                                    "stale_deep": [], "stale_light": [], "up_to_date": 0})
    monkeypatch.setattr(be.storage, "upsert_market_bars_batch", lambda *a, **k: 0)
    stats = be.run_full(fetch=lambda code, limit: [])   # 上游全空 = 限频/故障形态
    assert stats.aborted is True                        # 100% 失败率熔断
    assert len(stats.failed) == 10 and stats.fetched == 0
    # 且绝不写库（upsert mock 未被调用）→ 静默空洞封堵

def test_run_full_savepoint_isolates_one_bad_code(monkeypatch):
    # 10 码里第 3 码 fetch 抛异常，其余正常返回一根合法 bar：failed=[该码]，其余 9 码照常落库
    ...

def test_run_full_no_new_bar_and_force_and_universe_guard(monkeypatch): ...
def test_run_full_rejected_counted_not_stored(monkeypatch): ...
```

- [ ] **Step 2: 跑红 → Step 3: 实现**：

```python
@dataclass
class EtlStats:
    universe: int = 0
    up_to_date: int = 0
    backfill: int = 0        # 回补档码数
    daily: int = 0           # 日补档码数
    no_new_bar: int = 0
    rejected: int = 0        # DQ 坏根数（未落库）
    fetched: int = 0         # 落库行数
    failed: list[str] = field(default_factory=list)
    watermark: str = ""
    aborted: bool = False
    elapsed_ms: int = 0
    reason: str = ""

def validate_bars(bars: list[dict], watermark: str) -> tuple[list[dict], int]:
    clean, rejected = [], 0
    for bar in bars:
        o, h, l, c = (numeric_or_none(bar.get(k)) for k in ("open", "high", "low", "close"))
        v, date = numeric_or_none(bar.get("volume")), str(bar.get("date") or "")
        ok = (
            o is not None and h is not None and l is not None and c is not None and v is not None
            and min(o, h, l, c) >= 0 and v >= 0
            and l <= min(o, c) + 1e-9 and h >= max(o, c) - 1e-9
            and len(date) == 10 and date <= watermark  # 盘中半日 K/未来根双保险
        )
        (clean.append(bar) if ok else None, rejected := rejected + (0 if ok else 1))
    return clean, rejected
```

（`rejected := ...` 行是示意——实现写常规 if/else 计数。`numeric_or_none` 复用 `data_source.numeric`。）

`run_full` 骨架：入口 `_RUN_LOCK` 非阻塞（忙→`aborted, reason="overlap"`+日志，不抛）；fetch 默认 `lambda code, limit: data_source.load_history(code, limit=limit, is_index=False, adjustment="")`（走既有 `_throttle`+retry）；流程：universe 护栏（<2000 → aborted）→ 三档循环（回补 limit=500、日补 limit=max(20,lag+5)、missing 按回补）**并集追加 `_recheck_next` 队列码（上轮 rejected>0，无条件日补 limit=20，r3.1-P1-2）**→ 每码 `fetch` 空或抛→重试 1 次→仍败入 failed；非空→`validate_bars` 计 rejected→**rejected>0 的码入 `_recheck_next`**→干净根空且原非空→该码 failed（"全坏"）→`upsert_market_bars_batch`（批内 session 由 500 码组事务+逐码 `begin_nested` 包，单码异常回滚该码 SAVEPOINT 计 failed）→ 每档结束检查 `processed >= 50 and len(failed)/processed > 0.2` → aborted="fail_rate"（P2-1 最小样本）→ 汇总 `logger.info("bars_etl_ok universe=%d ...")`。**no_new_bar**：fetch 回来的 `max(date) <= _max_map 旧值` 且 upsert 行数>0 也计本档正常（重复幂等重写=假日形态）——判 `fetched==0 or 全 dups` 简单式：`set(dates) ⊆ 旧库 dates 且无新` → 该码计入 `no_new_bar`（从旧 map 拿 set 代价高，实现用 `mx.get(code)` 单值比较：bars 全根 date ≤ 旧 max → no_new_bar）。

- [ ] **Step 4: 跑绿 → Step 5: 全量+ruff/mypy → Step 6: Commit** `feat: bars_etl run_full 三档执行——空判失败/DQ 拒收/熔断自愈（P2-M1 I4）`

---

### Task 5: 调度注册（I11）+ bars_health（I5）+ lifespan + health 键（I9）

**Files:**
- Modify: `backend/bars_etl.py`（`register_jobs`、`bars_health`、`_last_run_at`）
- Modify: `backend/app.py`（lifespan :257-270 样板后追加；health() :296 附加键）
- Modify: `backend/schemas.py`（`HealthOut` + `bars: dict[str, Any] | None = None`）
- Test: `tests/test_bars_etl.py`、`tests/test_backend_api.py`

**Interfaces:**
- Consumes: Task 4 `run_full`。
- Produces: `register_jobs(scheduler) -> list[dict]`（返回实际传给 add_job 的 kwargs 列表，供测试断言/供 lifespan 调用，内部吞注册异常仅日志——行业预热样板同纪律）；`bars_health() -> dict | None`（60s 缓存 `{watermark, freshCount, universeSize, lastRunAt}`；`lastRunAt` 进程内毫秒，从未跑过=None）。

- [ ] **Step 1: 失败测试**：

```python
class FakeScheduler:
    timezone = "Asia/Shanghai"
    def __init__(self): self.calls = []
    def now(self): return datetime(2026, 9, 14, 9, 0)
    def add_job(self, fn, trigger, **kw): self.calls.append({"trigger": trigger, **kw})

def test_register_jobs_flags_and_triggers():
    from backend import bars_etl
    sched = FakeScheduler()
    calls = bars_etl.register_jobs(sched)
    assert len(calls) == 3
    ids = {c["id"] for c in calls}
    assert ids == {"bars-etl-startup", "bars-etl-daily", "bars-etl-weekly"}
    for c in calls:
        assert c["max_instances"] == 1 and c["coalesce"] is True and c["misfire_grace_time"] == 300
    daily = next(c for c in calls if c["id"] == "bars-etl-daily")
    assert daily["trigger"] == "cron" and daily["day_of_week"] == "mon-fri" and daily["hour"] == 15 and daily["minute"] == 20

def test_bars_health_shape_and_error_to_none(monkeypatch): ...
def test_health_endpoint_has_bars_key(client, monkeypatch):
    from backend import bars_etl
    monkeypatch.setattr(bars_etl, "bars_health", lambda: {"watermark": "2026-09-12", "freshCount": 1,
                                                          "universeSize": 2, "lastRunAt": None})
    body = client.get("/api/health").json()
    assert body["bars"]["watermark"] == "2026-09-12"
    assert isinstance(body["storage"]["redis"], bool)  # 既有键零触碰
```

（**spec→plan 澄清**：r3 §3.4"三触发共用 job id"在 APScheduler 3.x 不可行（同 id add_job 互相替换），改为**三独立 id + `run_full` 进程锁 `_RUN_LOCK` 兜互斥**——并发保证更强（跨 job 也互斥），锁定在计划层，验收判据 5 不变。）

- [ ] **Step 2: 跑红 → Step 3: 实现**：

```python
logger = logging.getLogger("atlas.bars_etl")
_last_run_at: dict[str, int | None] = {"at": None}
_h_cache: dict[str, object] = {"at": 0.0, "value": None}

def register_jobs(scheduler) -> list[dict]:
    common = {"id": "bars-etl-daily", "max_instances": 1, "coalesce": True, "misfire_grace_time": 300,
              "replace_existing": True}
    specs = [
        {"fn": run_full, "trigger": "interval", "seconds": 60, "id": "bars-etl-startup",
         "max_instances": 1, "coalesce": True, "misfire_grace_time": 300, "replace_existing": True},
        {"fn": run_full, "trigger": "cron", "day_of_week": "mon-fri", "hour": 15, "minute": 20, **common},
        {"fn": run_full, "trigger": "cron", "day_of_week": "sat", "hour": 10, "minute": 30,
         "id": "bars-etl-weekly", "max_instances": 1, "coalesce": True, "misfire_grace_time": 300,
         "replace_existing": True},
    ]
    registered = []
    for spec in specs:
        try:
            scheduler.add_job(**spec)
            registered.append(spec)
        except Exception:
            logger.warning("bars_etl 任务注册失败（跳过，不影响 API）", exc_info=True)
    return registered

def bars_health() -> dict | None:
    now = time.time()
    with _wm_lock:
        if now - float(_h_cache["at"]) < 60 and _h_cache["value"] is not None:
            return dict(_h_cache["value"])  # type: ignore[arg-type]
    try:
        watermark = authoritative_watermark()
        mx = _max_map()
        universe = resolve_universe()
        fresh = sum(1 for code in universe if mx.get(code) == watermark)
    except Exception:
        return None  # 不造假：查询失败回 null（health 端点容 null）
    value = {"watermark": watermark, "freshCount": fresh, "universeSize": len(universe), "lastRunAt": _last_run_at["at"]}
    with _wm_lock:
        _h_cache.update(at=now, value=dict(value))
    return value
```

（`run_full` 尾部加 `_last_run_at["at"] = int(time.time() * 1000)`。）

`app.py` lifespan（行业预热 try 块之后）：

```python
            try:
                bars_etl.register_jobs(scheduler)
            except Exception:
                review_bars_logger.warning(...)  # register_jobs 内部已逐条吞，此处双保险
```

`health()`：`bars=bars_etl.bars_health(),`（HealthOut 新字段默认 None，前端零改）。

- [ ] **Step 4: 跑绿 → Step 5: 全量门禁 → Step 6: Commit** `feat: bars_etl 调度注册与 health 水位观测（P2-M1 I5/I9/I11）`

---

### Task 6: redis_cache.CacheFacade（I6/I7，P1-1 主战场）

**Files:**
- Create: `backend/redis_cache.py`
- Create: `tests/test_redis_cache.py`

**Interfaces:**
- Produces:
  - 常量 `L2_TTL_FLOOR_SEC = 1860`（STALE_MAX_AGE+60；**物理 PX = max(FLOOR, 当前 _cache_ttl+60) 随动 ⟳ r3.1-P1-5**）、`L2_PREFIX = "atlas:q:"`、`WHITELIST_PREFIXES = ("quotes:", "history:")`、`MAX_L2_BYTES = 128_000`、`STALE_FRESH_GRACE = 5`、`BREAKER_FAILS = 3`、`BREAKER_SECONDS = 30`
  - `class CacheFacade(client, ttl_getter, clock=time.time)`：`get/set/take_stale/state/snapshot_counters()`
  - `build_facade(settings, client=None) -> CacheFacade`（client 注入面；None 且有 settings → `redis.Redis(host, port, password, db, socket_connect_timeout=1, socket_timeout=0.5, decode_responses=True)`；连接探测失败 → client 置 None，永久旁路，`state()=="down"`）
- 值封装 `{"ts": float, "v": Any}`，`json.dumps` **无 default**（TypeError=跳写不转换）。

- [ ] **Step 1: 失败测试（fake redis，可编程抛错+假时钟）**：

```python
class FakeRedis:
    def __init__(self): self.store = {}; self.fail = False; self.last_px = None
    def set(self, key, value, px=None):
        if self.fail: raise ConnectionError("down")
        self.last_px = px; self.store[key] = value; return True
    def get(self, key):
        if self.fail: raise ConnectionError("down")
        return self.store.get(key)

def facade(**kw):
    from backend.redis_cache import CacheFacade
    clock = kw.pop("clock", [1000.0])
    f = CacheFacade(client=FakeRedis(), ttl_getter=lambda: 8, clock=lambda: clock[0])
    f._clock_box = clock
    return f

def test_set_then_get_within_ttl_backfills_fresh():
    f = facade(); f.set("quotes:a", {"p": 1}, ttl=8)
    f._clock_box[0] = 1004.0
    assert f.get("quotes:a") == {"p": 1}
    assert f.client.last_px == 1860 * 1000  # P1-1：物理 TTL 与新鲜窗解耦

def test_get_rejects_beyond_ttl_plus_grace_but_take_stale_reaches():
    f = facade(); f.set("history:x", [1, 2], ttl=8)
    f._clock_box[0] = 1020.0
    assert f.get("history:x") is None            # 新鲜读 13s > 8+5 弃
    assert f.take_stale("history:x", 1800) == [1, 2]  # 降级窗物理可达（回归锚）

def test_take_stale_expires_at_1800():
    f = facade(); f.set("quotes:a", {"p": 1}, ttl=8); f._clock_box[0] = 3000.0
    assert f.take_stale("quotes:a", 1800) is None  # 2000s 超窗

def test_whitelist_blocks_screener_v2():
    f = facade(); f.set("screener_v2:p1", {"big": 1}, ttl=8)
    assert f.client.store == {}                    # 永不触 L2
    assert f.get("screener_v2:p1") is None

def test_breaker_opens_after_3_failures_and_bypass():
    f = facade(); f.client.fail = True
    for _ in range(3): f.set("quotes:a", 1, ttl=8)
    assert f.state() == "bypassed"
    f.client.fail = False
    assert f.get("quotes:a") is None               # 熔断期内仍不触 L2
    f._clock_box[0] += 31
    assert f.state() == "connected"                # 半开恢复

def test_unserializable_skips_without_type_conversion():
    f = facade(); f.set("quotes:a", {"d": object()}, ttl=8)   # 不可序列化
    assert f.client.store == {}
    assert f.snapshot_counters()["skip_unserializable"] == 1
    assert f.state() == "connected"          # ⟳ P1-3：跳写不推熔断，连续三次亦然
    for _ in range(3): f.set("quotes:a", {"d": object()}, ttl=8)
    assert f.state() == "connected"

def test_physical_px_tracks_large_cache_ttl():
    # ttl_getter 返回 3600 → PX == (3600+60)*1000；返回 8 → PX == 1860*1000（⟳ P1-5 随动）
    ...

def test_oversized_value_skipped(): ...
def test_build_facade_no_settings_returns_down_facade(): ...
```

- [ ] **Step 2: 跑红 → Step 3: 实现**（~120 行，逻辑按测试逐条满足；熔断计数 `fails/circuit_open_until`；`state()`：无 client="down"，熔断窗口内="bypassed"，否则="connected"；所有 L2 方法首行 `if self.client is None or self._bypassed(): return`；异常统一 `_on_error(exc)` 吞+计熔断，仅熔断开/闭瞬间各一条日志）
- [ ] **Step 4: 跑绿 → Step 5: ruff/mypy（redis-py 类型 stub 若缺，`redis.Redis` 构造处允许 `# type: ignore[import-untyped]` 与仓库现状对齐——先看 mypy 是否报，报则参照 storage.py 既有 ignore 风格）→ Step 6: Commit** `feat: Redis L2 CacheFacade——物理 TTL 与新鲜窗解耦、白名单、严格序列化（P2-M2 I6/I7）`

---

### Task 7: cached() 接管接线（I8——行为逐字不变的机器证明）

**Files:**
- Modify: `backend/data_source.py`（`cached()`、`set_facade()`、:312 键 sorted）
- Modify: `backend/app.py`（lifespan：`data_source.set_facade(redis_cache.build_facade(get_settings()))`；health() + `redisCache=` 附加键）
- Modify: `backend/schemas.py`（HealthOut + `redisCache: str | None = None`）
- Test: `tests/test_redis_cache.py` 追加接线组（`tests/test_backend_api.py` **既有 cached 用例零修改**）

**Interfaces:**
- Consumes: Task 6 facade。
- Produces: `data_source.set_facade(f: CacheFacade | None)`（测试复位面）；`_facade` 模块态默认 **None=纯 L1 现状**（离线测试不注入即逐字节等价旧行为）。

- [ ] **Step 1: 接线失败测试**：

```python
def test_cached_l2_hit_avoids_loader_and_backfills_l1():
    from backend import data_source
    import redis fake（复用 Task 6 FakeRedis）
    f = CacheFacade(client=FakeRedis(), ttl_getter=lambda: 8, clock=...)
    f.set("quotes:sh600000", {"px": 9.9}, ttl=8)
    data_source.cache.clear()
    data_source.set_facade(f)
    try:
        calls = []
        v = data_source.cached("quotes:sh600000", lambda: calls.append(1) or {"px": 0})
        assert v == {"px": 9.9} and calls == []
        assert data_source.cache.get("quotes:sh600000")[1] == {"px": 9.9}  # L1 回填
    finally:
        data_source.set_facade(None)

def test_cached_loader_failure_falls_to_L2_stale_when_L1_missing(): ...
def test_cached_screener_v2_never_touches_L2(): ...  # I8 断言
def test_quotes_key_sorted_normalization(monkeypatch):
    # load_quote_symbols(["sz000002","sh600000"]) 与逆序产生同一缓存键
```

- [ ] **Step 2: 跑红 → Step 3: 实现**：`cached()` 改造（L1 逻辑原样保留为第一级；L2 读仅在 `_facade` 存在时；loader 成功后 `if _facade: _facade.set(key, value, _cache_ttl)`；异常兜底链 **L1 stale → facade.take_stale(key, STALE_MAX_AGE) → mark_stale/raise**，命中 L2 时同样回填 L1 并 mark_stale）；:312 改 `f"quotes:{','.join(sorted(unique_symbols))}"`；lifespan/health/schemas 接线。**既有 `cached()` 语义测试（test_backend_api.py 相关用例）一行不改必须全绿**——这是 I8 的验收。
- [ ] **Step 4: 跑绿 → Step 5: 全量七件套（含 `python -m pytest tests/test_backend_api.py -k cache -q` 单列证据）→ Step 6: Commit** `feat: cached() 接入 CacheFacade L2——外部行为逐字不变（P2-M2 I8/I9）`

---

### Task 8: 真实冒烟（M1 传导 + M2 命中，验收判据 1/2/3/4 取证）

**Files:**
- Create: `.superpowers/smoke_bars.py`（gitignored，仅存档证据）
- Output: `.superpowers/smoke_bars_out.json`

**Steps:**
- [ ] 1. 停后端→清 L1（进程自然空）→起后端（lifespan 60s 首查会触发全量回补——**后台跑 9-15 分钟**，`job` 方式监控日志 `bars_etl_ok`）。
- [ ] 2. 回补完成后断言：`GET /api/health` → `bars.freshCount/bars.universeSize ≥ 0.95`、watermark==当日（假日跑则记 no_new_bar 轮，次日复跑，如实）。
- [ ] 3. 抽 3 码（含 1 北交所工作区码若自选里有）：`/api/plans/review`、`/api/portfolio/risk` 冷进程 → 响应 stats/日志断言 **upstream 码集合 ⊆ 非 universe**，差集打印入 json。
- [ ] 4. Redis 面：轮询 3 分钟 → `redisCache=="connected"`、fake 计数无法用——以**进程日志无对应上游 fetch**（`_throttle` debug 级不动；用 facade snapshot 附加日志或临时 `snapshot_counters()` 打印）证明 L2 命中；再**停 Redis 容器**→观察 `redisCache→bypassed` 且行情无感→起回→`connected`（判据 4）。
- [ ] 5. 证据 json 落盘（各步时间戳+计数原文），A1 清理调用一次并记录删除行数。
- [ ] 6. Commit：无代码面（脚本 gitignored 则**跳过提交**；若有 smoke 级修复归入各任务）。证据文件路径写进 SDD 台账。

---

### Task 9: 文档同步（AGENTS/ROADMAP）

**Files:**
- Modify: `AGENTS.md`（存储与数据说明：Redis 不再是"仅 ping"——行情/历史 `quotes:/history:` 已接管 L2，旁路=现状；`bars_etl.py` 模块行 + 调度三触发 15:20/60s/周六；`upsert_market_bars_batch` 进 storage 描述；测试计数按最终实数刷新；`/api/health` 附加键 `bars`/`redisCache`）
- Modify: `ROADMAP.md`（P2 两项 → ✅ 已交付 + 日期 + 残留边界一句话：北交所全市场/qfq 漂移/假日空转见 spec §9）
- [ ] 跑 `prettier --check`（两文件若属历史未格式化文件则**只保证不新增违例**），Commit `docs: P2 交付后 AGENTS/ROADMAP 同步`

---

## 最终闸（SDD 收尾，非任务）

全量七件套 + 本计划新增全部约束用例绿 → `python .superpowers/sdd.py package` 整分支 diff → 终审（重点：I8 既有测试零修改证据、P0-2/P1-1 回归锚在位、health 契约零触碰）→ `git flow feature finish p2-bars-etl-redis` → push develop → 台账/报告。

## Self-Review 结论（计划 vs spec r3）

- §3.1-3.7 → T3/T4/T5（+T1 A1、T2 I10）；§4.1-4.4 → T6/T7；§5 I1-I11 全覆盖（I11 有**成文澄清**：三独立 job id+进程锁替代同 id 三触发）；§8 四类测试映射 T3-T7 各 Step1 + T8 冒烟；§10 判据 1-5 → T8 步骤 2-4 + 最终闸。
- 占位符扫描：两处 `...` 为"按既有夹具风格展开"的显式指令（非 TBD），执行时由实现者以完整代码落地，评审任务时把关。
- 类型一致性：`upsert_market_bars_batch`/`EtlStats`/`CacheFacade` 三契约在 T2/T4/T6 定义处与消费处签名逐字一致。
