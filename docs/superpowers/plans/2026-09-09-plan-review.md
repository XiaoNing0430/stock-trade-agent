# P1 计划绩效复盘 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 对已创建交易计划做设计口径回算（不复权日线回放），聚合成胜率/盈亏比/期望值并按来源分组，在 ViewPlans 新增可折叠绩效面板。

**Architecture:** 新后端模块 `backend/plan_review.py`（纯函数回放引擎 + bars 批量获取委托 + 聚合），两条新只读端点（`GET /api/plans/review`、`GET /api/screener/scan/history`）；`trade_plans` 加 `source` 列实现来源归因（openFor → PlanDraftDialog → 计划 落库链路）；`load_history` 全链路加 `adjustment` 参数支持原始价（bfq）；前端新增 `useReviewStore` + ViewPlans 绩效区块。

**Tech Stack:** Python/FastAPI/SQLAlchemy/Alembic（后端）；Vue 3 + TS strict + Pinia + vitest（前端）；pytest-cov ≥80%。

**Spec:** `docs/superpowers/specs/2026-09-09-plan-review-spec.md`（r3.1 已批准，20 条决议为契约）。

## Global Constraints

- **绝不造数**：缺失数据显示 `--`/空态；比率分母为 0 一律 `null` 占位（spec FR-3）。
- **红线：回放零写 plans 表**——review 端点只读；bars 写入仅限 `market_bars` 缓存表。
- **保留现有 API 字段名**；只增不改（source、kpis/groups/items 全部新键）。
- **计划价口径 = 原始实时价**；回放 bars = 不复权（bfq）；`load_history` 默认 `adjustment="qfq"` 兼容现有全部调用（app.py:121、app.py:630、assist/service.py:116、screener/pipeline.py:252）。
- **回放窗口**：创建日（Asia/Shanghai）后第一个可交易 bar → validity 过期日（或今天）**当日或之前**最近一个**已收盘**交易日；`barDate < 今天(Asia/Shanghai)` 才参与。
- **sell = 已持仓平仓单（非做空）**；R = (exit − entry)/(entry − stop) 不翻向；入场触及 = `low ≤ entry`（跳空穿越按触及，成交价恒记计划 entry）；顺延后触发价恒为原 entry/stop/target。
- **成本**：`costR = feeRate × entry / |entry − stop|`，feeRate 默认 0.0015，校验 [0, 0.05] 越界 422；`netR = R − costR`；胜 = 触及 target；winRate 分母 = decided(胜+败)；payoffRatio 平出不计入、败样本空或 avgLossR=0 → null。
- **统计命名**：`decided`/`flatCount`（不用 breakeven）/outcome 值 `flat`/`notEnteredRate` 分母 = decided+flatCount+notEntered。
- **测试门禁**：后端 pytest（≥80% 覆盖）+ ruff format/check + mypy；前端 vitest + vue-tsc + eslint。全部跑过后才可提交 docs 任务。
- **Git Flow**：`git flow feature start plan-review`（基于 develop）；提交 Conventional Commits 中文主题；subagent 内提交用 `--no-verify`（pre-commit 不在 subagent 跑，Task 9 全量门禁兜底）。
- **测试文件**：后端统一 `tests/test_plan_review.py`；前端 `tests/frontend/useReviewStore.test.ts`（新建）+ 既有文件扩展。
- **subagent 上下文纪律**：实施者只读任务指定文件与锚点，禁止全文通读大文件（storage.py/app.py 超 800 行，用 grep 定位行号后读 ±40 行窗口）。

---

### Task 1: source 归因数据面（模型列 + 迁移 + 存取 + TS 类型）

**Files:**
- Modify: `backend/storage.py`（TradePlan 模型 ~line 40-46；`_plan_dict` line 272；`save_workspace` plans 段 ~line 440-470）
- Create: `backend/migrations/versions/<hash>_trade_plans_add_source.py`（autogenerate 生成）
- Modify: `frontend/src/types/models.ts`（Plan 接口）
- Test: `tests/test_plan_review.py`（新建，本任务先写存储段）

**Interfaces:**
- Produces: `TradePlan.source: str | None`（String(64) 可空）；`_plan_dict` 输出含 `"source": plan.source`；`save_workspace` 接受 `item["source"]`（空串/缺省 → None）；TS `Plan.source?: string`。后续 Task 6/7 依赖这些形状。

- [ ] **Step 1: 写失败测试**（`tests/test_plan_review.py` 新建）

```python
"""计划绩效复盘：source 归因存储 + bfq 链路 + 回放引擎 + 聚合 API。"""
from __future__ import annotations

import pytest

from backend import storage


@pytest.fixture()
def _plan_rows(session_db):  # session_db 为 test_storage_coverage.py 既有 fixture，若名不同则 grep tests/ 确认
    yield


def test_plan_dict_carries_source(session_db):
    with storage.SessionLocal() as session:  # 与 test_storage_coverage.py 同款会话用法；先 grep 该文件确认 fixture/工厂
        plan = storage.TradePlan(
            id="p1", workspace_id="default", code="300750", direction="buy",
            entry=10.0, stop=9.5, target=11.0, capital=10000, position=50,
            validity="本周内", source="scan:trend_breakout",
        )
        session.add(plan)
        session.commit()
        loaded = session.get(storage.TradePlan, "p1")
        assert loaded.source == "scan:trend_breakout"
        d = storage._plan_dict(loaded)
        assert d["source"] == "scan:trend_breakout"


def test_plan_source_null_is_legacy_ready(session_db):
    with storage.SessionLocal() as session:
        plan = storage.TradePlan(
            id="p2", workspace_id="default", code="600519", direction="buy",
            entry=10.0, stop=9.5, target=11.0, capital=10000, position=50, validity="本周内",
        )
        session.add(plan)
        session.commit()
        loaded = session.get(storage.TradePlan, "p2")
        assert loaded.source is None
        assert storage._plan_dict(loaded)["source"] is None  # 归一为 legacy 在 plan_review 层做


def test_save_workspace_roundtrips_source(session_db):
    payload = {
        "plans": [{
            "id": "p3", "code": "000001", "direction": "buy", "entry": 10.0, "stop": 9.5,
            "target": 11.0, "capital": 10000, "position": 50, "validity": "本月内",
            "status": "执行中", "triggered": {}, "createdAtMs": 1700000000000,
            "source": "manual",
        }],
        "watchlist": [], "alerts": [], "settings": {},
    }
    storage.save_workspace(payload)
    ws = storage.get_workspace()
    plan = next(p for p in ws["plans"] if p["id"] == "p3")
    assert plan["source"] == "manual"
    payload["plans"][0]["source"] = ""  # 空串 → None（存量/清空语义）
    storage.save_workspace(payload)
    plan = next(p for p in storage.get_workspace()["plans"] if p["id"] == "p3")
    assert plan["source"] is None
```

注意：`session_db`/会话工厂的确切名称以 `tests/test_storage_coverage.py` 现有写法为准（grep `SessionLocal\|session` 该文件头 60 行后对齐，勿臆造 fixture）。若该文件用 `memory engine`/`initialize_storage` 模式，照抄其 setup。

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_plan_review.py -q --no-cov`
Expected: FAIL（`TradePlan` 无 `source` 属性 / `_plan_dict` 无 source 键）

- [ ] **Step 3: 实现**

1. `backend/storage.py` TradePlan 模型 `triggered` 行（line ~41）后加：
```python
    source: Mapped[str | None] = mapped_column(String(64), nullable=True)
```
2. `_plan_dict`（line 272）dict 内加 `"source": plan.source,`（放在 `"triggered"` 之后）。
3. `save_workspace` plans 段（grep `plan.pos` 定位字段赋值块）在 `plan.note = ...` 附近加：
```python
            plan.source = item.get("source") or None
```
4. Alembic：`alembic revision --autogenerate -m "trade_plans add source"`。**检查生成脚本**：只允许含 `op.add_column("trade_plans", sa.Column("source", sa.String(length=64), nullable=True))` 与对应 downgrade `op.drop_column("trade_plans", "source")`；若 autogenerate 夹带其他表变更，删除多余 op（Task 8 的 scan 迁移先例：autogenerate 噪声必须手工修剪）。
5. `frontend/src/types/models.ts` Plan 接口 `triggered` 字段后加：
```ts
  source?: string;
```

- [ ] **Step 4: 跑测试确认通过 + 迁移往返**

Run: `python -m pytest tests/test_plan_review.py -q --no-cov` → PASS
Run: `alembic downgrade -1 && alembic upgrade head && alembic current`（往返后回到新 head；输出贴报告）

- [ ] **Step 5: 提交**

```bash
git add backend/storage.py backend/migrations/versions/ frontend/src/types/models.ts tests/test_plan_review.py
git commit -m "feat: 交易计划加 source 来源归因列（迁移+存取+TS 类型）" --no-verify
```

---

### Task 2: bfq 原始价链路（load_history 全链路 adjustment 参数）

**Files:**
- Modify: `backend/data_source.py:329`（tencent ds `load_history`——cached key + param 尾字段 + rows 键选择）
- Modify: `backend/sources/base.py:21`（ABC 签名）
- Modify: `backend/sources/tencent.py:37`（委托透传）
- Modify: `backend/sources/eastmoney.py:127`（`fqt` 映射）
- Modify: `backend/sources/mock_us.py:131`（接受参数，合成数据 no-op）
- Test: `tests/test_plan_review.py`（bfq 段）

**Interfaces:**
- Produces: 全部 5 处 `load_history(..., adjustment: str = "qfq")`；`adjustment=""` → 不复权（腾讯 param 尾字段空串、响应取 `day` 行；东财 `fqt: 0`；mock no-op）。Task 5 的 `fetch_all_bars` 依赖 `router 适配器.load_history(code, limit=300, is_index=False, adjustment="")` 可用。
- 兼容红线：现有 4 个调用点（app.py:121、app.py:630、assist/service.py:116、screener/pipeline.py:252）**不改一行**，靠默认值保持 qfq 行为。

- [ ] **Step 1: 写失败测试**

```python
def _row(date: str) -> list:
    return [date, "10.0", "10.2", "10.5", "9.9", "100000", "102000000", "1.5", "2.0", "0.1", "1.1"]


def test_load_history_default_qfq_unchanged(monkeypatch):
    from backend import data_source as ds
    keys: list[str] = []
    seen: dict[str, str] = {}

    def fake_cached(key, fn):
        keys.append(key)
        return fn()

    def fake_fetch_json(url, params):
        seen["param"] = params["param"]
        return {"data": {"sh600519": {"qfqday": [_row("2026-09-01")]}}}

    monkeypatch.setattr(ds, "tencent_symbol", lambda c: "sh600519")
    monkeypatch.setattr(ds, "cached", fake_cached)
    monkeypatch.setattr(ds, "fetch_json", fake_fetch_json)
    rows = ds.load_history("600519", limit=40)
    assert rows[0]["date"] == "2026-09-01"
    assert keys == ["history:sh600519:40:qfq"]          # 默认 qfq：缓存键含 :qfq
    assert seen["param"] == "sh600519,day,,,40,qfq"     # 上游 param 尾字段 qfq（现行为不变）


def test_load_history_bfq_uses_day_rows(monkeypatch):
    from backend import data_source as ds
    keys: list[str] = []
    seen: dict[str, str] = {}

    def fake_cached(key, fn):
        keys.append(key)
        return fn()

    def fake_fetch_json(url, params):
        seen["param"] = params["param"]
        return {"data": {"sh600519": {"day": [_row("2026-09-02")]}}}   # 不复权响应只有 day 键

    monkeypatch.setattr(ds, "tencent_symbol", lambda c: "sh600519")
    monkeypatch.setattr(ds, "cached", fake_cached)
    monkeypatch.setattr(ds, "fetch_json", fake_fetch_json)
    rows = ds.load_history("600519", limit=40, adjustment="")
    assert rows[0]["date"] == "2026-09-02"
    assert keys == ["history:sh600519:40:"]             # 空串 fq 的缓存键（与 qfq 键不冲突）
    assert seen["param"] == "sh600519,day,,,40,"        # 尾字段空串 → 上游返回原始价


def test_storage_market_bars_bfq_roundtrip(session_db):
    bars = [{"date": "2026-09-01", "open": 10.0, "close": 10.2, "high": 10.5,
             "low": 9.9, "volume": 100000, "amount": 102000000.0, "change": 1.5}]
    storage.save_market_bars("300750", bars, adjustment="")
    loaded = storage.load_market_bars("300750", adjustment="")
    assert loaded[0]["date"] == "2026-09-01"
    qfq = storage.load_market_bars("300750", adjustment="qfq")  # 互不污染
    assert qfq == []
```

```python
def test_storage_market_bars_bfq_roundtrip(session_db):
    bars = [{"date": "2026-09-01", "open": 10.0, "close": 10.2, "high": 10.5,
             "low": 9.9, "volume": 100000, "amount": 102000000.0, "change": 1.5}]
    storage.save_market_bars("300750", bars, adjustment="")
    loaded = storage.load_market_bars("300750", adjustment="")
    assert loaded[0]["date"] == "2026-09-01"
    qfq = storage.load_market_bars("300750", adjustment="qfq")  # 互不污染
    assert qfq == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_plan_review.py -q --no-cov -k bfq or qfq`
Expected: FAIL（`load_history() got an unexpected keyword argument 'adjustment'`）

- [ ] **Step 3: 实现（5 处签名 + 解析）**

1. `backend/data_source.py:329`：
```python
def load_history(code: str, limit: int = 40, is_index: bool = False, adjustment: str = "qfq") -> list[dict[str, Any]]:
    symbol = index_symbol(code) if is_index else tencent_symbol(code)
    fq = adjustment or ""
    payload = cached(
        f"history:{symbol}:{limit}:{fq}",
        lambda: fetch_json(KLINE_URL, {"param": f"{symbol},day,,,{limit},{fq}"}),
    )
    data = payload.get("data") or {}
    symbol_data = data.get(symbol) or {}
    rows = symbol_data.get(f"{fq}day") or symbol_data.get("day") or symbol_data.get("qfqday") or []
```
（`fq="qfq"` 时 `qfqday` 优先＝现行为；`fq=""` 时 `day` 优先。行解析部分不动。）
2. `backend/sources/base.py:21`：`def load_history(self, code: str, limit: int, is_index: bool, adjustment: str = "qfq") -> list[dict[str, Any]]: ...`
3. `backend/sources/tencent.py:37-38`：`return tencent_ds.load_history(code, limit, is_index, adjustment)`，签名加 `adjustment: str = "qfq"`。
4. `backend/sources/eastmoney.py:127`：签名加 `adjustment: str = "qfq"`；params 中 `"fqt": 1` 改为 `"fqt": 1 if adjustment == "qfq" else (2 if adjustment == "hfq" else 0)`。
5. `backend/sources/mock_us.py:131`：签名加 `adjustment: str = "qfq"`（合成数据 no-op，docstring 注明）。若 mock 内部有自用历史工厂，无需改逻辑。
6. **Router 检查**：`grep -n "def load_history" backend/data_source.py backend/sources/` 确认是否还有 Router 级包装（如 `DataSourceRouter.load_history`）；有则同样加 `adjustment: str = "qfq"` 透传，无则 ABC 默认值已覆盖。把 grep 输出贴报告。
7. 回归：`python -m pytest tests/ -q --no-cov -k "history or backtest or assist or screener"` 确认 4 个既有调用点行为不变。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_plan_review.py -q --no-cov` → PASS（bfq 段全绿）

- [ ] **Step 5: 提交**

```bash
git add backend/data_source.py backend/sources/ tests/test_plan_review.py
git commit -m "feat: load_history 全链路支持 adjustment 参数（bfq 原始价，默认 qfq 兼容）" --no-verify
```

---

### Task 3: 回放引擎核心（窗口切片 + 六态 + 双触 + sell + R/净R）

**Files:**
- Create: `backend/plan_review.py`
- Test: `tests/test_plan_review.py`（回放核心段）

**Interfaces:**
- Consumes: Task 1 的 plan dict 形状（`_plan_dict` + `createdAtMs` 由编排层补）。
- Produces（Task 4/5 依赖，签名冻结）:
  - `SHANGHAI: timezone`
  - `shanghai_date_str(ms: int) -> str`
  - `validity_expiry_date(created_ms: int, validity: str) -> str`（本月内=创建月月末；本周内=ISO 周日；长期/空=哨兵 "9999-12-31"（经 min(expiry, today) 收口为今天，spec 边界表）；其他未知=创建当日）
  - `slice_window(bars: list[dict], created_ms: int, validity: str, today: str | None = None) -> tuple[list[dict], dict | None, bool]` → (窗口 bars（已收盘）, 窗口前一根 bar（供 prevClose，可 None）, 窗口是否已闭合)
  - `replay_plan(plan: dict, bars: list[dict], fee_rate: float, today: str | None = None) -> dict`（items 行形状，outcome ∈ win|loss|flat|notEntered|open|invalid）
  - `InvalidOutcome` 常量 `"invalid"` 等（直接用字符串字面量即可）

- [ ] **Step 1: 写失败测试（fixture 与用例一起给全）**

fixture 工具（放 `tests/test_plan_review.py` 顶部）：

```python
def make_bars(dates_prices: list[tuple[str, float, float, float, float, float]]) -> list[dict]:
    """(date, open, close, high, low, volume) → bar dicts，amount/change 补默认。"""
    return [{"date": d, "open": o, "close": c, "high": h, "low": l, "volume": v,
             "amount": 1_000_000.0, "change": 1.0} for d, o, c, h, l, v in dates_prices]


def make_plan(**over) -> dict:
    base = {"id": "p1", "code": "300750", "direction": "buy", "entry": 10.0, "stop": 9.5,
            "target": 11.0, "capital": 10000, "position": 50, "validity": "本月内",
            "status": "执行中", "triggered": {}, "createdAtMs": 1_789_084_800_000,
            "note": "", "createdAt": "00:00", "source": None}
    base.update(over)
    return base
```

`createdAtMs = 1_789_084_800_000` = **2026-09-11（周五）08:00 Asia/Shanghai**（已实算：1_767_225_600 = 2026-01-01 00:00 UTC，+253 整天）。全局 `TODAY = "2026-10-05"`（所有「本月内」窗口（09-30 过期）均已闭合）；需要未闭合窗口的用例显式传更早的 today。所有用例不依赖墙钟。

核心用例（each asserts outcome/rValue/netR/costR/ambiguous/entryDate/exitDate 精确值；数字必须手推并在注释里写明推导）：

```python
from backend.plan_review import replay_plan, slice_window, validity_expiry_date, shanghai_date_str

TODAY = "2026-10-05"  # 「本月内」（过期 09-30）窗口均闭合

def test_buy_win_hits_target_first():
    # 创建 09-11；窗口从 09-14 起。entry=10 stop=9.5 target=11 → risk=0.5
    # 09-14 low=9.8>未触? low 9.8 > entry 10? 9.8<10 → 触及 entry（low≤entry）
    # 09-15 high=11.3 ≥ target 11 → win, R=(11-10)/0.5=2.0；costR=0.0015*10/0.5=0.03 → netR=1.97
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),
                      ("2026-09-15", 10.5, 11.2, 11.3, 10.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "win" and rec["rValue"] == 2.0 and rec["netR"] == 1.97
    assert rec["entryDate"] == "2026-09-14" and rec["exitDate"] == "2026-09-15"
    assert rec["costR"] == 0.03 and rec["ambiguous"] is False

def test_buy_loss_hits_stop():
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),
                      ("2026-09-15", 10.0, 9.4, 10.1, 9.4, 1000.0)])  # low 9.4 ≤ stop 9.5
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "loss" and rec["rValue"] == -1.0 and rec["netR"] == -1.03

def test_same_day_double_touch_conservative_loss():
    # 09-14 当日 low 9.4≤stop 且 high 11.2≥target → 保守记败 R=-1
    bars = make_bars([("2026-09-14", 10.2, 10.0, 11.2, 9.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "loss" and rec["ambiguous"] is True and rec["rValue"] == -1.0

def test_gap_down_whole_day_below_entry_still_enters():
    # 整日低于 entry（high 9.8 < entry 10）→ low ≤ entry 触及成立（r3.1），成交价记 entry=10
    # 09-15 收 9.4≤stop? low 9.4 ≤ stop 9.5 → loss -1
    bars = make_bars([("2026-09-14", 9.7, 9.6, 9.8, 9.5, 1000.0),
                      ("2026-09-15", 9.5, 9.4, 9.6, 9.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["entryDate"] == "2026-09-14" and rec["outcome"] == "loss"

def test_flat_exits_at_window_end_close():
    # 窗口内触及 entry 后 target/stop 均未触 → 平出，exit=末收盘 10.1，R=(10.1-10)/0.5=0.2
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.3, 9.9, 1000.0),
                      ("2026-09-15", 10.1, 10.1, 10.4, 10.0, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "flat" and abs(rec["rValue"] - 0.2) < 1e-9

def test_not_entered_when_entry_never_touched():
    bars = make_bars([("2026-09-14", 10.5, 10.6, 10.8, 10.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "notEntered" and rec["rValue"] is None

def test_open_when_window_not_closed():
    # validity=本月内（09-11 创建 → 09-30 过期）但 today=09-16：窗口未闭合 → 进行中
    bars = make_bars([("2026-09-14", 10.5, 10.6, 10.8, 10.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today="2026-09-16")
    assert rec["outcome"] == "open"

def test_sell_direction_flat_order_semantics():
    # sell：无未入场判定；先 target 记胜。R=(11-10)/0.5=2.0（不翻向）
    bars = make_bars([("2026-09-14", 10.5, 11.1, 11.2, 10.4, 1000.0)])
    rec = replay_plan(make_plan(direction="sell"), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "win" and rec["rValue"] == 2.0

def test_invalid_plan_params():
    rec = replay_plan(make_plan(entry=0), [], 0.0015, today=TODAY)
    assert rec["outcome"] == "invalid"
    rec2 = replay_plan(make_plan(stop=10.5), [], 0.0015, today=TODAY)  # entry-stop ≤ 0
    assert rec2["outcome"] == "invalid"

def test_no_bars_at_all_is_invalid():
    rec = replay_plan(make_plan(), [], 0.0015, today=TODAY)
    assert rec["outcome"] == "invalid"

def test_creation_day_bar_excluded_and_expiry_day_included():
    # 创建 2026-09-11（周五）：09-11 的 bar 不参与（决议 9）；窗口从 09-14 起
    # validity=本周内 → 过期日=09-13（ISO 周日，已实算）
    assert validity_expiry_date(1_789_084_800_000, "本周内") == "2026-09-13"
    assert validity_expiry_date(1_789_084_800_000, "本月内") == "2026-09-30"
    bars = make_bars([("2026-09-11", 9.0, 9.0, 9.0, 9.0, 1000.0),   # 创建当日：若被误用会立刻 win（low≤entry≤target）→ 该用例防前视
                      ("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0)])
    rec = replay_plan(make_plan(validity="本月内"), bars, 0.0015, today=TODAY)
    assert rec["entryDate"] == "2026-09-14"  # 创建当日 bar 未参与

def test_unclosed_today_bar_excluded():
    # today=09-15：09-15 的 bar 是"今天"，未收盘不参与 → 09-14 触及 entry 后窗口无后续 → open
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),
                      ("2026-09-15", 11.5, 11.6, 11.7, 11.0, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today="2026-09-15")
    assert rec["outcome"] == "open"

def test_sell_empty_closed_window_is_invalid():
    # sell 已持仓平仓单：窗口空（bars 全在创建日前）且已闭合 → invalid（评审 B1；无末收盘价可平出，绝不算 notEntered）
    bars = make_bars([("2026-09-01", 10, 10, 10, 10, 1000.0)])
    rec = replay_plan(make_plan(direction="sell"), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "invalid"

def test_validity_long_term_and_empty_sentinel():
    # 长期/空 → 哨兵 9999-12-31，slice_window 收口为"终点=今天"（spec 边界表；评审非 Blocker ①）
    assert validity_expiry_date(1_789_084_800_000, "长期") == "9999-12-31"
    assert validity_expiry_date(1_789_084_800_000, "") == "9999-12-31"
    bars = make_bars([("2026-09-14", 10.5, 10.6, 10.8, 10.4, 1000.0)])
    rec = replay_plan(make_plan(validity="长期"), bars, 0.0015, today="2026-09-16")
    assert rec["outcome"] == "open"   # 窗口未闭合 → 进行中（非 notEntered）
```

窗口终点语义用例（slice_window 直测，数值已按 createdAt=09-11 钉死）：

```python
def test_slice_window_expiry_day_bar_included():
    # validity=本周内 → 过期日 09-13；today=09-16 → end_date=min(09-13, 09-16)=09-13，已闭合
    # 窗口 = (09-11, 09-13] → 09-12、09-13；prevClose 用 09-11（创建当日 bar 可作 prev）
    bars = make_bars([("2026-09-11", 10, 10, 10, 10, 1000.0),
                      ("2026-09-12", 10, 10, 10, 10, 1000.0),
                      ("2026-09-13", 10, 10, 10, 10, 1000.0),
                      ("2026-09-14", 10, 10, 10, 10, 1000.0)])   # 09-14 > 过期日 → 不在窗口
    window, prev, closed = slice_window(bars, 1_789_084_800_000, "本周内", today="2026-09-16")
    assert [b["date"] for b in window] == ["2026-09-12", "2026-09-13"]  # 过期日当日 bar 参与（r3.1 消歧）
    assert closed is True and prev is not None and prev["date"] == "2026-09-11"

def test_slice_window_excludes_unclosed_today_bar():
    # today=09-15：09-15 的 bar 未收盘，即使 ≤ end_date 也排除（B2）
    bars = make_bars([("2026-09-11", 10, 10, 10, 10, 1000.0),
                      ("2026-09-14", 10, 10, 10, 10, 1000.0),
                      ("2026-09-15", 10, 10, 10, 10, 1000.0)])
    window, _, closed = slice_window(bars, 1_789_084_800_000, "本月内", today="2026-09-15")
    assert [b["date"] for b in window] == ["2026-09-14"]    # 09-15（今天）被 < today 排除
    assert closed is False                                   # end_date=min(09-30,09-15)=09-15 不早于今天
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_plan_review.py -q --no-cov -k replay`
Expected: FAIL（`No module named 'backend.plan_review'`）

- [ ] **Step 3: 实现 `backend/plan_review.py`（本任务范围：核心回放，不含跳空/一字板——Task 4 加）**

```python
"""计划绩效复盘——设计口径回放引擎。纯函数；bars 获取与聚合在编排层（Task 5）。

契约：docs/superpowers/specs/2026-09-09-plan-review-spec.md r3.1（决议 3/4/6/9/10/17/20）。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

SHANGHAI = timezone(timedelta(hours=8))


def shanghai_date_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, SHANGHAI).strftime("%Y-%m-%d")


def validity_expiry_date(created_ms: int, validity: str) -> str:
    """镜像前端 planUtils.validityExpiry：本月内=创建月月末；本周内=ISO 周日；其他未知=创建当日。

    例外（有意分歧，以 spec 边界表为准）：长期/空 → "9999-12-31" 哨兵，
    经 slice_window 的 min(expiry, today) 收口为"窗口终点=今天"（评审非 Blocker ①）。
    """
    base = datetime.fromtimestamp(created_ms / 1000, SHANGHAI)
    if validity == "本月内":
        nxt = base.replace(year=base.year + 1, month=1, day=1) if base.month == 12 else base.replace(month=base.month + 1, day=1)
        end = nxt - timedelta(days=1)
    elif validity == "本周内":
        end = base + timedelta(days=(6 - base.weekday()) % 7)  # Monday=0 → 周日差 (6-wd)
    elif validity in ("长期", ""):
        return "9999-12-31"
    else:
        end = base
    return end.strftime("%Y-%m-%d")


def slice_window(bars: list[dict[str, Any]], created_ms: int, validity: str,
                 today: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any] | None, bool]:
    """回放窗切片。bars 按 date 升序（编排层保证不含未收盘 bar）。

    返回 (窗口bars, 窗口前一根bar（prevClose 用，可 None）, 窗口是否已闭合)。
    窗口 = 创建日 < barDate ≤ min(过期日, 今天) 且 barDate < 今天（B2：未收盘 bar 一律排除）。
    """
    today = today or shanghai_date_str(int(datetime.now(SHANGHAI).timestamp() * 1000))
    start_date = shanghai_date_str(created_ms)          # 创建当日 bar 不参与（决议 9）
    end_date = validity_expiry_date(created_ms, validity)
    end_date = min(end_date, today)
    prior = [b for b in bars if b["date"] < start_date]
    window = [b for b in bars if start_date < b["date"] <= end_date and b["date"] < today]
    closed = end_date < today                            # 过期日 < 今天 → 窗口已闭合
    return window, (prior[-1] if prior else None), closed


def replay_plan(plan: dict[str, Any], bars: list[dict[str, Any]], fee_rate: float,
                today: str | None = None) -> dict[str, Any]:
    entry = float(plan.get("entry") or 0)
    stop = float(plan.get("stop") or 0)
    target = float(plan.get("target") or 0)
    direction = plan.get("direction") or "buy"
    rec: dict[str, Any] = {
        "planId": plan.get("id"), "code": plan.get("code"),
        "source": plan.get("source") or "legacy", "direction": direction,
        "entry": entry, "stop": stop, "target": target,
        "validity": plan.get("validity") or "", "status": plan.get("status") or "执行中",
        "outcome": "invalid", "rValue": None, "netR": None, "costR": None,
        "entryDate": None, "exitDate": None,
        "ambiguous": False, "gapFill": False, "limitDeferred": False,
    }
    if not bars or entry <= 0 or stop <= 0 or target <= 0 or entry - stop <= 0:
        return rec
    created_ms = int(plan.get("createdAtMs") or 0)
    window, prev_bar, closed = slice_window(bars, created_ms, plan.get("validity") or "", today)
    risk = entry - stop
    rec["costR"] = round(fee_rate * entry / risk, 4)
    entered = direction == "sell"  # 已持仓平仓单：无未入场判定（决议 10）

    def r_of(exit_price: float) -> float:
        return round((exit_price - entry) / risk, 3)

    for bar in window:
        low = float(bar["low"]); high = float(bar["high"])
        if not entered:
            if low <= entry:            # r3.1：跳空穿越亦触及，成交价恒记计划 entry
                entered = True
                rec["entryDate"] = bar["date"]
            else:
                continue
        hit_stop = low <= stop
        hit_target = high >= target
        if hit_stop and hit_target:     # 同日双触保守记败（决议 3）
            rec.update(outcome="loss", rValue=-1.0, exitDate=bar["date"], ambiguous=True)
            return _finalize(rec)
        if hit_target:
            rec.update(outcome="win", rValue=r_of(target), exitDate=bar["date"])
            return _finalize(rec)
        if hit_stop:
            rec.update(outcome="loss", rValue=-1.0, exitDate=bar["date"])
            return _finalize(rec)
    # 窗口走完未决：未闭合 → 进行中；已闭合 → 入场过=平出；未入场（仅 buy）→ notEntered；
    # sell 无未入场概念，窗口空且已闭合 → invalid（无末收盘价可平出，评审 B1）
    if not closed:
        rec["outcome"] = "open"
    elif entered and window:
        rec.update(outcome="flat", rValue=r_of(float(window[-1]["close"])), exitDate=window[-1]["date"])
    elif direction == "sell":
        rec["outcome"] = "invalid"
    else:
        rec["outcome"] = "notEntered"
    return _finalize(rec)


def _finalize(rec: dict[str, Any]) -> dict[str, Any]:
    if rec["rValue"] is not None and rec["costR"] is not None:
        rec["netR"] = round(rec["rValue"] - rec["costR"], 3)
    return rec
```

注意：窗口走完的兜底三分支（未闭合→open；闭合+入场→flat；闭合+未入场→notEntered）语义互相穷尽；"窗口为空且已闭合 + 已入场"不可能发生（入场必在窗口内某根 bar）。空 bars 整体在入口返回 `invalid`（边界表"无 bars → invalid"）。

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_plan_review.py -q --no-cov -k "replay or slice or validity"` → PASS（先实算 createdAt 日期修正字面量）

- [ ] **Step 5: 提交**

```bash
git add backend/plan_review.py tests/test_plan_review.py
git commit -m "feat: 计划回放引擎核心（窗口切片/六态/双触保守/sell 平仓语义/R 与净R）" --no-verify
```

---

### Task 4: 市场微结构规则（跳空成交 + 停牌 + 一字板顺延 + prevClose 涨跌停价）

**Files:**
- Modify: `backend/plan_review.py`（replay_plan 循环内嵌微结构判定）
- Test: `tests/test_plan_review.py`（微结构段）

**Interfaces:**
- Consumes: Task 3 的 `replay_plan`/`slice_window`（`slice_window` 已返回 prev bar）。
- Produces: `replay_plan` 记录新增填充 `gapFill`/`limitDeferred`；`_board_pct(code) -> float`；`_limit_prices(prev_close, pct) -> tuple[float, float] | None`。签名不外泄（模块私有），Task 5 无感。

- [ ] **Step 1: 写失败测试**

```python
def test_gap_fill_stop_executes_at_open():
    # 跳空低开：open 9.2 < stop 9.5 → exit=open（更劣），R=(9.2-10)/0.5=-1.6，gapFill=True
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),
                      ("2026-09-15", 9.2, 9.1, 9.6, 9.0, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "loss" and rec["gapFill"] is True
    assert rec["rValue"] == -1.6 and rec["netR"] == -1.63

def test_gap_fill_target_executes_at_open():
    # 跳空高开：open 11.5 > target 11 → exit=open（更优），R=(11.5-10)/0.5=3.0，gapFill=True
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),
                      ("2026-09-15", 11.5, 11.6, 11.7, 11.2, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "win" and rec["gapFill"] is True and rec["rValue"] == 3.0

def test_suspended_day_skipped():
    # 09-14 触及 entry；09-15 停牌（volume 0）跳过；09-16 到 target → win
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),
                      ("2026-09-15", 10.1, 10.1, 10.1, 10.1, 0.0),
                      ("2026-09-16", 10.5, 11.2, 11.3, 10.4, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "win" and rec["exitDate"] == "2026-09-16"

def test_limit_up_one_price_defers_buy_entry():
    # 主板 10%：prevClose=10.0 → limitUp=11.0；09-14 一字涨停（high==low==11.0, vol>0）→ 买入入场顺延
    # 09-15 正常触及 entry → entryDate=09-15，limitDeferred=True
    bars = make_bars([("2026-09-11", 10.0, 10.0, 10.0, 10.0, 1000.0),  # prev bar（窗口前一根）
                      ("2026-09-14", 11.0, 11.0, 11.0, 11.0, 1000.0),  # 一字涨停
                      ("2026-09-15", 10.5, 10.6, 10.8, 9.8, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["entryDate"] == "2026-09-15" and rec["limitDeferred"] is True and rec["outcome"] == "flat"

def test_limit_down_one_price_defers_sell_exit():
    # buy 已入场后 09-15 一字跌停（limitDown=9.5*0.9=8.55? prevClose=9.6→8.64）→ 卖出离场顺延；
    # 09-16 low 9.0≤stop 9.5 → loss；limitDeferred=True
    bars = make_bars([("2026-09-11", 10.0, 10.0, 10.0, 10.0, 1000.0),
                      ("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),   # 入场
                      ("2026-09-15", 9.6, 9.6, 9.6, 9.6, 1000.0),      # 一字跌停（prevClose=10.1→limitDown=9.09；9.6>9.09 非一字跌停！）
                      ("2026-09-16", 9.0, 9.0, 9.2, 9.0, 1000.0)])
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    # ↑ 构造时先算 limitDown=round(10.1*0.9,2)=9.09；要让 09-15 成一字跌停需 close≤9.09 且 high==low。
    # 修正 fixture：09-15 open=high=low=close=9.05（<9.09 一字跌停）；09-16 low 9.0≤9.5 触发 loss。
    assert rec["outcome"] == "loss" and rec["limitDeferred"] is True
```

（第二个用例的数值修正过程保留在注释里——这是给实施者的示范：**一字板用例必须先手算 limitUp/limitDown 再造 bar**。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_plan_review.py -q --no-cov -k "gap or suspend or limit"`
Expected: FAIL（gapFill 恒 False / 一字板无顺延）

- [ ] **Step 3: 实现（在 Task 3 的 replay_plan 循环内改造）**

模块级新增：

```python
def _board_pct(code: str) -> float:
    """板块涨跌幅：北交所 30%、创业板/科创板 20%、其他 10%（AGENTS 涨跌幅纪律）。"""
    c = (code or "").zfill(6)
    if c[0] in "48" or c.startswith("92"):
        return 0.30
    if c.startswith(("300", "301", "688", "689")):
        return 0.20
    return 0.10


def _limit_prices(prev_close: float | None, pct: float) -> tuple[float, float] | None:
    if prev_close is None or prev_close <= 0:
        return None
    return round(prev_close * (1 + pct), 2), round(prev_close * (1 - pct), 2)
```

replay_plan 循环改造（完整替换 Task 3 的 for 循环体）：

```python
    prev_close = float(prev_bar["close"]) if prev_bar else None   # prev_bar 来自 slice_window
    for bar in window:
        low = float(bar["low"]); high = float(bar["high"]); open_ = float(bar["open"])
        volume = float(bar.get("volume") or 0)
        if volume <= 0:            # 停牌：无成交可能，prev_close 不更新
            continue
        limits = _limit_prices(prev_close, _board_pct(str(plan.get("code") or "")))
        one_price = high == low
        limit_up_day = bool(limits and one_price and close >= limits[0])
        limit_down_day = bool(limits and one_price and close <= limits[1])
        prev_close = float(bar["close"])
        if not entered:
            if limit_up_day:       # 涨停一字板：买入不可成交 → 顺延（决议 20）
                rec["limitDeferred"] = True
                continue
            if low <= entry:
                entered = True
                rec["entryDate"] = bar["date"]
            else:
                continue
        hit_stop = low <= stop
        hit_target = high >= target
        # 跳空成交模型：离场实际成交价
        exit_stop = open_ if open_ < stop else stop
        exit_target = open_ if open_ > target else target
        if (hit_stop or hit_target) and (exit_stop != stop or exit_target != target):
            rec["gapFill"] = True
        if hit_stop and hit_target:                     # 双触保守记败（决议 3）——跳空模型同样适用（评审 B2）
            exit_price = open_ if open_ < stop else stop
            rec.update(outcome="loss", rValue=r_of(exit_price), exitDate=bar["date"], ambiguous=True)
            return _finalize(rec)
        if hit_target:
            if limit_down_day:                          # 跌停一字板：卖出离场不可成交 → 顺延
                rec["limitDeferred"] = True
                continue
            rec.update(outcome="win", rValue=r_of(exit_target), exitDate=bar["date"])
            return _finalize(rec)
        if hit_stop:
            if limit_down_day:
                rec["limitDeferred"] = True
                continue
            rec["rValue"] = r_of(exit_stop)
            rec["outcome"] = "loss"
            rec["exitDate"] = bar["date"]
            return _finalize(rec)
```

（注意：循环开头需 `close = float(bar["close"])`；**三条 loss 路径（双触/单 stop）统一走 `r_of(exit_price)`**——无跳空时 `exit_price == stop` → R=−1 数值不变，跳空时 exit=open（更劣），Task 3 的 `-1.0` 字面量在 Task 4 全部消除；窗口闭合兜底 flat 的 exit=末收盘不变。）

补充测试（加进 Step 1 的微结构段）：

```python
def test_double_touch_with_gap_down_uses_open_exit():
    # 双触 + 跳空低开：open 9.2 < stop 9.5 → exit=9.2，R=(9.2-10)/0.5=-1.6（非 -1），ambiguous+gapFill
    bars = make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),   # 入场日
                      ("2026-09-15", 9.2, 9.3, 11.2, 9.0, 1000.0)])    # open<stop 且 low≤stop、high≥target
    rec = replay_plan(make_plan(), bars, 0.0015, today=TODAY)
    assert rec["outcome"] == "loss" and rec["ambiguous"] is True and rec["gapFill"] is True
    assert rec["rValue"] == -1.6
```

- [ ] **Step 4: 跑全量回放测试（Task 3 用例不得回归）**

Run: `python -m pytest tests/test_plan_review.py -q --no-cov -k "replay or gap or suspend or limit or slice"` → PASS

- [ ] **Step 5: 提交**

```bash
git add backend/plan_review.py tests/test_plan_review.py
git commit -m "feat: 回放引擎微结构——跳空成交价/停牌跳过/前收盘涨跌停一字板顺延" --no-verify
```

---

### Task 5: bars 批量获取 + 聚合编排 review_plans

**Files:**
- Modify: `backend/plan_review.py`（追加编排段）
- Modify: `backend/storage.py`（无改动——复用 `load_market_bars:583`/`save_market_bars:612`，import 使用）
- Test: `tests/test_plan_review.py`（编排段）

**Interfaces:**
- Consumes: Task 3/4 `replay_plan`；storage `load_market_bars(code, adjustment, limit)` / `save_market_bars(code, bars, adjustment)`；Task 2 bfq。
- Produces（Task 6 依赖，签名冻结）:
  - `class ReviewUpstreamError(Exception)`：`.codes: list[str]`（失败 code 列表，502 日志用）
  - `fetch_all_bars(codes: list[str], router) -> dict[str, list[dict]]`（DB 缓存 → 上游 `load_history(code, limit=300, is_index=False, adjustment="")` → `save_market_bars(adjustment="")`；末根 < 今天-7天 视为过期重取；任一失败累积后抛 ReviewUpstreamError）
  - `aggregate(records: list[dict]) -> dict`（→ `{"kpis": ..., "groups": ..., "items": sorted}`）
  - `review_plans(plans: list[dict], days: int, fee_rate: float, load_bars) -> dict`（load_bars 注入：`codes -> {code: bars}`；days=0 全部；createdAtMs 过滤 → fetch → replay → aggregate）

- [ ] **Step 1: 写失败测试**

```python
def test_aggregate_kpis_and_null_placeholders():
    recs = [
        {**_rec("win", 2.0, 0.03)}, {**_rec("win", 1.5, 0.03)},
        {**_rec("loss", -1.0, 0.03)}, {**_rec("flat", 0.2, 0.03)},
        {**_rec("notEntered", None, None)}, {**_rec("open", None, None)},
        {**_rec("invalid", None, None)},
    ]
    out = aggregate(recs)
    k = out["kpis"]
    # netR：win 1.97 / win 1.47 / loss -1.03 / flat 0.17（cost=0.03）
    assert k["total"] == 7 and k["decided"] == 3 and k["flatCount"] == 1
    assert k["winRate"] == 0.667                        # 2 胜 / 3 decided
    assert k["expectancyR"] == 0.645                    # (1.97+1.47-1.03+0.17)/4
    assert k["avgWinR"] == 1.72 and k["avgLossR"] == -1.03
    assert k["payoffRatio"] == 1.67                     # 1.72 / 1.03
    assert k["notEnteredRate"] == 0.2                   # 1 / (3+1+1)
    assert k["openCount"] == 1 and k["invalidCount"] == 1

def test_aggregate_null_when_no_losses():
    recs = [{**_rec("win", 2.0, 0.0)}, {**_rec("win", 1.0, 0.0)}]
    k = aggregate(recs)["kpis"]
    assert k["payoffRatio"] is None and k["avgLossR"] is None  # 败样本空 → null（绝不造数）

def test_groups_small_sample_flag():
    recs = [{**_rec("win", 2.0, 0.03), "source": "manual"}] * 3
    out = aggregate(recs)
    g = next(row for row in out["groups"]["source"] if row["key"] == "manual")
    assert g["smallSample"] is True and g["decided"] + g["flatCount"] < 5

def test_aggregate_excludes_null_netr_defensively():
    # 评审 B3：settled 记录 netR 为 None（回放异常）→ 显式剔除均值，绝不静默归零；计数仍按 outcome
    recs = [{**_rec("win", 2.0, 0.03)}, {**_rec("win", None, None)}, {**_rec("loss", -1.0, 0.03)}]
    k = aggregate(recs)["kpis"]
    assert k["decided"] == 2 and k["winRate"] == 1.0          # 计数按结局：2 胜 0 败
    assert k["avgWinR"] == 1.97                               # netR None 的 win 剔除后均值（非 (2.0+0)/2）
    assert k["expectancyR"] == round((1.97 - 1.03) / 2, 3)    # 0.47

def test_review_plans_days_filter_and_flow():
    plans = [make_plan(id="old", createdAtMs=1_700_000_000_000),   # 2023-11
             make_plan(id="new")]
    def fake_load_bars(codes):
        return {c: make_bars([("2026-09-14", 10.2, 10.1, 10.4, 9.8, 1000.0),
                              ("2026-09-15", 10.5, 11.2, 11.3, 10.4, 1000.0)]) for c in codes}
    out = review_plans(plans, days=90, fee_rate=0.0015, load_bars=fake_load_bars)
    ids = {i["planId"] for i in out["items"]}
    assert "new" in ids and "old" not in ids            # days=90 只留 createdAt 近 90 天
    out_all = review_plans(plans, days=0, fee_rate=0.0015, load_bars=fake_load_bars)
    assert {"old", "new"} <= {i["planId"] for i in out_all["items"]}

def test_fetch_all_bars_uses_db_cache_and_raises_on_failure(session_db, monkeypatch):
    # DB 命中：save 一份 bfq bars 后 fetch 不打上游
    bars = make_bars([("2026-09-14", 10, 10, 10, 10, 1000.0)])
    storage.save_market_bars("300750", bars, adjustment="")
    calls = []
    class FakeRouter:
        def load_history(self, code, limit, is_index=False, adjustment="qfq"):
            calls.append(code); return []
    out = fetch_all_bars(["300750"], FakeRouter())
    assert out["300750"][0]["date"] == "2026-09-14" and calls == []
    # 上游失败：无缓存 code 抛 ReviewUpstreamError 且 codes 齐全
    class BadRouter:
        def load_history(self, code, limit, is_index=False, adjustment="qfq"):
            raise RuntimeError("upstream down")
    with pytest.raises(ReviewUpstreamError) as ei:
        fetch_all_bars(["600519", "000001"], BadRouter())
    assert sorted(ei.value.codes) == ["000001", "600519"]

def _rec(outcome, r, cost):
    return {"planId": "x", "code": "300750", "source": "manual", "direction": "buy",
            "entry": 10.0, "stop": 9.5, "target": 11.0, "validity": "本月内",
            "status": "执行中", "outcome": outcome, "rValue": r, "netR": None if r is None else round(r - (cost or 0), 3),
            "costR": cost, "entryDate": None, "exitDate": None,
            "ambiguous": False, "gapFill": False, "limitDeferred": False}
```

（`expectancyR` 断言的数值：netR 依 `_rec` 的 cost=0.03：win 2.0→1.97、win 1.5→1.47、loss −1.0→−1.03、flat 0.2→0.17。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_plan_review.py -q --no-cov -k "aggregate or review_plans or fetch_all"`
Expected: FAIL（函数未定义）

- [ ] **Step 3: 实现（plan_review.py 追加）**

```python
DEFAULT_FEE_RATE = 0.0015
_BARS_LIMIT = 300
_STALE_DAYS = 7


class ReviewUpstreamError(Exception):
    def __init__(self, codes: list[str]) -> None:
        super().__init__(f"history fetch failed for {len(codes)} code(s)")
        self.codes = codes


def fetch_all_bars(codes: list[str], router) -> dict[str, list[dict[str, Any]]]:
    """唯一 code 去重预取：DB bfq 缓存优先，缺口/过期走上游并落缓存；失败累积抛错。"""
    from backend import storage  # 局部导入避免环

    today = shanghai_date_str(int(datetime.now(SHANGHAI).timestamp() * 1000))
    # stale 阈值 7 天是"缓存够新"的粗判：即使计划窗口截止日较早（不需要最新 bar），也统一重取——
    # 简单优先；窗口截断由 slice_window 负责，多取无害（评审非 Blocker ②，注释为证）。
    stale_before = (datetime.now(SHANGHAI) - timedelta(days=_STALE_DAYS)).strftime("%Y-%m-%d")
    out: dict[str, list[dict[str, Any]]] = {}
    failed: list[str] = []
    for code in dict.fromkeys(codes):
        try:
            bars = storage.load_market_bars(code, adjustment="", limit=_BARS_LIMIT) or []
            if not bars or str(bars[-1]["date"]) < stale_before:
                fresh = router.load_history(code, limit=_BARS_LIMIT, is_index=False, adjustment="")
                if fresh:
                    storage.save_market_bars(code, fresh, adjustment="")
                    bars = fresh
            out[code] = sorted(bars, key=lambda b: b["date"])
        except Exception:  # noqa: BLE001 —— 任一 code 失败不阻断其他 code 的拉取，最后统一抛
            failed.append(code)
    if failed:
        raise ReviewUpstreamError(failed)
    return out


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 3) if values else None


def aggregate(records: list[dict[str, Any]]) -> dict[str, Any]:
    wins = [r for r in records if r["outcome"] == "win"]
    losses = [r for r in records if r["outcome"] == "loss"]
    flats = [r for r in records if r["outcome"] == "flat"]
    decided = wins + losses
    settled = decided + flats
    not_entered = [r for r in records if r["outcome"] == "notEntered"]
    opens = [r for r in records if r["outcome"] == "open"]
    invalids = [r for r in records if r["outcome"] == "invalid"]

    def _nets(rows: list[dict[str, Any]]) -> list[float]:
        # None 显式剔除（评审 B3）——绝不静默归零污染均值；计数仍按 outcome（winRate 与 netR 有无无关）
        return [float(r["netR"]) for r in rows if r.get("netR") is not None]

    avg_win = _mean(_nets(wins))
    avg_loss = _mean(_nets(losses))
    payoff = round(avg_win / abs(avg_loss), 3) if (avg_win is not None and avg_loss) else None
    denom_ne = len(decided) + len(flats) + len(not_entered)
    kpis = {
        "total": len(records), "decided": len(decided), "flatCount": len(flats),
        "winRate": round(len(wins) / len(decided), 3) if decided else None,
        "avgWinR": avg_win, "avgLossR": avg_loss, "payoffRatio": payoff,
        "expectancyR": _mean(_nets(settled)),
        "notEnteredRate": round(len(not_entered) / denom_ne, 3) if denom_ne else None,
        "openCount": len(opens), "invalidCount": len(invalids),
    }

    def group_rows(key_fn, label_fn) -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = {}
        for r in records:
            buckets.setdefault(key_fn(r), []).append(r)
        rows = []
        for key in sorted(buckets):
            g = aggregate_min(buckets[key])
            rows.append({"key": key, "label": label_fn(key), **g})
        return rows

    months = sorted({r.get("createdMonth") or "" for r in records} - {""})
    month_labels = {m: m for m in months}
    groups = {
        "source": group_rows(lambda r: r.get("source") or "legacy",
                             lambda k: {"legacy": "早期计划", "manual": "手动新建",
                                        "screener": "策略命中", "monitor": "盯盘信号"}.get(k, k)),
        "direction": group_rows(lambda r: r.get("direction") or "buy",
                                lambda k: {"buy": "买入", "sell": "卖出（平仓）"}.get(k, k)),
        "validity": group_rows(lambda r: r.get("validity") or "未知", lambda k: k),
        "createdMonth": group_rows(lambda r: r.get("createdMonth") or "未知", lambda k: month_labels.get(k, k)),
    }
    items = sorted(records, key=lambda r: str(r.get("planId")), reverse=True)  # createdAt 排序在 review_plans 里做
    return {"kpis": kpis, "groups": groups, "items": items}


def aggregate_min(records: list[dict[str, Any]]) -> dict[str, Any]:
    """分组行：decided/flatCount/wins/winRate/expectancyR/smallSample（分母口径与 kpis 一致）。"""
    wins = [r for r in records if r["outcome"] == "win"]
    losses = [r for r in records if r["outcome"] == "loss"]
    flats = [r for r in records if r["outcome"] == "flat"]
    decided = wins + losses
    settled = decided + flats
    nets = lambda rows: [float(r["netR"]) for r in rows if r.get("netR") is not None]  # None 剔除（评审 B3）
    avg_loss = _mean(nets(losses))
    avg_win = _mean(nets(wins))
    return {
        "decided": len(decided), "flatCount": len(flats), "wins": len(wins),
        "winRate": round(len(wins) / len(decided), 3) if decided else None,
        "expectancyR": _mean(nets(settled)),
        "payoffRatio": None,  # 分组行不含 payoff（YAGNI；明细看 kpis）
        "smallSample": (len(decided) + len(flats)) < 5,
    }


def review_plans(plans: list[dict[str, Any]], days: int, fee_rate: float,
                 load_bars) -> dict[str, Any]:
    from datetime import datetime as _dt
    now_ms = int(_dt.now(SHANGHAI).timestamp() * 1000)
    min_created = 0 if days == 0 else now_ms - days * 86_400_000
    scoped = [p for p in plans if int(p.get("createdAtMs") or 0) >= min_created]
    codes = sorted({str(p.get("code")) for p in scoped if p.get("code")})
    bars_map = load_bars(codes) if codes else {}
    records = []
    for p in scoped:
        rec = replay_plan(p, bars_map.get(str(p.get("code")) or "", []), fee_rate)
        rec["createdMonth"] = shanghai_date_str(int(p.get("createdAtMs") or 0))[:7]
        rec["_createdAtMs"] = int(p.get("createdAtMs") or 0)
        records.append(rec)
    out = aggregate(records)
    out["items"] = sorted(records, key=lambda r: r["_createdAtMs"], reverse=True)
    for r in out["items"]:
        r.pop("_createdAtMs", None)
    return out
```

（`aggregate` 里 items 的二级排序键用 `_createdAtMs` 由 review_plans 处理——aggregate 单测直接调用时不带 `_createdAtMs`，排序退化为 planId，无碍。）

- [ ] **Step 4: 跑测试确认通过**

Run: `python -m pytest tests/test_plan_review.py -q --no-cov` → PASS（全文件）

- [ ] **Step 5: 提交**

```bash
git add backend/plan_review.py tests/test_plan_review.py
git commit -m "feat: 复盘编排——bars 双层缓存批量预取/聚合 kpis 四维分组/null 兜底" --no-verify
```

---

### Task 6: API 端点（GET /api/plans/review + GET /api/screener/scan/history）

**Files:**
- Modify: `backend/app.py`（scan 路由附近追加两个只读端点；grep `@app.get("/api/screener/scan/hits")` 定位插入点）
- Test: `tests/test_plan_review.py`（端点段；复用 test_scan.py 的 FastAPI TestClient 模式——grep `TestClient` 该文件头 40 行对齐 fixture）

**Interfaces:**
- Consumes: Task 5 `review_plans`/`ReviewUpstreamError`/`DEFAULT_FEE_RATE`；storage `list_plans`（get_workspace 内 plans；直接 `storage.get_workspace()["plans"]`，补 `createdAtMs`——`_plan_dict` 已含）、`list_scan_history(strategy_id, limit)`（storage.py:872，返回行 → camelCase 映射仿 `_scan_config_out`）。
- Produces:
  - `GET /api/plans/review?days=30|90|0&feeRate=` → 200 `{kpis, groups, items}` 顶层键；422（days ∉ {0,30,90} 或 feeRate ∉ [0,0.05]，detail 含 `ERR_VALIDATION_ERROR`）；502（`ReviewUpstreamError`，detail `ERR_UPSTREAM_UNAVAILABLE`，日志含失败 codes）。
  - `GET /api/screener/scan/history?strategyId=&limit=` → 200 `{"history": [...]}`（limit 默认 30，1..200 夹取）。

- [ ] **Step 1: 写失败测试**

```python
import logging

from fastapi.testclient import TestClient

from backend.app import app

client = TestClient(app)  # 模块级共享；各用例自 monkeypatch，互不残留


def test_review_endpoint_happy_path(monkeypatch):
    plans = [make_plan(id="p1"), make_plan(id="p2", source="scan:trend_breakout")]
    monkeypatch.setattr("backend.app.storage.get_workspace", lambda *a, **k: {"plans": plans})
    monkeypatch.setattr("backend.plan_review.review_plans",
                        lambda ps, days, fee_rate, **k: {"kpis": {"total": len(ps)}, "groups": {}, "items": []})
    r = client.get("/api/plans/review", params={"days": 90})
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"kpis", "groups", "items"} and body["kpis"]["total"] == 2
    # feeRate 以字符串数值传入 → FastAPI float 解析兼容（评审遗留观察）
    ok = client.get("/api/plans/review", params={"days": 0, "feeRate": "0.002"})
    assert ok.status_code == 200


def test_review_endpoint_422_days_and_feerate(monkeypatch):
    monkeypatch.setattr("backend.plan_review.review_plans", lambda *a, **k: {})  # 422 在调用前返回，不触达
    assert client.get("/api/plans/review", params={"days": 45}).status_code == 422
    assert client.get("/api/plans/review", params={"days": 90, "feeRate": 0.9}).status_code == 422
    assert client.get("/api/plans/review", params={"days": 90, "feeRate": -0.1}).status_code == 422


def test_review_endpoint_502_logs_failed_codes(monkeypatch, caplog):
    from backend.plan_review import ReviewUpstreamError

    def boom(plans, days, fee_rate, **k):
        raise ReviewUpstreamError(["600519", "000001"])

    caplog.set_level(logging.ERROR)
    monkeypatch.setattr("backend.app.storage.get_workspace", lambda *a, **k: {"plans": []})
    monkeypatch.setattr("backend.plan_review.review_plans", boom)
    r = client.get("/api/plans/review")
    assert r.status_code == 502
    assert "600519" in caplog.text and "000001" in caplog.text   # 失败 code 落日志（r3.1）


def test_scan_history_endpoint(monkeypatch):
    rows = [{"strategy_id": "trend_breakout", "run_at_ms": 1_789_000_000_000, "status": "ok",
             "hit_count": 3, "new_count": 1, "elapsed_ms": 1200, "trace_id": "t1", "mode": "quick"}]
    monkeypatch.setattr("backend.app.storage.list_scan_history", lambda strategy_id=None, limit=50: rows)
    r = client.get("/api/screener/scan/history", params={"strategyId": "trend_breakout"})
    assert r.status_code == 200
    body = r.json()["history"][0]
    assert body["hitCount"] == 3 and body["strategyId"] == "trend_breakout"   # camelCase 出参
```

（patch 目标统一 `"backend.plan_review.review_plans"`——app.py 用 `from backend import plan_review` 属性访问；`storage.get_workspace` 的 plans 行形状以 `_plan_dict` 实际输出为准。`list_scan_history` 返回行的真实键名以 storage.py:872 实现为准——上面 fake 行按 snake_case 假设，若实际是 camelCase 则 `_scan_history_out` 映射相应简化。）

- [ ] **Step 2: 跑测试确认失败**

Run: `python -m pytest tests/test_plan_review.py -q --no-cov -k endpoint`
Expected: FAIL（404 Not Found）

- [ ] **Step 3: 实现（app.py 追加，紧邻既有 scan 路由）**

```python
@app.get("/api/plans/review")
def plans_review(days: int = 90, feeRate: float = plan_review.DEFAULT_FEE_RATE) -> dict[str, Any]:
    """计划绩效复盘（只读，设计口径回算；红线：零写 plans）。"""
    if days not in (0, 30, 90):
        raise HTTPException(status_code=422, detail={"code": "ERR_VALIDATION_ERROR", "message": "days 仅支持 0/30/90"})
    if not (0.0 <= feeRate <= 0.05):
        raise HTTPException(status_code=422, detail={"code": "ERR_VALIDATION_ERROR", "message": "feeRate 须在 [0, 0.05]"})
    plans = storage.get_workspace().get("plans") or []
    try:
        return plan_review.review_plans(plans, days=days, fee_rate=float(feeRate),
                                        load_bars=lambda codes: plan_review.fetch_all_bars(codes, router))
    except plan_review.ReviewUpstreamError as exc:
        logger.error("review_upstream_failed codes=%s", exc.codes)   # logger=atlas.review；失败 code 进消息串
        raise HTTPException(status_code=502, detail={"code": "ERR_UPSTREAM_UNAVAILABLE",
                                                     "message": "历史行情拉取失败",
                                                     "failedCodes": exc.codes}) from exc


@app.get("/api/screener/scan/history")
def scan_history(strategyId: str | None = None, limit: int = 30) -> dict[str, Any]:
    limit = max(1, min(int(limit), 200))
    rows = storage.list_scan_history(strategy_id=strategyId or None, limit=limit)
    return {"history": [_scan_history_out(r) for r in rows]}


def _scan_history_out(row: dict[str, Any]) -> dict[str, Any]:
    return {"strategyId": row.get("strategy_id"), "runAtMs": row.get("run_at_ms"),
            "status": row.get("status"), "hitCount": row.get("hit_count"),
            "newCount": row.get("new_count"), "elapsedMs": row.get("elapsed_ms"),
            "traceId": row.get("trace_id"), "mode": row.get("mode")}
```

适配要点（实现者现场核对后落笔）：
- import 方式：app.py 头部 `from backend import plan_review` + `logger = logging.getLogger("atlas.review")`（app.py 已有 logging 惯例，grep `logging.getLogger` 对齐格式；extra 键名遵循 scan 的 `screener.scan` 风格）。
- `router` 为 app.py 既有 DataSourceRouter 实例（grep `router = ` 确认变量名，替换示例中的 `router`）。
- `storage.list_scan_history` 返回行形状以 storage.py:872 实际字段为准（可能是 dict 或含 snake_case 键；`_scan_history_out` 按实际字段改写映射，保持 camelCase 出参）。
- `get_workspace()` 的 plans 行即 `_plan_dict` 输出，**`createdAtMs` 已含**（storage.py:288 `int(plan.created_at.timestamp() * 1000)`，探现场时已核验——评审 B4 关闭，无需补齐；source 由 Task 1 加入后同样经此输出）。
- 422 detail 结构与 scan 端点既有 `ERR_VALIDATION_ERROR` 用法保持同构（grep `ERR_VALIDATION_ERROR` app.py）。

- [ ] **Step 4: 跑测试确认通过 + 后端全量回归**

Run: `python -m pytest tests/test_plan_review.py -q --no-cov -k endpoint` → PASS
Run: `python -m pytest tests/ -q --no-cov` → 全绿（340+ 新增）

- [ ] **Step 5: 提交**

```bash
git add backend/app.py tests/test_plan_review.py
git commit -m "feat: 复盘只读端点（plans/review 聚合 + scan/history 留痕，422/502 语义）" --no-verify
```

---

### Task 7: source 前端链路（openFor → PlanDraftDialog → 计划落库 + 各入口标签）

**Files:**
- Modify: `frontend/src/stores/useAssistStore.ts`（openFor 输入类型 + source 透传，~line 57 起）
- Modify: `frontend/src/components/PlanDraftDialog.vue`（source 接收 + 确认写入 + 口径提示行）
- Modify: `frontend/src/App.vue`（openScanDraft ~line 313 传 `scan:{strategyId}`）
- Modify: `frontend/src/views/ViewScreener.vue`（命中行草案入口传 `screener`）
- Modify: `frontend/src/views/ViewMonitor.vue` / `ViewStockDetail.vue`（盯盘/详情草案入口传 `monitor`——grep `openFor(` 全仓定位实际调用点）
- Modify: `frontend/src/views/ViewPlans.vue`（手动新建传 `manual`）
- Modify: `frontend/src/stores/usePlansStore.ts` 或 `useWorkspaceStore.ts`（计划对象构造处带 source——grep `createPlan\|plans.push` 定位）
- Test: `tests/frontend/useAlertsStore.test.ts`（既有 chip 用例扩展 source 断言）+ `tests/frontend/useAssistStore.test.ts`（若存在；否则 grep tests/frontend/ 找 openFor 现有覆盖文件）

**Interfaces:**
- Consumes: Task 1 `Plan.source?: string`。
- Produces: `openFor(input: AssistOpenInput)` 其中 `AssistOpenInput = { code: string; name?: string; price?: number; asOfMs?: number; source?: string }`（在既有输入类型上加可选 `source`）；确认落计划的计划对象含 `source: <string>`；四入口字面量：`scan:${strategyId}` / `'screener'` / `'monitor'` / `'manual'`。Task 8 无感（只读端）。

- [ ] **Step 1: 写失败测试**

```ts
// tests/frontend/useAlertsStore.test.ts —— 既有 alert-code-chip 用例的 openFor 断言升级：
// 旧：expect(openFor).toHaveBeenCalledWith(expect.objectContaining({ code: '300750' }))
// 新：
expect(openForSpy).toHaveBeenCalledWith(
  expect.objectContaining({ code: '300750', source: 'scan:trend_breakout' })
);
```

新增（放入同一文件或 useAssistStore 对应测试文件，mock 模式照抄该文件既有 `vi.mock('@/api/client')` 写法）：

```ts
it('confirmDraft 落计划携带 source 并显示口径提示', async () => {
  // 1) openFor({ code, source: 'scan:trend_breakout' }) 后 PlanDraftDialog 的 source ref === 'scan:trend_breakout'
  // 2) 提示行文案存在：「K 线图为前复权价，请勿直接照抄图表价位」（data-testid="draft-price-scope-note"）
  // 3) 确认按钮触发的计划对象断言 source —— spy workspace store 的计划创建函数
});
```

（断言体按被测组件实际暴露补齐：挂载 PlanDraftDialog，注入 source 后触发确认，spy 计划创建调用参数。测试写法以 tests/frontend/ 既有 PlanDraftDialog 或 ViewScreener 测试的挂载/mock 模式为准——grep `PlanDraftDialog` tests/frontend/ 找现有文件。）

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run tests/frontend/useAlertsStore.test.ts`
Expected: FAIL（source 未传）

- [ ] **Step 3: 实现**

1. `useAssistStore.ts`：openFor 输入类型加 `source?: string`；openFor 存入组件可见的 draft 状态（与 code/name 同路：grep `openFor` 函数体，把 source 写进 dialog 输入对象）；`confirmDraft`/落计划调用处把 source 透传给计划创建函数。
2. `PlanDraftDialog.vue`：**source 与 code 走完全相同的通路**（评审 B6）——先 grep 该文件中 `code` 的到达路径（`grep -n "code" frontend/src/components/PlanDraftDialog.vue | head -30`）：若经 `useAssistStore()` 的 draft/recalc 状态读取，则在该状态对象加 `source?: string`，openFor 写入、对话框同源读取；若经 props 传入，则加同名可选 prop。**禁止旁路**（不允许 source 独立于 code 的第二通道）。确认回调把 source 带入计划对象（构造点统一兜底 `|| 'manual'`）。模板加口径提示行（放入场输入框附近）：

```html
<p class="field-hint" data-testid="draft-price-scope-note">计划价格以原始实时价为准；K 线图为前复权价，请勿直接照抄图表价位。</p>
```
3. 计划对象构造处（grep `createPlan\|plans.push\|plans = [` 定位唯一构造点）：`source: <来源变量> || 'manual'`——手动新建入口无 source 时兜底 `manual`。
4. 各入口传值：
   - `App.vue` openScanDraft：`assist.openFor({ code: item.code, source: \`scan:${item.strategyId}\` })`
   - ViewScreener 命中行草案按钮：`source: 'screener'`
   - ViewMonitor / ViewStockDetail 草案入口：`source: 'monitor'`
   - ViewPlans 手动新建：不传（构造处兜底 manual）
   - grep `openFor(` 全仓列出全部调用点逐一核对，报告贴清单。

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run tests/frontend/` → 全绿（既有 openFor 调用者不受影响：source 可选）

- [ ] **Step 5: 提交**

```bash
git add frontend/src/ tests/frontend/
git commit -m "feat: 计划来源归因前端链路——openFor/草案对话框/四入口标签/口径提示" --no-verify
```

---

### Task 8: 绩效 UI（useReviewStore + ViewPlans 折叠面板）

**Files:**
- Create: `frontend/src/stores/useReviewStore.ts`
- Modify: `frontend/src/views/ViewPlans.vue`（计划列表下方追加折叠面板；模板 + script）
- Modify: `frontend/src/App.vue`（store 无需注册——Pinia 直接 use；若 app.ts 有 store 清单惯例则同步，grep `useScanStore` in app.ts/App.vue 判断）
- Modify: `AGENTS.md`（store 计数 10→11 等——**放 Task 9**，本任务不动 docs）
- Test: `tests/frontend/useReviewStore.test.ts`（新建）+ `tests/frontend/ViewPlans.test.ts`（存在则扩展，不存在则新建——mock 模式照抄 ViewScreener.test.ts：`vi.mock('@/api/client', async (importOriginal) => ({ ...await importOriginal(), requestJson: vi.fn() }))`）

**Interfaces:**
- Consumes: Task 6 端点形状（`{kpis, groups, items}`；`GET /api/plans/review?days=`）；`requestJson`（`@/api/client` named export）。
- Produces: `useReviewStore()` → `{ review, loading, days, activeGroup, expanded, sortKey, sortDir, trace, traceLoading, fetchReview(days?), toggle(), setGroup(key), setDays(d), toggleSort(key), fetchTrace(strategyId), formatRatio(v), formatR(v) }`（评审 B5：trace 状态与方法进 store；明细排序状态 `sortKey: 'netR'|'outcome'|null` + `sortDir`）；testids：`review-toggle`/`review-kpis`/`review-group-tab`/`review-items`/`review-trace`/`review-disclaimer`/`review-fee-note`。

- [ ] **Step 1: 写失败测试**

```ts
// tests/frontend/useReviewStore.test.ts
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';

const requestJson = vi.fn();
vi.mock('@/api/client', async (importOriginal) => ({
  ...(await importOriginal<any>()),
  requestJson: (...a: unknown[]) => requestJson(...a),
}));

import { useReviewStore } from '@/stores/useReviewStore';

const payload = {
  kpis: { total: 2, decided: 1, flatCount: 0, winRate: 1, avgWinR: 1.97, avgLossR: null,
          payoffRatio: null, expectancyR: 1.97, notEnteredRate: 0, openCount: 1, invalidCount: 0 },
  groups: { source: [{ key: 'manual', label: '手动新建', decided: 1, flatCount: 0, wins: 1,
                       winRate: 1, expectancyR: 1.97, smallSample: true }] },
  items: [{ planId: 'p1', code: '300750', source: 'manual', direction: 'buy', entry: 10,
            stop: 9.5, target: 11, validity: '本月内', status: '执行中', outcome: 'win',
            rValue: 2, netR: 1.97, costR: 0.03, entryDate: '2026-09-14', exitDate: '2026-09-15',
            ambiguous: false, gapFill: false, limitDeferred: false }],
};

describe('useReviewStore', () => {
  beforeEach(() => { setActivePinia(createPinia()); requestJson.mockReset(); });

  it('fetchReview 请求 /api/plans/review 并存 review', async () => {
    requestJson.mockResolvedValue(payload);
    const s = useReviewStore();
    await s.fetchReview(90);
    expect(requestJson.mock.calls[0]?.[0]).toContain('/api/plans/review?days=90');
    expect(s.review?.kpis.total).toBe(2);
  });

  it('null 指标渲染占位 --（payoffRatio null 不造数）', async () => {
    requestJson.mockResolvedValue(payload);
    const s = useReviewStore();
    await s.fetchReview(90);
    expect(s.formatRatio(s.review?.kpis.payoffRatio)).toBe('--');
  });

  it('来源分组含 scan: 行时自动拉取留痕（评审 B5）', async () => {
    const withScan = { ...payload,
      groups: { ...payload.groups,
        source: [{ key: 'scan:trend_breakout', label: '扫描·趋势突破', decided: 1, flatCount: 0,
                   wins: 1, winRate: 1, expectancyR: 1.97, smallSample: true }] } };
    requestJson.mockImplementation((url: string) => {
      if (String(url).includes('/api/plans/review')) return Promise.resolve(withScan);
      if (String(url).includes('/api/screener/scan/history')) {
        return Promise.resolve({ history: [{ strategyId: 'trend_breakout', runAtMs: 1_789_000_000_000,
          status: 'ok', hitCount: 3, newCount: 1, elapsedMs: 1200, traceId: 't1', mode: 'quick' }] });
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });
    const s = useReviewStore();
    await s.fetchReview(90);
    expect(s.trace?.[0]?.hitCount).toBe(3);        // fetchReview → syncTrace → fetchTrace 自动触发
    expect(requestJson.mock.calls.some((c) => String(c[0]).includes('/api/screener/scan/history?strategyId=trend_breakout'))).toBe(true);
    await s.setGroup('direction');                  // 切走 → trace 清空
    expect(s.trace).toBeNull();
  });
});
```

组件测试（ViewPlans.test.ts 新建/扩展，断言展开即拉取 + testids + 角标）：

```ts
it('展开绩效面板时首次拉取并渲染 testids', async () => {
  requestJson.mockResolvedValue(payload);
  const wrapper = mountViewPlans();               // 按 ViewScreener.test.ts 的挂载工厂
  await wrapper.find('[data-testid="review-toggle"]').trigger('click');
  await flushPromises();
  expect(requestJson.mock.calls.some((c) => String(c[0]).includes('/api/plans/review'))).toBe(true);
  expect(wrapper.find('[data-testid="review-kpis"]').exists()).toBe(true);
  expect(wrapper.find('[data-testid="review-disclaimer"]').text()).toContain('不构成投资建议');
  expect(wrapper.find('[data-testid="review-fee-note"]').exists()).toBe(true);
  expect(wrapper.find('[data-testid="review-items"]').exists()).toBe(true);
});

it('分组 Tab 切换与 smallSample 徽标', async () => {
  // 展开 → 找 [data-testid="review-group-tab"]（≥4 个）→ 点「来源」外的另一个 → 行仍渲染
  // smallSample=true 的分组行含「样本不足，仅供参考」文案
});
```

- [ ] **Step 2: 跑测试确认失败**

Run: `npx vitest run tests/frontend/useReviewStore.test.ts`
Expected: FAIL（store 不存在）

- [ ] **Step 3: 实现**

`frontend/src/stores/useReviewStore.ts`：

```ts
import { defineStore } from 'pinia';
import { ref } from 'vue';
import { requestJson } from '@/api/client';

export interface ReviewKpis {
  total: number; decided: number; flatCount: number; winRate: number | null;
  avgWinR: number | null; avgLossR: number | null; payoffRatio: number | null;
  expectancyR: number | null; notEnteredRate: number | null; openCount: number; invalidCount: number;
}
export interface ReviewGroupRow {
  key: string; label: string; decided: number; flatCount: number; wins: number;
  winRate: number | null; expectancyR: number | null; smallSample: boolean;
}
export interface ReviewItem {
  planId: string; code: string; source: string; direction: string;
  entry: number; stop: number; target: number; validity: string; status: string;
  outcome: 'win' | 'loss' | 'flat' | 'notEntered' | 'open' | 'invalid';
  rValue: number | null; netR: number | null; costR: number | null;
  entryDate: string | null; exitDate: string | null;
  ambiguous: boolean; gapFill: boolean; limitDeferred: boolean;
}
export interface ReviewPayload {
  kpis: ReviewKpis;
  groups: { source: ReviewGroupRow[]; direction: ReviewGroupRow[]; validity: ReviewGroupRow[]; createdMonth: ReviewGroupRow[] };
  items: ReviewItem[];
}

export interface ScanTraceRow {
  strategyId: string; runAtMs: number; status: string; hitCount: number;
  newCount: number; elapsedMs: number; traceId: string; mode: string;
}

export const useReviewStore = defineStore('review', () => {
  const review = ref<ReviewPayload | null>(null);
  const loading = ref(false);
  const days = ref<0 | 30 | 90>(90);
  const activeGroup = ref<'source' | 'direction' | 'validity' | 'createdMonth'>('source');
  const expanded = ref(false);
  const fetchedOnce = ref(false);
  const sortKey = ref<'netR' | 'outcome' | null>(null);
  const sortDir = ref<'asc' | 'desc'>('desc');
  const trace = ref<ScanTraceRow[] | null>(null);
  const traceLoading = ref(false);

  async function fetchReview(d?: 0 | 30 | 90) {
    if (d !== undefined) days.value = d;
    loading.value = true;
    try {
      review.value = await requestJson(`/api/plans/review?days=${days.value}`, { method: 'GET' });
      fetchedOnce.value = true;
      void syncTrace();
    } finally {
      loading.value = false;
    }
  }
  async function toggle() {
    expanded.value = !expanded.value;
    if (expanded.value && !fetchedOnce.value) await fetchReview();
  }
  function toggleSort(key: 'netR' | 'outcome') {
    if (sortKey.value === key) sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc';
    else { sortKey.value = key; sortDir.value = 'desc'; }
  }
  async function fetchTrace(strategyId: string) {
    traceLoading.value = true;
    try {
      const res = await requestJson<{ history: ScanTraceRow[] }>(
        `/api/screener/scan/history?strategyId=${encodeURIComponent(strategyId)}&limit=30`, { method: 'GET' });
      trace.value = res.history;
    } finally {
      traceLoading.value = false;
    }
  }
  function syncTrace() {
    // 来源分组下存在 scan:{strategyId} 行时自动拉取该策略近 30 天留痕（评审 B5）
    if (activeGroup.value !== 'source') { trace.value = null; return; }
    const row = (review.value?.groups.source ?? []).find((r) => r.key.startsWith('scan:'));
    if (row) void fetchTrace(row.key.slice(5));
    else trace.value = null;
  }
  function setGroup(k: typeof activeGroup.value) {
    activeGroup.value = k;
    syncTrace();
  }
  function formatRatio(v: number | null | undefined): string {
    return v === null || v === undefined ? '--' : `${(v * 100).toFixed(1)}%`;
  }
  function formatR(v: number | null | undefined): string {
    return v === null || v === undefined ? '--' : v.toFixed(2);
  }
  return { review, loading, days, activeGroup, expanded, sortKey, sortDir, trace, traceLoading,
           fetchReview, toggle, setGroup, setDays: fetchReview, toggleSort, fetchTrace, formatRatio, formatR };
});
```

（`requestJson` 的调用签名以 `@/api/client` 实际导出为准——grep `export function requestJson\|export const requestJson` 对齐参数形状；扫描功能已有 `import { requestJson } from '@/api/client'` 先例（useScanStore.ts），照抄其调用方式。）

`ViewPlans.vue` 追加（计划列表 section 之后）：

```html
<section class="panel review-panel">
  <button class="review-toggle" data-testid="review-toggle" type="button" @click="review.toggle()">
    <span>绩效复盘</span>
    <span v-if="review.review" class="muted">{{ reviewSummary }}</span>
    <i data-lucide="chevron-down" :class="{ flipped: review.expanded }"></i>
  </button>
  <template v-if="review.expanded">
    <div class="review-days">
      <button v-for="d in [30, 90, 0]" :key="d" type="button"
              :class="{ active: review.days === d }" @click="review.setDays(d)">
        {{ d === 0 ? '全部' : `近 ${d} 天` }}
      </button>
    </div>
    <div class="review-kpis" data-testid="review-kpis">
      <div class="kpi"><b>{{ review.review?.kpis.total ?? '--' }}</b><span>计划总数</span></div>
      <div class="kpi"><b>{{ review.formatRatio(review.review?.kpis.winRate) }}</b><span>胜率</span></div>
      <div class="kpi"><b>{{ review.formatR(review.review?.kpis.payoffRatio) }}</b><span>盈亏比</span></div>
      <div class="kpi"><b>{{ review.formatR(review.review?.kpis.expectancyR) }}</b><span>期望值 R</span></div>
      <div class="kpi"><b>{{ review.formatRatio(review.review?.kpis.notEnteredRate) }}</b><span>未入场率</span></div>
      <div class="kpi"><b>{{ review.review?.kpis.openCount ?? '--' }}</b><span>进行中</span></div>
      <span class="kpi-note" data-testid="review-fee-note">成本假设（可调，参考范围 0.1%–0.5%）：feeRate × 入场 ÷ 止损距离，近似值</span>
    </div>
    <div class="review-tabs">
      <button v-for="g in GROUPS" :key="g.key" data-testid="review-group-tab" type="button"
              :class="{ active: review.activeGroup === g.key }" @click="review.setGroup(g.key)">{{ g.label }}</button>
    </div>
    <table class="review-table" data-testid="review-items">
      <thead><tr><th>分组</th><th>已决</th><th>胜</th><th>胜率</th><th>期望 R</th></tr></thead>
      <tbody>
        <tr v-for="row in activeRows" :key="row.key">
          <td>{{ row.label }} <span v-if="row.smallSample" class="badge-muted">样本不足，仅供参考</span></td>
          <td>{{ row.decided }}</td><td>{{ row.wins }}</td>
          <td>{{ review.formatRatio(row.winRate) }}</td>
          <td>{{ review.formatR(row.expectancyR) }}</td>
        </tr>
      </tbody>
    </table>
    <table class="review-table" data-testid="review-items-detail">
      <thead><tr><th>代码</th><th>来源</th><th><button type="button" @click="review.toggleSort('outcome')">结局</button></th><th><button type="button" @click="review.toggleSort('netR')">净 R</button></th><th>入场日</th><th>离场日</th></tr></thead>
      <tbody>
        <tr v-for="item in sortedDetail" :key="item.planId">
          <td>{{ item.code }}</td><td>{{ sourceLabel(item.source) }}</td>
          <td>{{ outcomeLabel(item) }}<span v-if="item.ambiguous" class="badge-muted">保守裁定</span><span v-if="item.gapFill" class="badge-muted">跳空</span><span v-if="item.limitDeferred" class="badge-muted">顺延</span></td>
          <td>{{ review.formatR(item.netR) }}</td><td>{{ item.entryDate ?? '--' }}</td><td>{{ item.exitDate ?? '--' }}</td>
        </tr>
      </tbody>
    </table>
    <div v-if="activeScanTrace.length" data-testid="review-trace" class="review-trace">
      <p class="muted">{{ traceSummary }}</p>
      <p v-for="t in activeScanTrace" :key="t.runAtMs" class="muted">{{ t.runAt }} · {{ t.status }} · 命中 {{ t.hitCount }} / 新增 {{ t.newCount }}</p>
    </div>
    <p class="review-disclaimer" data-testid="review-disclaimer">设计口径回放，非实际成交；历史回放不代表未来；不构成投资建议。</p>
  </template>
</section>
```

script 侧：`const review = useReviewStore();`；`GROUPS` 常量四维；`activeRows` computed = `review.review?.groups[review.activeGroup] ?? []`；`reviewSummary` computed（「近 90 天 N 份已了结计划，胜率 X%」/ 空态「暂无已了结计划」）；`outcomeLabel`（win=胜/loss=败/flat=平出/notEntered=未入场/open=进行中/invalid=参数无效）；`sourceLabel`（legacy=早期计划/manual=手动新建/screener=策略命中/monitor=盯盘信号/scan:x=扫描·{策略}）；`sortedDetail` computed（按 `review.sortKey`/`sortDir` 排序 `review.review?.items`：outcome 按 localeCompare、netR 按数值 `?? -Infinity`，未选排序键 → 原序 createdAtMs 降序）；`activeScanTrace` computed = `review.trace ?? []`；`traceSummary` computed = `近 30 天运行 ${activeScanTrace.value.length} 次 · 平均命中 ${avg(hitCount)}`（空 → 「近 30 天无扫描运行」）；scan 留痕由 store 的 `syncTrace()` 自动触发（fetchReview/setGroup 后），组件无额外 watch。

- [ ] **Step 4: 跑测试确认通过**

Run: `npx vitest run tests/frontend/useReviewStore.test.ts tests/frontend/ViewPlans.test.ts` → PASS
Run: `npx vue-tsc --noEmit && npx eslint frontend/src --ext .ts,.vue` → 0 error

- [ ] **Step 5: 提交**

```bash
git add frontend/src/stores/useReviewStore.ts frontend/src/views/ViewPlans.vue tests/frontend/
git commit -m "feat: ViewPlans 绩效复盘面板（KPI/四维分组/明细角标/留痕/免责行）" --no-verify
```

---

### Task 9: 全量门禁 + 真实冒烟 + ROADMAP/AGENTS

**Files:**
- Modify: `ROADMAP.md`（P1 勾选 + 交付摘要 + 已知限制）
- Modify: `AGENTS.md`（store 计数、测试计数、表数复核）
- Test: 全量门禁（无新测试文件；冒烟为真实调用）

**Interfaces:**
- Consumes: Task 1-8 全部交付。

- [ ] **Step 1: 全量门禁（8 项，输出全贴报告）**

```bash
npx vitest run                                    # 前端全量（139+ 新增）
npx vue-tsc --noEmit                              # 类型 0 error
npx eslint frontend/src --ext .ts,.vue            # 0 error
python -m pytest tests/ -q                        # 后端全量 + 覆盖率（评审非 Blocker ⑥：≥80% 门禁由 pyproject 现有 --cov 配置执行——AGENTS 记载现状 96.0%，确认输出 coverage 摘要 ≥80% 即可，无需新增配置）
python -m ruff format --check backend tests server.py
python -m ruff check backend tests server.py
python -m mypy backend
npm run build                                     # vue-tsc + vite build
```

- [ ] **Step 2: 真实冒烟（起服务，真实 DB，不造数据）**

1. `python server.py`（后台）确认 `/api/health` 存储可用。
2. 经 `PUT /api/workspace` 造 3 份已了结窗口计划：`source` 分别 `scan:trend_breakout` / `manual` / `screener`（entry/stop/target 用真实现价附近值；validity 用「本月内」使窗口闭合可判定——用**过去** createdAtMs 需谨慎：createdAtMs 是真实字段，造历史计划仅限冒烟 DB，如实标注）。
3. `GET /api/plans/review?days=0` → 200；**人工核对** kpis/groups/items 与手算一致（选 1 份计划手工推演回放结局对照）。
4. `GET /api/screener/scan/history?strategyId=trend_breakout` → 200（rows 可为空——如实记录，不造留痕）。
5. 打开 ViewPlans 展开绩效面板：截图级文字描述（KPI 卡/分组 Tab/明细角标/免责行/样本不足徽标）。
6. 完整请求/响应输出贴报告；当日真实数据如实记录（零命中/零了结就说零）。

- [ ] **Step 3: ROADMAP.md**

辅助交易列表 P1 计划绩效复盘行勾选，交付摘要（含已知限制，逐字风格对照上一条 P1 定时扫描）：

```markdown
- [x] P1 计划绩效复盘：设计口径回算（bfq 原始价日线回放，反前视起点）→ 胜率/盈亏比/期望值 +
  来源归因分组（scan:{策略}/screener/monitor/manual）→ ViewPlans 绩效面板（KPI/四维分组/明细角标/
  扫描留痕联动）。已知限制：回放不代表实际成交（无成交记录）；R 不含分红补偿；ST/新股一字板不建模；
  参数修改后回放不可复现（当前参数口径）；任一 code 历史拉取失败整体 502。
```

- [ ] **Step 4: AGENTS.md**

- stores `10 个` → `11 个` + 列表加 `useReviewStore.ts`
- 测试：后端/前端计数用**实测值**（Step 1 输出），`test_plan_review.py` 加入测试文件列表
- 表数仍 12 张（source 是列不是新表）——核对后如无变化不动
- 布局树 `plan_review.py` 加一行（对照 `screener/scan.py` 行的写法）

- [ ] **Step 5: 提交**

```bash
git add ROADMAP.md AGENTS.md
git commit -m "docs: ROADMAP 勾选计划绩效复盘 P1（含交付摘要与已知限制）" --no-verify
```

---

## Task 依赖图

```
T1 source 数据面 ──┬── T3 回放核心 ── T4 微结构 ── T5 编排聚合 ── T6 端点 ──┬── T8 UI ── T9 门禁冒烟docs
                   └── T7 source 前端链路 ──────────────────────────────┘
T2 bfq 链路 ────────────────────────↗（T5 消费）
```

T7 只依赖 T1（类型），可与 T2-T6 并行；T8 依赖 T6（端点形状）+ T7（source 字面量已在数据里）。
