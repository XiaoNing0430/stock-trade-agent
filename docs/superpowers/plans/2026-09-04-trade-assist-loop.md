# 研究 → 决策最小闭环（trade-assist-loop）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 策略选股命中 / 个股详情 → 一键生成带 ATR 止损、盈亏比目标、建议仓位的交易计划草案（前端零 API 调参），经工作区修订锁落为计划。

**Architecture:** 后端新增无状态草案服务 `backend/assist/`（纯函数计算 + 滑窗限频 + Router 编排，不写库）；前端 `assistCalc.ts` 纯函数镜像后端公式实现"调参即所见"（FR-13）；对话框经 `workspace.syncNow()` 显式 PUT（409 回滚不重试）。规格：`docs/superpowers/specs/2026-09-04-trade-assist-loop-spec.md`（唯一权威）。

**Tech Stack:** FastAPI + Pydantic v2 + pytest；Vue 3 + Pinia + vitest。分支 `feature/trade-assist-loop`（已建，spec 已提交）。

## Global Constraints

- UI 中文；绝不造数（数据缺失 → null + warning，绝不硬凑）。
- **写入唯一路径**：`PUT /api/workspace` 修订锁；后端草案端点绝不落库。409 绝不自动重试。
- 计划对象形状与 `usePlansStore.savePlan` 完全一致（`id: plan-{code}-{ts}`、`status: '执行中'`、`createdAtMs`、`triggered: {}`）。
- 时间戳机器值为 `createdAtMs`/`updatedAt`（epoch 毫秒）。
- 新 API 字段只增不改；pytest 覆盖率 ≥80% 门禁；ruff/mypy 0 错误。
- 提交：Conventional Commits + 中文主题 + `--no-verify`（CRLF 警告为良性噪声）。
- 复用而非新建：`indicators.atr/ma`、`closed_bars`（本计划抽公共）、`price_limit_ratio`、`classify_code`、Router `route_with_fallback`、`defaultCapital`（=账户权益）。

---

### Task 1: 公共截断 helper `closed_bars`（pipeline 去重）

**Files:**
- Modify: `backend/indicators.py`（文件末尾追加函数）
- Modify: `backend/screener/pipeline.py:250`（替换内联截断）
- Test: `tests/test_assist.py`（新建）

**Interfaces:**
- Produces: `closed_bars(bars: list[dict[str, Any]], ref_date: str, limit: int) -> list[dict[str, Any]]`（Task 3/6 消费）

- [ ] **Step 1: 写失败测试**（`tests/test_assist.py`）

```python
"""草案计算核心测试：closed_bars / 限频 / 纯函数 sizing（Task 1-3 逐段补充）。"""
from __future__ import annotations

from backend.indicators import closed_bars


def _bar(day: str, close: float) -> dict:
    return {"date": day, "open": close, "close": close, "high": close, "low": close, "volume": 100}


def test_closed_bars_truncates_future_dates() -> None:
    bars = [_bar("2026-09-01", 10.0), _bar("2026-09-02", 11.0), _bar("2026-09-03", 12.0)]
    closed = closed_bars(bars, "2026-09-02", limit=60)
    assert [b["date"] for b in closed] == ["2026-09-01", "2026-09-02"]


def test_closed_bars_keeps_last_limit() -> None:
    bars = [_bar(f"2026-08-{d:02d}", 10.0) for d in range(1, 11)]
    assert len(closed_bars(bars, "2026-08-31", limit=5)) == 5


def test_closed_bars_empty() -> None:
    assert closed_bars([], "2026-09-02", limit=60) == []
```

- [ ] **Step 2: 跑测试确认失败**：`python -m pytest tests/test_assist.py -q --no-cov` → FAIL（ImportError: cannot import name 'closed_bars'）
- [ ] **Step 3: 最小实现**（`backend/indicators.py` 末尾追加）

```python
def closed_bars(bars: list[dict[str, Any]], ref_date: str, limit: int) -> list[dict[str, Any]]:
    """截断至 ref_date（含）并取最后 limit 根——杜绝未来函数的唯一定义点。"""
    return [b for b in bars if str(b.get("date", "")) <= ref_date][-limit:]
```

（`indicators.py` 已有 `from typing import Any`？核对文件头 import，缺则补 `from typing import Any`。）

- [ ] **Step 4: 重构 pipeline 去重**：`backend/screener/pipeline.py` 顶部 import 区加 `from backend.indicators import closed_bars`；将 line ~250 的 `closed = [b for b in bars if str(b.get("date", "")) <= ref_date][-_CLOSED_BARS:]` 替换为 `closed = closed_bars(bars, ref_date, _CLOSED_BARS)`。
- [ ] **Step 5: 全绿验证**：`python -m pytest tests/test_assist.py tests/test_screener_pipeline.py tests/test_strategy_engines.py -q --no-cov` → PASS（管道行为不变）
- [ ] **Step 6: Commit**：`git add backend/indicators.py backend/screener/pipeline.py tests/test_assist.py && git commit -m "refactor: 抽取 closed_bars 公共截断 helper（管道去重）" --no-verify`

---

### Task 2: 滑动窗口限频器

**Files:**
- Create: `backend/assist/__init__.py`、`backend/assist/limiter.py`
- Test: `tests/test_assist.py`（追加）

**Interfaces:**
- Produces: `SlidingWindowLimiter(max_events: int, window_seconds: float = 60.0)`，`.check() -> tuple[bool, float]`（放行 / 建议 Retry-After 秒数）。**所有请求计数（含失败），保护上游。**

- [ ] **Step 1: 失败测试**（追加到 `tests/test_assist.py`）

```python
from backend.assist.limiter import SlidingWindowLimiter


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_allows_burst_then_blocks() -> None:
    clock = _FakeClock()
    limiter = SlidingWindowLimiter(max_events=3, window_seconds=60.0, clock=clock)
    assert limiter.check() == (True, 0.0)
    assert limiter.check() == (True, 0.0)
    assert limiter.check() == (True, 0.0)
    allowed, retry_after = limiter.check()
    assert not allowed
    assert 59.0 <= retry_after <= 60.0


def test_limiter_window_slides() -> None:
    clock = _FakeClock()
    limiter = SlidingWindowLimiter(max_events=2, window_seconds=60.0, clock=clock)
    limiter.check()
    limiter.check()
    clock.now += 61.0
    allowed, _ = limiter.check()
    assert allowed
```

- [ ] **Step 2: 确认失败**（ModuleNotFoundError: backend.assist）
- [ ] **Step 3: 实现**（`backend/assist/limiter.py`；`__init__.py` 仅 docstring）

```python
"""进程内滑动窗口限频（单用户本地部署；线程安全；时钟可注入便于测试）。"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class SlidingWindowLimiter:
    def __init__(
        self, max_events: int, window_seconds: float = 60.0, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._max = max_events
        self._window = window_seconds
        self._clock = clock
        self._events: deque[float] = deque()
        self._lock = threading.Lock()

    def check(self) -> tuple[bool, float]:
        now = self._clock()
        with self._lock:
            while self._events and now - self._events[0] >= self._window:
                self._events.popleft()
            if len(self._events) >= self._max:
                return False, max(self._window - (now - self._events[0]), 0.0)
            self._events.append(now)
            return True, 0.0
```

- [ ] **Step 4: 通过 + Commit**：`python -m pytest tests/test_assist.py -q --no-cov` → PASS；`git commit -m "feat: 草案端点滑窗限频器（30 次/分钟护栏）" --no-verify`

---

### Task 3: 草案计算核心（纯函数）

**Files:**
- Create: `backend/assist/calculator.py`
- Test: `tests/test_assist.py`（追加）

**Interfaces:**
- Consumes: `indicators.atr/ma/closed_bars`（Task 1）
- Produces: `indicator_levels(bars, ref_date) -> IndicatorLevels`；`sizing(entry, levels, *, stop_mode, equity, risk_pct, rr_ratio, cap_pct, limit_ratio) -> SizingResult`（Task 6 service 消费；Task 7 前端镜像同公式）

公式（前后端逐字段一致的唯一事实）：
`stop_distance = entry - stop`；`target = entry + stop_distance*rr`；`risk_amount = equity*risk_pct/100`；`shares = floor(risk_amount/stop_distance/100)*100`；上限 `cap_shares = floor(equity*cap_pct/100/entry/100)*100`，`shares = min(shares, cap_shares)`；`position_pct = shares*entry/equity*100`。止损候选 `stop_atr = entry - 2*atr14`、`stop_ma20 = ma20`，按 stopMode 优先，**候选 ≥ entry 视为无效**，preferred 无效则回退 alternate，均无效 → stop=None + warning。

- [ ] **Step 1: 失败测试**（追加；A=10.0、ATR=0.5、MA20=9.8 基准场景）

```python
from backend.assist.calculator import IndicatorLevels, indicator_levels, sizing

LEVELS = IndicatorLevels(
    reference_date="2026-09-03", closed_count=60, atr14=0.5, ma20=9.8,
    stop_atr=9.0, stop_ma20=9.8,
)


def test_indicator_levels_computes_atr_and_ma() -> None:
    bars = [
        {"date": f"2026-08-{d:02d}", "open": 10, "close": 10 + (d % 3) * 0.2,
         "high": 10.5 + (d % 3) * 0.2, "low": 9.5, "volume": 100}
        for d in range(1, 31)
    ]
    levels = indicator_levels(bars, "2026-08-30")
    assert levels.closed_count == 30
    assert levels.atr14 is not None and levels.atr14 > 0
    assert levels.ma20 is not None
    assert levels.stop_atr == round(10 - levels.ma20 * 0, 2) or True  # 结构断言，精确值见 sizing
    # 与 indicators 直算一致
    from backend.indicators import atr, ma
    closes = [float(b["close"]) for b in bars]
    assert levels.atr14 == atr(bars, period=14)[-1]
    assert levels.ma20 == ma(closes, 20)[-1]


def test_indicator_levels_insufficient_bars() -> None:
    bars = [_bar("2026-08-01", 10.0), _bar("2026-08-02", 10.1)]
    levels = indicator_levels(bars, "2026-08-30")
    assert levels.atr14 is None and levels.ma20 is None


def test_sizing_default_scenario() -> None:
    r = sizing(10.0, LEVELS, stop_mode="atr", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10)
    assert r.stop == 9.0 and r.stop_distance == 1.0
    assert r.target == 11.0 and r.risk_amount == 1000.0
    assert r.suggested_shares == 1000 and r.position_pct == 10.0


def test_sizing_insufficient_equity() -> None:
    r = sizing(10.0, LEVELS, stop_mode="atr", equity=9000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10)
    assert r.suggested_shares == 0 and any("不足一手" in w for w in r.warnings)


def test_sizing_cap_truncates() -> None:
    r = sizing(10.0, LEVELS, stop_mode="atr", equity=100000.0, risk_pct=5.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10)
    assert r.suggested_shares == 2500 and any("上限" in w for w in r.warnings)


def test_sizing_ma20_mode_and_fallback() -> None:
    r = sizing(10.0, LEVELS, stop_mode="ma20", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10)
    assert r.stop == 9.8  # ma20 优先且有效


def test_sizing_invalid_stop_falls_back_to_none() -> None:
    levels = IndicatorLevels(reference_date="d", closed_count=60, atr14=0.5, ma20=10.5, stop_atr=9.0, stop_ma20=10.5)
    r = sizing(10.0, levels, stop_mode="ma20", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10)
    assert r.stop == 9.0  # ma20 无效回退 atr


def test_sizing_all_stops_invalid() -> None:
    levels = IndicatorLevels(reference_date="d", closed_count=60, atr14=0.1, ma20=11.0, stop_atr=9.8, stop_ma20=11.0)
    r = sizing(10.0, levels, stop_mode="atr", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10)
    # stop_atr=9.8 有效——构造全无效场景
    levels2 = IndicatorLevels(reference_date="d", closed_count=60, atr14=0.1, ma20=11.0, stop_atr=10.5, stop_ma20=11.0)
    r2 = sizing(10.0, levels2, stop_mode="atr", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10)
    assert r2.stop is None and r2.target is None and r2.suggested_shares == 0
    assert any("止损" in w for w in r2.warnings)


def test_sizing_multiday_target_warning() -> None:
    r = sizing(10.0, LEVELS, stop_mode="atr", equity=100000.0, risk_pct=1.0, rr_ratio=3.0, cap_pct=25.0, limit_ratio=0.10)
    assert any("多日" in w for w in r.warnings)
```

（首个 `test_indicator_levels_computes_atr_and_ma` 中那行 `... or True` 结构断言是脚手架噪声——实现时删除该行，保留精确断言。）

- [ ] **Step 2: 确认失败**
- [ ] **Step 3: 实现**（`backend/assist/calculator.py`）

```python
"""交易计划草案纯计算核心（无 IO；与 frontend/src/modules/assistCalc.ts 逐字段一致）。"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from backend.indicators import atr, closed_bars, ma


@dataclass(frozen=True)
class IndicatorLevels:
    reference_date: str
    closed_count: int
    atr14: float | None
    ma20: float | None
    last_close: float | None  # 截断末根收盘（涨停价提示用，二轮评审）
    stop_atr: float | None
    stop_ma20: float | None


@dataclass(frozen=True)
class SizingResult:
    stop: float | None
    target: float | None
    stop_distance: float | None
    risk_amount: float | None
    suggested_shares: int
    position_pct: float
    warnings: list[str] = field(default_factory=list)


def indicator_levels(bars: list[dict], ref_date: str) -> IndicatorLevels:
    closed = closed_bars(bars, ref_date, limit=60)
    atr14 = None
    if len(closed) >= 15:
        atr_values = atr(closed, period=14)
        atr14 = atr_values[-1] if atr_values and atr_values[-1] is not None else None
    ma20 = None
    if len(closed) >= 20:
        closes = [float(b["close"]) for b in closed if b.get("close") is not None]
        ma_values = ma(closes, 20)
        ma20 = ma_values[-1] if ma_values and ma_values[-1] is not None else None
    stop_atr = round(closed[-1]["close"] - 2 * atr14, 2) if atr14 is not None else None
    stop_ma20 = round(ma20, 2) if ma20 is not None else None
    last_close = float(closed[-1]["close"]) if closed and closed[-1].get("close") is not None else None
    return IndicatorLevels(reference_date=ref_date, closed_count=len(closed), atr14=atr14, ma20=ma20, last_close=last_close)
```

注意：`stop_atr` 锚定**截断末根收盘**而非动态 entry（entry 由调用方在 sizing 里覆盖重算——见下）。修正：`indicator_levels` 不算 stop（entry 未知），`stop_atr/stop_ma20` 移到 `sizing` 里按 entry 现算。即 `IndicatorLevels` 只含 `reference_date/closed_count/atr14/ma20`，`sizing(entry, levels, ...)` 内部：

```python
def sizing(entry, levels, *, stop_mode, equity, risk_pct, rr_ratio, cap_pct, limit_ratio) -> SizingResult:
    warnings: list[str] = []
    stop_atr = round(entry - 2 * levels.atr14, 2) if levels.atr14 is not None else None
    stop_ma20 = round(levels.ma20, 2) if levels.ma20 is not None else None
    if stop_atr is None:
        warnings.append("历史数据不足，无法计算 ATR 止损")
    if stop_ma20 is None:
        warnings.append("历史数据不足，无法计算 MA20 止损")
    preferred, alternate = (stop_atr, stop_ma20) if stop_mode == "atr" else (stop_ma20, stop_atr)
    stop = next((c for c in (preferred, alternate) if c is not None and c < entry), None)
    if stop is None and (preferred is not None or alternate is not None):
        warnings.append("候选止损价均不低于入场价，已置空止损（强趋势 / 数据不足），请手动设定")
    target = stop_distance = risk_amount = None
    shares, position_pct = 0, 0.0
    if stop is not None:
        stop_distance = round(entry - stop, 2)
        risk_amount = round(equity * risk_pct / 100.0, 2)
        shares = int(math.floor(risk_amount / stop_distance / 100.0)) * 100
        cap_shares = int(math.floor(equity * cap_pct / 100.0 / entry / 100.0)) * 100
        if shares <= 0:
            warnings.append("权益不足一手，无法按该风险比例建仓")
        elif shares > cap_shares:
            shares = max(cap_shares, 0)
            warnings.append("建议仓位已按单票市值上限截断")
        target = round(entry + stop_distance * rr_ratio, 2)
        if (target - entry) / entry > limit_ratio:
            warnings.append("目标位距入场价超单日涨幅上限，需多日达成")
        if shares > 0:
            position_pct = round(shares * entry / equity * 100.0, 2)
    return SizingResult(stop=stop, target=target, stop_distance=stop_distance, risk_amount=risk_amount, suggested_shares=max(shares, 0), position_pct=position_pct, warnings=warnings)
```

（`IndicatorLevels` 相应删去 `stop_atr/stop_ma20` 两字段；`test_sizing_*` 用 `IndicatorLevels(reference_date=..., closed_count=60, atr14=0.5, ma20=9.8)` 构造。cap 截断测试核对：equity=100000、cap=25% → cap_shares=2500；risk 5% → raw=5000 → 截至至 2500 ✓。）

- [ ] **Step 4: 通过 + Commit**：`git commit -m "feat: 草案计算核心（ATR/MA20 止损 + 盈亏比目标 + 风险仓位）" --no-verify`

---

### Task 4: 工作区设置 4 键

**Files:**
- Modify: `backend/storage.py:294-335`（DEFAULT_WORKSPACE_SETTINGS + `_normalize_workspace_settings`）
- Test: `tests/test_settings_api.py`（追加）

**Interfaces:**
- Produces: 设置键 `riskPerTradePct=1.0`（0.1–5）、`rrRatio=2.0`（1–10）、`stopMode="atr"`（atr|ma20）、`positionCapPct=25`（5–100）；`defaultCapital` 既有键复用为账户权益（不动）。

- [ ] **Step 1: 失败测试**（追加到 `tests/test_settings_api.py`）

```python
def test_settings_assist_defaults(client: Any) -> None:
    data = client.get("/api/settings").json()
    assert data["riskPerTradePct"] == 1.0
    assert data["rrRatio"] == 2.0
    assert data["stopMode"] == "atr"
    assert data["positionCapPct"] == 25.0


def test_settings_assist_clamps(client: Any) -> None:
    resp = client.put("/api/settings", json={"riskPerTradePct": 99, "rrRatio": 0, "stopMode": "bogus", "positionCapPct": 1})
    data = resp.json()
    assert data["riskPerTradePct"] == 5.0
    assert data["rrRatio"] == 1.0
    assert data["stopMode"] == "atr"
    assert data["positionCapPct"] == 5.0
```

（`client` fixture 名与该文件既有写法一致，先看文件头再套用。）

- [ ] **Step 2: 确认失败** → **Step 3: 实现**：`DEFAULT_WORKSPACE_SETTINGS` 追加 4 键；normalize 追加：

```python
    data["riskPerTradePct"] = max(0.1, min(float(data["riskPerTradePct"]), 5.0))
    data["rrRatio"] = max(1.0, min(float(data["rrRatio"]), 10.0))
    data["stopMode"] = data["stopMode"] if data["stopMode"] in {"atr", "ma20"} else "atr"
    data["positionCapPct"] = max(5.0, min(float(data["positionCapPct"]), 100.0))
```

（`data["stopMode"]` 初值来自 payload dict 原样，`float()` 转换前注意 riskPerTradePct 可能是 int——`float()` 包裹已覆盖。）

- [ ] **Step 4: 通过**（`python -m pytest tests/test_settings_api.py tests/test_storage_coverage.py -q --no-cov`）+ **Step 5: Commit**：`feat: 工作区设置新增交易辅助 4 键（风险%/盈亏比/止损模式/单票上限）`

---

### Task 5: API 契约 schema

**Files:**
- Modify: `backend/schemas.py`（文件末尾追加两个模型）
- Test: `tests/test_schemas.py`（追加）

- [ ] **Step 1: 失败测试**（追加到 `tests/test_schemas.py`）

```python
def test_plan_draft_in_defaults() -> None:
    from backend.schemas import PlanDraftIn
    m = PlanDraftIn.model_validate({"code": "600519"})
    assert m.code == "600519" and m.entryPrice is None and m.stopMode is None


def test_plan_draft_in_rejects_out_of_range() -> None:
    import pytest
    from pydantic import ValidationError
    from backend.schemas import PlanDraftIn
    with pytest.raises(ValidationError):
        PlanDraftIn.model_validate({"code": "600519", "rrRatio": 99})
    with pytest.raises(ValidationError):
        PlanDraftIn.model_validate({"code": "600519", "entryPrice": -1})


def test_plan_draft_out_shape() -> None:
    from backend.schemas import PlanDraftOut
    m = PlanDraftOut.model_validate({
        "code": "600519", "name": "贵州茅台", "entry": 10.0, "referenceDate": "2026-09-03",
        "disclaimer": "x",
    })
    assert m.direction == "buy" and m.suggestedShares == 0 and m.stale is False and m.fallbackUsed is False
    assert m.warnings == []
```

- [ ] **Step 2: 确认失败** → **Step 3: 实现**（`backend/schemas.py` 末尾；`Literal` 若未导入则从 typing 补）

```python
class PlanDraftIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    name: str | None = None
    entryPrice: float | None = Field(default=None, gt=0)
    entryAsOfMs: int | None = Field(default=None, ge=0)
    stopMode: Literal["atr", "ma20"] | None = None
    rrRatio: float | None = Field(default=None, ge=1, le=10)
    accountEquity: float | None = Field(default=None, gt=0)
    riskPct: float | None = Field(default=None, ge=0.1, le=5)


class PlanDraftOut(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    name: str = ""
    direction: str = "buy"
    entry: float
    stopAtr: float | None = None
    stopMa20: float | None = None
    stop: float | None = None
    target: float | None = None
    stopDistance: float | None = None
    atr14: float | None = None
    ma20: float | None = None
    riskAmount: float | None = None
    suggestedShares: int = 0
    positionPct: float = 0.0
    referenceDate: str
    entryAsOf: int | None = None
    stale: bool = False
    fallbackUsed: bool = False
    provider: str = ""
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str
```

- [ ] **Step 4: 通过**（`python -m pytest tests/test_schemas.py -q --no-cov`）+ **Step 5: Commit**：`feat: 草案 API 契约 PlanDraftIn/Out`

---

### Task 6: API 端点 + 限频接线 + 观测日志

**Files:**
- Create: `backend/assist/service.py`（Router 编排 + stale 判定 + UpstreamError）
- Modify: `backend/assist/__init__.py`（导出）、`backend/app.py`（常量 `ERR_RATE_LIMITED`、`create_app` 内 `app.state.assist_limiter`、端点）
- Test: `tests/test_backend_api.py`（追加 assist 端点测试，monkeypatch 模式与既有 screener 测试一致）

**Interfaces:**
- Consumes: Task 1-5 全部产出；`classify_code` / `price_limit_ratio`（`backend.data_source`）；Router `route_with_fallback(source_id: str, capability: str, fallback_enabled: bool)`（capability 为字面量 `"realtime"` / `"history"`）；Router `route(source_id, capability)`（不降级取首选源，用于 fallbackUsed 判定）。
- Produces: `POST /api/assist/plan-draft`（200 草案 / 422 校验 / 429+Retry-After / 502 上游）；响应含 `fallbackUsed`（二轮评审：降级透明化）。

- [ ] **Step 1: service 实现**（`backend/assist/service.py`）

```python
"""草案编排：Router 取数 + stale 判定 + 组装响应 dict（无状态，绝不落库）。"""
from __future__ import annotations

from datetime import date
from typing import Any, Callable

from backend.assist.calculator import indicator_levels, sizing
from backend.data_source import classify_code, price_limit_ratio

DISCLAIMER = "算法生成的建议，非投资建议；止损 / 目标 / 仓位均基于公开行情计算，请自行判断。"
_T1_WARNING = "A 股 T+1：当日买入次交易日方可卖出，止损自次一交易日生效"
_STALE_MAX_AGE_MS = 60_000


class UpstreamError(Exception):
    """行情 / 历史数据不可用（→ 502，绝不返回造数草案）。"""


def entry_staleness(entry_as_of_ms: int | None, now_ms: int) -> tuple[bool, list[str]]:
    if entry_as_of_ms is None:
        return True, ["入场价快照时间未知，请核实现价"]
    if now_ms - entry_as_of_ms > _STALE_MAX_AGE_MS:
        return True, ["入场价为过期快照，请核实现价"]
    return False, []


def _limit_up_warning(entry: float, last_close: float, code: str) -> list[str]:
    """触及涨停价提示（二轮评审：封板不可买入的成交风险，不阻断）。"""
    limit_price = round(last_close * (1 + price_limit_ratio(code)), 2)
    if entry >= limit_price:
        return ["当前价格触及涨停，实际成交可能存在风险"]
    return []


def build_plan_draft(router: Any, payload: dict[str, Any], settings_getter: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    code = str(payload.get("code", "")).strip()
    profile = classify_code(code)
    if profile["securityType"] not in {"股票", "ETF"}:
        raise ValueError(f"无法识别的证券代码：{code}")
    settings = settings_getter()
    fallback_enabled = bool(settings.get("fallbackEnabled", True))
    entry = payload.get("entryPrice")
    as_of = payload.get("entryAsOfMs")
    name = str(payload.get("name") or "")
    provider = ""
    fallback_used = False
    try:
        if entry is None:
            source = router.route_with_fallback(settings["realtimeSource"], "realtime", fallback_enabled)
            rows = source.load_quotes([code])
            row = next((q for q in rows if str(q.get("code")) == code), None)
            if row is None or not row.get("price"):
                raise UpstreamError(f"暂无 {code} 实时报价")
            entry = float(row["price"])
            as_of = row.get("updatedAt")
            name = name or str(row.get("name") or "")
            provider = source.provider_label
        history_source = router.route_with_fallback(settings["historySource"], "history", fallback_enabled)
        # fallbackUsed 判定：实际路由源 ≠ 设置首选源（二轮评审；route() 不降级，仅取首选）
        try:
            preferred_history = router.route(settings["historySource"], "history")
            fallback_used = preferred_history.id != history_source.id
        except Exception:
            fallback_used = False
        bars = history_source.load_history(code, limit=62, is_index=False)
        ref_date = str(history_source.calendar.previous_trading_day(date.today()).isoformat())
        if not provider:
            provider = history_source.provider_label
    except UpstreamError:
        raise
    except Exception as exc:  # 上游网络/解析失败 → 502
        raise UpstreamError(str(exc)) from exc

    entry = float(entry)
    if entry <= 0:
        raise ValueError("入场价必须为正数")
    levels = indicator_levels(bars, ref_date)
    result = sizing(
        entry, levels,
        stop_mode=str(payload.get("stopMode") or settings["stopMode"]),
        equity=float(payload.get("accountEquity") or settings["defaultCapital"]),
        risk_pct=float(payload["riskPct"]) if payload.get("riskPct") is not None else float(settings["riskPerTradePct"]),
        rr_ratio=float(payload["rrRatio"]) if payload.get("rrRatio") is not None else float(settings["rrRatio"]),
        cap_pct=float(settings["positionCapPct"]),
        limit_ratio=price_limit_ratio(code),
    )
    stale, stale_warnings = entry_staleness(as_of, int(time.time() * 1000))
    limit_up_warnings = _limit_up_warning(entry, levels_last_close, code) if bars else []
    return {
        "code": code, "name": name, "direction": "buy", "entry": entry,
        "stopAtr": round(entry - 2 * levels.atr14, 2) if levels.atr14 is not None else None,
        "stopMa20": round(levels.ma20, 2) if levels.ma20 is not None else None,
        "stop": result.stop, "target": result.target, "stopDistance": result.stop_distance,
        "atr14": levels.atr14, "ma20": levels.ma20,
        "riskAmount": result.risk_amount, "suggestedShares": result.suggested_shares,
        "positionPct": result.position_pct,
        "referenceDate": levels.reference_date, "entryAsOf": as_of, "stale": stale,
        "fallbackUsed": fallback_used,
        "provider": provider,
        "warnings": stale_warnings + limit_up_warnings + result.warnings, "disclaimer": DISCLAIMER,
    }
```

（实现时补：`levels_last_close = float(closed_bars(bars, ref_date, 1)[-1]["close"]) if bars else None`——直接在 service 内从 `indicator_levels` 返回值取更简：给 `IndicatorLevels` 加 `last_close: float | None` 字段即可，Task 3 实现时带上。`__import__("time")` 换成顶部 `import time`。）

- [ ] **Step 2: 失败测试**（`tests/test_backend_api.py` 追加；fixture/mocking 风格照抄该文件既有 screener 测试——先读文件头 30 行）

```python
# --- 辅助 fixture：隔离限频（每测试新 app 实例即新 limiter，无需额外清理） ---

def _assist_bars() -> list:
    return [
        {"date": f"2026-08-{d:02d}", "open": 10, "close": 10 + (d % 3) * 0.2,
         "high": 10.6 + (d % 3) * 0.2, "low": 9.4, "volume": 1000}
        for d in range(1, 31)
    ]


def test_assist_plan_draft_happy_path(monkeypatch: Any, client: Any) -> None:
    from backend.sources import tencent as tx_module
    monkeypatch.setattr(tx_module.TencentSource, "load_quotes", lambda self, codes: [
        {"code": "600519", "name": "贵州茅台", "price": 10.0, "volume": 100, "updatedAt": int(time.time() * 1000)}
    ])
    monkeypatch.setattr(tx_module.TencentSource, "load_history", lambda self, code, limit, is_index=False: _assist_bars())
    monkeypatch.setattr(tx_module.TencentSource, "calendar", property(lambda self: _AssistFakeCalendar()))
    resp = client.post("/api/assist/plan-draft", json={"code": "600519", "entryPrice": 10.0, "entryAsOfMs": int(time.time() * 1000), "name": "贵州茅台"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["direction"] == "buy" and data["entry"] == 10.0
    assert data["stopAtr"] == 9.0 or data["stopAtr"] == pytest.approx(10.0 - 2 * data["atr14"], abs=0.01)
    assert data["suggestedShares"] % 100 == 0
    assert data["referenceDate"] == "2026-09-02"
    assert data["stale"] is False
    assert any("T+1" in w for w in data["warnings"])


def test_assist_plan_draft_halted_rejected(monkeypatch: Any, client: Any) -> None:
    from backend.sources import tencent as tx_module
    monkeypatch.setattr(tx_module.TencentSource, "load_history", lambda self, code, limit, is_index=False: _assist_bars())
    monkeypatch.setattr(tx_module.TencentSource, "calendar", property(lambda self: _AssistFakeCalendar()))
    resp = client.post("/api/assist/plan-draft", json={"code": "600519", "entryPrice": 0})  # pydantic gt=0 → 422
    assert resp.status_code == 422


def test_assist_plan_draft_unknown_code(monkeypatch: Any, client: Any) -> None:
    resp = client.post("/api/assist/plan-draft", json={"code": "abc", "entryPrice": 10.0})
    assert resp.status_code == 422


def test_assist_plan_draft_upstream_502(monkeypatch: Any, client: Any) -> None:
    from backend.sources import tencent as tx_module

    def _boom(self, code, limit, is_index=False):
        raise RuntimeError("network down")

    monkeypatch.setattr(tx_module.TencentSource, "load_history", _boom)
    resp = client.post("/api/assist/plan-draft", json={"code": "600519", "entryPrice": 10.0})
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "UPSTREAM_UNAVAILABLE"


def test_assist_plan_draft_stale_entry(monkeypatch: Any, client: Any) -> None:
    from backend.sources import tencent as tx_module
    monkeypatch.setattr(tx_module.TencentSource, "load_history", lambda self, code, limit, is_index=False: _assist_bars())
    monkeypatch.setattr(tx_module.TencentSource, "calendar", property(lambda self: _AssistFakeCalendar()))
    old_ms = int(time.time() * 1000) - 120_000
    resp = client.post("/api/assist/plan-draft", json={"code": "600519", "entryPrice": 10.0, "entryAsOfMs": old_ms})
    data = resp.json()
    assert data["stale"] is True and any("过期快照" in w for w in data["warnings"])


def test_assist_plan_draft_rate_limited(client: Any) -> None:
    for _ in range(30):
        client.post("/api/assist/plan-draft", json={"code": "abc"})  # 422 也计数
    resp = client.post("/api/assist/plan-draft", json={"code": "abc"})
    assert resp.status_code == 429
    assert resp.json()["detail"]["code"] == "RATE_LIMITED"
    assert "retry-after" in {k.lower() for k in resp.headers}


def test_assist_plan_draft_fallback_flag(monkeypatch: Any, client: Any) -> None:
    """主源 history 失败 → 降级东财成功 → fallbackUsed=True（二轮评审）。"""
    from backend.sources import eastmoney as em_module
    from backend.sources import tencent as tx_module

    def _tx_boom(self, code, limit, is_index=False):
        raise RuntimeError("tencent down")

    monkeypatch.setattr(tx_module.TencentSource, "load_history", _tx_boom)
    monkeypatch.setattr(em_module.EastMoneySource, "load_history", lambda self, code, limit, is_index=False: _assist_bars())
    monkeypatch.setattr(em_module.EastMoneySource, "calendar", property(lambda self: _AssistFakeCalendar()))
    resp = client.post("/api/assist/plan-draft", json={"code": "600519", "entryPrice": 10.0})
    assert resp.status_code == 200
    assert resp.json()["fallbackUsed"] is True


def test_assist_plan_draft_limit_up_warning(monkeypatch: Any, client: Any) -> None:
    """entry 触及涨停价（末根收盘 10.0 × 1.10 = 11.0）→ 警告不阻断（二轮评审）。"""
    from backend.sources import tencent as tx_module
    monkeypatch.setattr(tx_module.TencentSource, "load_history", lambda self, code, limit, is_index=False: _assist_bars())
    monkeypatch.setattr(tx_module.TencentSource, "calendar", property(lambda self: _AssistFakeCalendar()))
    resp = client.post("/api/assist/plan-draft", json={"code": "600519", "entryPrice": 11.0})
    assert resp.status_code == 200
    assert any("涨停" in w for w in resp.json()["warnings"])
```

`_AssistFakeCalendar`：`previous_trading_day` 返回 `date(2026, 9, 2)`（与 bars 末根 08-30 分离，验证截断）。检查该测试文件是否已有类似 FakeCalendar 可复用，有则用现成的。

- [ ] **Step 3: 端点实现**（`backend/app.py`）

常量区追加：`ERR_RATE_LIMITED = "RATE_LIMITED"  # 429 草案限频`。

`create_app` 内 `app.state.assist_limiter = SlidingWindowLimiter(max_events=30, window_seconds=60.0)`、`app.state.assist_router = build_router()`（`from backend.sources import build_router`；与 screener 端点的 `_strategy_pipeline` 模式并存——注意 build_router 在 create_app 时调用需离线安全：参考 `/api/sources` 端点如何构建 router，保持同一模式）。

端点（放在 screener 端点之后）：

```python
    @app.post("/api/assist/plan-draft", response_model=PlanDraftOut)
    def assist_plan_draft(payload: PlanDraftIn) -> PlanDraftOut:
        limiter: SlidingWindowLimiter = app.state.assist_limiter
        allowed, retry_after = limiter.check()
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail={"error": "草案请求过于频繁，请稍后再试", "code": ERR_RATE_LIMITED},
                headers={"Retry-After": str(max(1, int(retry_after) + 1))},
            )
        started = time.monotonic()
        trace_id = uuid.uuid4().hex[:12]
        try:
            draft = build_plan_draft(app.state.assist_router, payload.model_dump(), lambda: get_workspace_settings("default"))
        except ValueError as exc:
            raise api_error(422, ERR_VALIDATION_ERROR, str(exc)) from exc
        except UpstreamError as exc:
            logger.warning("assist.upstream_error", extra={"trace_id": trace_id, "code": payload.code, "error": str(exc)})
            raise api_error(502, ERR_UPSTREAM_UNAVAILABLE, str(exc), provider="upstream") from exc
        logger.info(
            "assist.plan_draft",
            extra={"trace_id": trace_id, "code": payload.code, "elapsed_ms": int((time.monotonic() - started) * 1000),
                   "shares": draft["suggestedShares"], "stale": draft["stale"],
                   "fallback_used": draft["fallbackUsed"], "provider": draft["provider"]},
        )
        return PlanDraftOut.model_validate(draft)
```

（import 区：`from backend.assist.limiter import SlidingWindowLimiter`、`from backend.assist.service import UpstreamError, build_plan_draft`、schemas 增 `PlanDraftIn/PlanDraftOut`；`uuid`/`time` 若未导入则补。`logger` 已存在则复用。`get_workspace_settings` 已是 app.py 顶层导入。）

- [ ] **Step 4: 通过**（`python -m pytest tests/test_backend_api.py -q --no-cov`，若既有测试因 create_app 新增 build_router 受影响，按 `/api/sources` 端点既有模式调整）+ **Step 5: mypy/ruff**：`python -m mypy backend && python -m ruff check backend tests server.py && python -m ruff format --check backend` → 0 错误
- [ ] **Step 6: Commit**：`feat: POST /api/assist/plan-draft（限频 + 422/429/502 + trace 日志）`

---

### Task 7: 前端纯函数 `assistCalc.ts`（与后端逐字段镜像）

**Files:**
- Create: `frontend/src/modules/assistCalc.ts`
- Test: `tests/frontend/assistCalc.test.ts`（新建）

**Interfaces:**
- Consumes: Task 3 的公式定义（数学镜像）
- Produces: `selectStop(entry, indicators, mode)` / `sizePosition(entry, stop, equity, params)`（Task 8 对话框消费）

- [ ] **Step 1: 失败测试**（`tests/frontend/assistCalc.test.ts`）

```ts
import { describe, expect, it } from 'vitest';
import { selectStop, sizePosition } from '@/modules/assistCalc';

const indicators = { stopAtr: 9.0, stopMa20: 9.8 };

describe('selectStop', () => {
  it('atr 模式优先且有效', () => {
    expect(selectStop(10, indicators, 'atr')).toBe(9.0);
  });
  it('ma20 模式取 ma20', () => {
    expect(selectStop(10, indicators, 'ma20')).toBe(9.8);
  });
  it('首选无效回退备选', () => {
    expect(selectStop(10, { stopAtr: 10.5, stopMa20: 9.8 }, 'atr')).toBe(9.8);
  });
  it('全部无效返回 null', () => {
    expect(selectStop(10, { stopAtr: 10.5, stopMa20: 11 }, 'atr')).toBeNull();
  });
});

describe('sizePosition', () => {
  const p = { rrRatio: 2, riskPct: 1, capPct: 25 };
  it('基准：整手 1000 股', () => {
    const r = sizePosition(10, 9.0, 100000, p);
    expect(r.target).toBe(11.0);
    expect(r.shares).toBe(1000);
    expect(r.positionPct).toBe(10.0);
  });
  it('资金不足一手', () => {
    const r = sizePosition(10, 9.0, 9000, p);
    expect(r.shares).toBe(0);
    expect(r.warnings.some((w) => w.includes('不足一手'))).toBe(true);
  });
  it('单票上限截断', () => {
    const r = sizePosition(10, 9.0, 100000, { ...p, riskPct: 5 });
    expect(r.shares).toBe(2500);
  });
});
```

- [ ] **Step 2: 确认失败** → **Step 3: 实现**（`frontend/src/modules/assistCalc.ts`）

```ts
/**
 * 草案调参纯函数——与 backend/assist/calculator.py 的 sizing 逐字段一致（FR-13）。
 * 调参仅在此重算，零 API 调用。
 */
export interface DraftIndicators {
  stopAtr: number | null;
  stopMa20: number | null;
}

export interface SizingParams {
  rrRatio: number;
  riskPct: number;
  capPct: number;
}

export interface SizingOutput {
  stop: number | null;
  target: number | null;
  shares: number;
  positionPct: number;
  warnings: string[];
}

export function selectStop(entry: number, indicators: DraftIndicators, mode: 'atr' | 'ma20'): number | null {
  const preferred = mode === 'atr' ? indicators.stopAtr : indicators.stopMa20;
  const alternate = mode === 'atr' ? indicators.stopMa20 : indicators.stopAtr;
  const valid = [preferred, alternate].find((c) => c !== null && c < entry);
  return valid ?? null;
}

export function sizePosition(entry: number, stop: number | null, equity: number, params: SizingParams): SizingOutput {
  const warnings: string[] = [];
  if (stop === null || stop <= 0 || stop >= entry) {
    return { stop, target: null, shares: 0, positionPct: 0, warnings: ['请先设定低于入场价的止损'] };
  }
  const stopDistance = Math.round((entry - stop) * 100) / 100;
  const riskAmount = Math.round(((equity * params.riskPct) / 100) * 100) / 100;
  let shares = Math.floor(riskAmount / stopDistance / 100) * 100;
  const capShares = Math.floor((equity * params.capPct) / 100 / entry / 100) * 100;
  if (shares <= 0) {
    warnings.push('权益不足一手，无法按该风险比例建仓');
  } else if (shares > capShares) {
    shares = Math.max(capShares, 0);
    warnings.push('建议仓位已按单票市值上限截断');
  }
  const target = Math.round((entry + stopDistance * params.rrRatio) * 100) / 100;
  const positionPct = shares > 0 ? Math.round(((shares * entry) / equity) * 100 * 100) / 100 : 0;
  return { stop, target, shares, positionPct, warnings };
}
```

- [ ] **Step 4: 通过**（`npx vitest run tests/frontend/assistCalc.test.ts`）+ **Step 5: Commit**：`feat: 前端草案调参纯函数（后端公式镜像，零 API 调参）`

---

### Task 8: useAssistStore + PlanDraftDialog + `syncNow`

**Files:**
- Create: `frontend/src/stores/useAssistStore.ts`、`frontend/src/components/PlanDraftDialog.vue`（新建 `components/` 目录——两个视图共用对话框的最小结构新增，同步补一行到 AGENTS.md 项目布局）
- Modify: `frontend/src/stores/useWorkspaceStore.ts`（新增 `syncNow()`；`scheduleWorkspaceSync` 不动）、`frontend/src/App.vue`（挂载对话框）
- Test: `tests/frontend/PlanDraftDialog.test.ts`（新建）

**Interfaces:**
- Consumes: Task 7 纯函数；`workspace.requestJson / plans / persist / showToast / watchlistCodes / isWatched`
- Produces: `useAssistStore` → `visible / loading / submitting / draft / error / openFor(payload) / confirmDraft() / close()`；`workspace.syncNow(): Promise<{ ok: boolean; conflict?: boolean }>`
- 二轮评审约束：**`suggestedShares === 0` 或无有效止损时确认按钮置灰** + 提示「资金不足以按该风险比例建仓，请调高风险比例或降低入场价」——不保存无效计划；`fallbackUsed=true` 对话框顶部小黄标提示。

- [ ] **Step 1: `syncNow` 实现**（`useWorkspaceStore.ts`，加在 `scheduleWorkspaceSync` 后；**不改动既有同步逻辑**）

```ts
  /** 立即执行一次工作区 PUT（对话框确认等需要确定性结果的动作用）；绝不自动重试 409。 */
  async function syncNow(): Promise<{ ok: boolean; conflict?: boolean }> {
    if (!workspaceSynced.value) return { ok: true };
    let waited = 0;
    while (workspaceSyncInFlight && waited < 3000) {   // 上限 3s：定时同步卡死时不可让 UI 假死（二轮评审）
      await new Promise((resolve) => setTimeout(resolve, 120));
      waited += 120;
    }
    if (workspaceSyncInFlight) return { ok: false };
    workspaceSyncInFlight = true;
    try {
      await requestJson(`/api/workspace?baseRevision=${encodeURIComponent(workspaceRevision.value)}`, {
        method: 'PUT',
        body: JSON.stringify(workspacePayload()),
      });
      return { ok: true };
    } catch (error: any) {
      if (error.status === 409) return { ok: false, conflict: true };
      return { ok: false };
    } finally {
      workspaceSyncInFlight = false;
    }
  }
```

（并加入 return 导出对象；`workspaceSyncInFlight` 复用现有变量，与定时同步互斥。confirmDraft 对 `!ok && !conflict` 分支的 toast 已覆盖"同步正忙"场景——文案统一为「工作区同步失败，本地已保留（恢复后自动同步）」。）

- [ ] **Step 2: 失败测试**（`tests/frontend/PlanDraftDialog.test.ts`；mount 模式照抄 `tests/frontend/ViewScreener.test.ts` 头部——Pinia + workspace requestJson spy）

```ts
import { mount } from '@vue/test-utils';
import { createPinia, setActivePinia } from 'pinia';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useAssistStore } from '@/stores/useAssistStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import PlanDraftDialog from '@/components/PlanDraftDialog.vue';

const DRAFT = {
  code: '600519', name: '贵州茅台', direction: 'buy', entry: 10, stopAtr: 9.0, stopMa20: 9.8,
  stop: 9.0, target: 11.0, stopDistance: 1.0, atr14: 0.5, ma20: 9.8, riskAmount: 1000,
  suggestedShares: 1000, positionPct: 10.0, referenceDate: '2026-09-02', entryAsOf: 1, stale: false,
  provider: 'x', warnings: ['A 股 T+1：当日买入次交易日方可卖出，止损自次一交易日生效'],
  disclaimer: '算法生成的建议，非投资建议',
};

async function mountDialog() {
  const wrapper = mount(PlanDraftDialog, { global: { plugins: [createPinia()] } });
  const assist = useAssistStore();
  assist.draft = structuredClone(DRAFT);
  assist.visible = true;
  await wrapper.vm.$nextTick();
  return { wrapper, assist };
}

beforeEach(() => setActivePinia(createPinia()));

describe('PlanDraftDialog', () => {
  it('调参重算零 API（改盈亏比仅本地重算）', async () => {
    const { wrapper } = await mountDialog();
    const workspace = useWorkspaceStore();
    const spy = vi.spyOn(workspace, 'requestJson');
    spy.mockClear();
    await wrapper.find('input[data-testid="rr-input"]').setValue('3');
    expect(spy).not.toHaveBeenCalled();
    expect(wrapper.find('[data-testid="target"]').text()).toContain('11.50');
  });

  it('确认走 PUT 且计划入列', async () => {
    const { wrapper } = await mountDialog();
    const workspace = useWorkspaceStore();
    const spy = vi.spyOn(workspace, 'requestJson').mockResolvedValue({ revision: 2 });
    await wrapper.find('button[data-testid="confirm"]').trigger('click');
    await vi.dynamicImportSettled();
    expect(spy).toHaveBeenCalledWith(expect.stringContaining('/api/workspace'), expect.anything());
    const body = JSON.parse(spy.mock.calls[0][1].body);
    expect(workspace.plans[0].code).toBe('600519');
    expect(workspace.plans[0].direction).toBe('buy');
    expect(workspace.plans[0].triggered).toEqual({});
    void body;
  });

  it('双击只保存一次（single-flight）', async () => {
    const { wrapper } = await mountDialog();
    const workspace = useWorkspaceStore();
    let resolveOnce: (v: unknown) => void = () => {};
    const spy = vi.spyOn(workspace, 'requestJson').mockImplementation(() => new Promise((r) => { resolveOnce = r; }));
    const btn = wrapper.find('button[data-testid="confirm"]');
    await btn.trigger('click');
    await btn.trigger('click');
    resolveOnce({ revision: 2 });
    await vi.dynamicImportSettled();
    expect(workspace.plans.filter((p: any) => p.code === '600519').length).toBe(1);
    void spy;
  });

  it('409 回滚本地计划并提示，不自动重试', async () => {
    const { wrapper } = await mountDialog();
    const workspace = useWorkspaceStore();
    const toastSpy = vi.spyOn(workspace, 'showToast');
    vi.spyOn(workspace, 'requestJson').mockRejectedValue({ status: 409 });
    await wrapper.find('button[data-testid="confirm"]').trigger('click');
    await vi.dynamicImportSettled();
    expect(workspace.plans.length).toBe(0);
    expect(toastSpy).toHaveBeenCalledWith('工作区有新变更，请刷新后重试', 'error');
  });

  it('shares=0 时确认按钮置灰（不保存无效计划）', async () => {
    const { wrapper, assist } = await mountDialog();
    assist.draft = { ...structuredClone(DRAFT), suggestedShares: 0, positionPct: 0, warnings: [...DRAFT.warnings, '权益不足一手，无法按该风险比例建仓'] };
    await wrapper.vm.$nextTick();
    const btn = wrapper.find('button[data-testid="confirm"]');
    expect(btn.attributes('disabled')).toBeDefined();
  });

  it('fallbackUsed=true 显示备用源黄标', async () => {
    const { wrapper } = await mountDialog();
    const assist = useAssistStore();
    assist.draft = { ...structuredClone(DRAFT), fallbackUsed: true };
    await wrapper.vm.$nextTick();
    expect(wrapper.find('[data-testid="fallback-badge"]').exists()).toBe(true);
  });
});
```

（mock 细节按 ViewScreener.test.ts 既有 workspace patch 手法调整——若该文件用 `vi.mock` 全局替换而非 spy，保持同款。）

- [ ] **Step 3: store 实现**（`frontend/src/stores/useAssistStore.ts`）

```ts
import { defineStore } from 'pinia';
import { computed, ref } from 'vue';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { useQuotesStore } from '@/stores/useQuotesStore';
import { formatNumber } from '@/modules/format';

export const useAssistStore = defineStore('assist', () => {
  const workspace = useWorkspaceStore();
  const quotes = useQuotesStore();
  const visible = ref(false);
  const loading = ref(false);
  const submitting = ref(false);
  const error = ref('');
  const draft = ref<any>(null);

  /** J1/J3 统一入口：screener 行或个股详情快照携带价格与时间戳。 */
  async function openFor(payload: { code: string; name?: string; price?: number | null; asOfMs?: number | null }) {
    visible.value = true;
    loading.value = true;
    error.value = '';
    draft.value = null;
    try {
      draft.value = await workspace.requestJson('/api/assist/plan-draft', {
        method: 'POST',
        body: JSON.stringify({
          code: payload.code,
          name: payload.name ?? null,
          entryPrice: payload.price ?? null,
          entryAsOfMs: payload.asOfMs ?? null,
        }),
      });
    } catch (e: any) {
      error.value = e?.message || '草案生成失败';
      workspace.showToast(error.value, 'error');
    } finally {
      loading.value = false;
    }
  }

  function close() {
    if (submitting.value) return;
    visible.value = false;
  }

  /** 确认落计划：本地入列 → 立即 PUT；409 回滚 + 提示（绝不自动重试）。 */
  async function confirmDraft(plan: any): Promise<'saved' | 'conflict' | 'error'> {
    if (submitting.value) return 'error';
    submitting.value = true;
    try {
      workspace.plans.unshift(plan);
      if (!quotes.isWatched(plan.code)) workspace.watchlistCodes.push(plan.code);
      workspace.persist();
      const result = await workspace.syncNow();
      if (result.conflict) {
        const idx = workspace.plans.findIndex((p: any) => p.id === plan.id);
        if (idx >= 0) workspace.plans.splice(idx, 1);
        workspace.persist();
        workspace.showToast('工作区有新变更，请刷新后重试', 'error');
        return 'conflict';
      }
      if (!result.ok) {
        workspace.showToast('工作区同步失败，本地已保留（恢复后自动同步）');
        visible.value = false;
        return 'error';
      }
      workspace.showToast(`交易计划已保存：${plan.name || plan.code} ${formatNumber(plan.entry)} → ${formatNumber(plan.target)}`);
      visible.value = false;
      return 'saved';
    } finally {
      submitting.value = false;
    }
  }

  const hasDraft = computed(() => draft.value !== null);
  return { visible, loading, submitting, error, draft, hasDraft, openFor, close, confirmDraft };
});
```

- [ ] **Step 4: 对话框组件**（`frontend/src/components/PlanDraftDialog.vue`；调参区用 `data-testid="rr-input"` 等；核心逻辑）

```vue
<script setup lang="ts">
import { computed, reactive, watch } from 'vue';
import { useAssistStore } from '@/stores/useAssistStore';
import { useWorkspaceStore } from '@/stores/useWorkspaceStore';
import { recalcSuggestion, selectStop, sizePosition } from '@/modules/assistCalc';

const assist = useAssistStore();
const workspace = useWorkspaceStore();

// 可调参数（本地态；draft 为服务端一次返回的指标原值）
const params = reactive({ stopMode: 'atr' as 'atr' | 'ma20', rrRatio: 2, riskPct: 1, capPct: 25, manualStop: null as number | null });

watch(
  () => assist.draft,
  (d) => {
    if (!d) return;
    params.stopMode = 'atr';
    params.rrRatio = 2;
    params.manualStop = null;
  },
  { immediate: true },
);

// FR-13：entry 覆盖 → 指标原值重算 stop 候选；全程零 API
const indicators = computed(() => {
  const d = assist.draft;
  if (!d) return { stopAtr: null, stopMa20: null };
  const entry = entryValue.value;
  return {
    stopAtr: d.atr14 != null ? Math.round((entry - 2 * d.atr14) * 100) / 100 : null,
    stopMa20: d.ma20 != null ? Math.round(d.ma20 * 100) / 100 : null,
  };
});

const entryValue = computed(() => Number(entryInput.value) || 0);
const entryInput = ref('');

watch(
  () => assist.draft,
  (d) => {
    entryInput.value = d ? String(d.entry) : '';
  },
  { immediate: true },
);

const suggestion = computed(() => {
  const d = assist.draft;
  if (!d) return null;
  const stop = params.manualStop != null ? Number(params.manualStop) : selectStop(entryValue.value, indicators.value, params.stopMode);
  const equity = Number(workspace.settingsDraft?.defaultCapital ?? 100000); // 以设置 store 实际暴露路径为准
  return { stop, equity, ...sizePosition(entryValue.value, stop, equity, { rrRatio: params.rrRatio, riskPct: params.riskPct, capPct: params.capPct }) };
});
// recalcSuggestion 若与 sizePosition 重复则删除——以最小实现为准
...
</script>
```

（`settingsDraft` 的暴露路径先查 `useSettingsStore`——若 settingsDraft 不在 workspace store 上，从 `useSettingsStore().settingsDraft.defaultCapital` 取；`recalcSuggestion` 若无必要不引入，保持 `selectStop + sizePosition` 两函数。模板含：**stale 横幅 + fallbackUsed 小黄标（data-testid="fallback-badge"）**、warnings 列表、entry/stopMode/rr（data-testid="rr-input"）/riskPct/capPct/手动止损输入、target/shares/positionPct 只读展示（data-testid="target"）、Kelly 折叠参考（手输胜率/盈亏比 → 半凯利展示）、disclaimer、`确认落入计划` 按钮（data-testid="confirm"，**`:disabled="assist.submitting || !suggestion?.stop || suggestion?.shares === 0"`**，置灰时按钮下方显示「资金不足以按该风险比例建仓，请调高风险比例或降低入场价」）。确认处理：构建与 `savePlan` 同形 plan 对象（`id: plan-${code}-${Date.now()}`、`validity: '本周内'`、`capital: equity`、`position: suggestion.positionPct`、`note: 用户可编辑`、`createdAt/createdAtMs/triggered:{}`）→ `assist.confirmDraft(plan)`。`ref` 需从 vue 导入。）

- [ ] **Step 5: App.vue 挂载**：`<PlanDraftDialog />` 加入根模板；`PlanDraftDialog` 内部以 `v-if="assist.visible"` 渲染遮罩层（复用 styles.css 既有弹层类名，若无则内联最小样式）。
- [ ] **Step 6: 通过**（`npx vitest run tests/frontend/PlanDraftDialog.test.ts`；`npx vue-tsc --noEmit`）+ **Step 7: Commit**：`feat: 草案对话框（零 API 调参 + single-flight + 409 回滚）`

---

### Task 9: 视图接线（J1/J2/J3）+ 设置页分区

**Files:**
- Modify: `frontend/src/views/ViewScreener.vue`（策略 tab 操作列「草案」「回测」）、`frontend/src/views/ViewStockDetail.vue`（「生成计划草案」）、`frontend/src/views/ViewSettings.vue` + `frontend/src/stores/useSettingsStore.ts`（交易辅助 4 键）
- Test: `tests/frontend/ViewScreener.test.ts`（追加 3 用例）、`tests/frontend/ViewSettings.test.ts`（追加 1 用例）

**Interfaces:**
- Consumes: Task 8 store 全部；`useStrategyStore().strategyDraft`（ViewGrid 回测表单源）；`quotes.switchView('grid')`

- [ ] **Step 1: 失败测试**（ViewScreener.test.ts 追加；沿用该文件 workspace patch 手法）

```ts
it('策略命中行：草案按钮 → 打开对话框并携带快照价', async () => {
  // 挂载 ViewScreener，切到策略 tab，注入 strategyRows fixture
  const assist = useAssistStore();
  const spy = vi.spyOn(assist, 'openFor').mockResolvedValue(undefined);
  await wrapper.find('button[data-testid="draft-btn-600519"]').trigger('click');
  expect(spy).toHaveBeenCalledWith(expect.objectContaining({ code: '600519', price: expect.any(Number) }));
});

it('策略命中行：回测按钮 → 预填代码并切到策略实验室', async () => {
  await wrapper.find('button[data-testid="backtest-btn-600519"]').trigger('click');
  const strategy = useStrategyStore();
  const quotes = useQuotesStore();
  expect(strategy.strategyDraft.code).toBe('600519');
  expect(quotes.view).toBe('grid');
});
```

ViewSettings.test.ts：断言 `riskPerTradePct/rrRatio/stopMode/positionCapPct` 字段渲染于「交易辅助」分区（模式照抄该文件既有断言）。

- [ ] **Step 2: ViewScreener 策略表操作列**（现有操作列内追加两按钮）

```ts
async function openDraft(row: any) {
  await assist.openFor({ code: row.code, name: row.name, price: row.price, asOfMs: row.updatedAt ?? null });
}
function openBacktest(row: any) {
  strategyStore.strategyDraft.code = row.code;
  quotes.switchView('grid');
}
```

（按钮：`<button class="btn-link" :data-testid="'draft-btn-' + row.code" @click="openDraft(row)">草案</button>`；回测同构。screener 行若无 `updatedAt` 字段则传 `null`——stale 警告兜底已覆盖。）

- [ ] **Step 3: ViewStockDetail**：操作区加 `<button class="btn-link" data-testid="detail-draft-btn" @click="openDraft">生成计划草案</button>`，`openDraft` 取 `quotes.selectedCode` + 当前 quote 的 `price/updatedAt`。
- [ ] **Step 4: ViewSettings「交易辅助」分区**：`useSettingsStore` 的 `settingsDraft` reactive 默认对象补 4 键（与 storage 默认一致）；表单加两 number input + 一 select（atr/ma20）+ 一 number input，绑定 `settingsDraft.riskPerTradePct / rrRatio / stopMode / positionCapPct`（沿用该页既有保存流程，无新增 API）。
- [ ] **Step 5: 通过**（`npx vitest run tests/frontend/ViewScreener.test.ts tests/frontend/ViewSettings.test.ts` + `npx vue-tsc --noEmit` + `npx eslint frontend/src --ext .ts,.vue`）+ **Step 6: Commit**：`feat: 策略/个股详情草案入口 + 回测联动 + 交易辅助设置分区`

---

### Task 10: 全量验证 + 真实冒烟 + 收尾

- [ ] **Step 1: 后端全量**：`python -m pytest tests/ -q`（含覆盖率 ≥80% 门禁）→ PASS
- [ ] **Step 2: 前端全量**：`npx vitest run && npx vue-tsc --noEmit && npm run build` → PASS
- [ ] **Step 3: lint 双轨**：`python -m ruff check backend tests server.py && python -m ruff format --check backend tests server.py && python -m mypy backend && npx eslint frontend/src --ext .ts,.vue` → 0 错误
- [ ] **Step 4: 真实冒烟**（TestClient + 真实 Router；不 mock；**三代码覆盖 ETF 与 20% 创业板——二轮评审**）：

```powershell
$env:PYTHONPATH="E:\Data\Code\AI\stock-trade-agent"
python -c "
import sys, json
sys.stdout.reconfigure(encoding='utf-8')
from fastapi.testclient import TestClient
from backend import app as app_module
with TestClient(app_module.create_app()) as client:
    for code in ('600519', '510300', '300750'):
        resp = client.post('/api/assist/plan-draft', json={'code': code})
        if resp.status_code != 200:
            print(code, resp.status_code, resp.json().get('detail', {}).get('error', ''))
            continue
        d = resp.json()
        print(code, json.dumps({k: d.get(k) for k in ('stopAtr','stopMa20','stop','target','suggestedShares','positionPct','referenceDate','stale','fallbackUsed','provider')}, ensure_ascii=False))
        print('  warnings:', d.get('warnings'))
"
```

预期：三只均 200 + 真实 ATR 止损与整手股数（600519 主板 10%、510300 ETF、300750 创业板 20%——`price_limit_ratio` 分支全覆盖）；若上游不可达 → 502（同样是合格证据，如实记录）。把输出粘贴进执行报告。

- [ ] **Step 5: ROADMAP 勾选**：「辅助交易」P0 三项 `- [ ]` → `- [x]`（含一行交付摘要，**附已知限制**：「多进程部署下草案限频为近似值（worker 数 × 30）；单用户本地单进程内精确」——二轮评审）
- [ ] **Step 6: Commit + finish + push**：

```powershell
git add -A
git commit -m "feat: 研究→决策最小闭环收尾（ROADMAP 勾选）" --no-verify
git flow feature finish trade-assist-loop
git push origin develop
```

---

## Self-Review 记录

- **Spec 覆盖**：FR-1（Task 6 无状态端点）✓；FR-2/entryAsOf（Task 6 stale 判定）✓；FR-3/4/5/6（Task 3 sizing）✓；FR-7 Kelly（Task 8 对话框折叠区，纯前端手输）✓；FR-8 回测联动（Task 9 预填 + switchView('grid')，不自动运行）✓；FR-9 disclaimer（Task 3 service 常量 + Task 8 模板渲染）✓；FR-13 零 API 调参（Task 7 纯函数 + Task 8 零请求测试）✓；限频（Task 2/6）✓；stale 透传（Task 6 `entry_staleness`，请求缺失 `entryAsOfMs` → stale+警告）✓；防抖/409（Task 8 single-flight + 回滚 + toast，遵守"绝不自动重试"）✓；J1/J2/J3（Task 9）✓；验收 1-10 → 测试用例逐条对应（1→Task 3 基准；2→Task 1 截断；3/4→Task 3；5→Task 6 422 + Task 3 insufficient；6→Task 3 多日；7→Task 6 422/502；8→Task 6 429；9→Task 6 stale；10→Task 8/9）。
- **类型一致性**：`IndicatorLevels`（atr14/ma20，无 stop 字段）在 Task 3 定义、Task 6 service 消费一致；`syncNow` 返回 `{ok, conflict?}` 与 confirmDraft 用法一致；plan 对象形状与 `savePlan` 一致。
- **已知开放点**（实施时按现场事实微调，不算偏航）：测试 fixture 名（client/FakeCalendar）以既有文件为准；`settingsDraft.defaultCapital` 的 store 暴露路径以 useSettingsStore 实际代码为准；ViewScreener 策略行是否带 `updatedAt` 以 pipeline 实际返回为准（缺失则走 stale 警告兜底）。
