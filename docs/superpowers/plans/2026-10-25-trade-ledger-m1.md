# 成交台账 M1（成交 / 持仓 / 台账面板）实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让用户能录入真实成交（含无计划自由成交、分批、部分卖出），并由这些成交推导真实持仓、摊薄成本、已实现/浮动盈亏，在 ViewPlans 里看到台账。

**Architecture:** 新增独立「账本」域。成交落 `trade_fills` 表（append + 作废语义，绝不经 workspace 全量 PUT）；持仓与盈亏由纯函数 `replay_fills` 从成交重放得出，不落库；API 走既有 `api_error` 契约。前端新增 `useLedgerStore`，ViewPlans 追加「持仓与成交」面板。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy 2.0 / Alembic / Pydantic v2 / pytest（SQLite 内存库隔离存储）/ Vue 3 + TS strict / Pinia / vitest。

**契约来源:** `docs/superpowers/specs/2026-10-25-trade-ledger-design.md`（r1，已通过复审）。M1 只做该 spec 的 M1 里程碑；现金/NAV(M2)、复盘对账(M3)、组合风险 actual(M4) 不在本计划内。

## Global Constraints

- 用户可见字符串**全中文**；错误一律 `api_error(status, code, 中文短句)` → `{"detail": {"error": 中文, "code": 机器码}}`。
- **永不造数**：行情缺失 → `lastPrice: null` / 前端 `--`，并在 `disclosures` 点名；不插值、不猜。
- 卖出不得超持仓（422 `SELL_EXCEEDS_POSITION`），股票 T+1 硬校验（422 `T1_VIOLATION`），ETF 走软校验 + 不判 T+1。
- 作废保留审计：`voided_at_ms` / `void_reason`，不可恢复，不参与重放。
- 时间字段一律**毫秒 epoch 整数**（`tradedAtMs` / `createdAtMs`），上海时区固定偏移 `timezone(timedelta(hours=8))`（与 `plan_review.SHANGHAI` 同口径）。
- 排序确定性：`(traded_at_ms, created_at_ms, id)`。
- 保留既有 API 字段名；不改 `NAV_ITEMS` 顺序与数字键 1–7；不改既有 `data-testid`。
- Pinia 解构纪律：响应式状态必须 `storeToRefs`，只有函数直接解构。
- Git Flow：`git flow feature start trade-ledger`（从 `develop`）；提交主题行中文 + Conventional Commits；禁用 `--no-verify`。
- 门禁：`npm run verify`（vitest + vue-tsc + pytest，覆盖率 ≥80%）。

## File Structure

| 文件 | 职责 |
| --- | --- |
| `backend/ledger.py`（新） | 纯函数：板块申报规则、数量校验、成交重放（持仓/成本/已实现盈亏/超卖/T+1） |
| `backend/storage.py`（改） | `TradeFill` 模型 + 台账 CRUD（含幂等、作废） |
| `backend/migrations/versions/tf20261025_trade_fills.py`（新） | `trade_fills` 表迁移 |
| `backend/schemas.py`（改） | `FillIn` 请求模型 |
| `backend/app.py`（改） | `/api/fills`（GET/POST/PUT/void）、`/api/positions` |
| `frontend/src/types/models.ts`（改） | `FillRow` / `PositionRow` / `LedgerWarning` 类型 |
| `frontend/src/stores/useLedgerStore.ts`（新） | 台账/持仓拉取与写操作 |
| `frontend/src/components/FillDialog.vue`（新） | 录入/编辑成交对话框 |
| `frontend/src/views/ViewPlans.vue`（改） | 追加「持仓与成交」面板 + 计划行「确认成交」 |
| `frontend/src/modules/ledgerCsv.ts`（新） | 台账 CSV 组装（复用 `csv.ts` 的防注入单元格） |
| `frontend/src/styles.css`（改） | 台账表格与对话框样式 |
| `tests/test_ledger.py`（新） | 规则 + 重放纯函数用例 |
| `tests/test_ledger_api.py`（新） | 存储 + API 用例（SQLite 内存库 + TestClient） |
| `tests/frontend/useLedgerStore.test.ts`（新） | store 用例 |
| `tests/frontend/FillDialog.test.ts`（新） | 对话框校验用例 |
| `tests/frontend/ViewPlans.test.ts`（改） | 面板渲染 / 确认成交桥接用例 |

---

### Task 1: 板块申报规则与数量校验

**Files:**
- Create: `backend/ledger.py`
- Test: `tests/test_ledger.py`

**Interfaces:**
- Produces: `LedgerError(code: str, message: str)`；`LotRule(min_qty: int, step: int, strict: bool, t1: bool)`；
  `lot_rule(code: str) -> LotRule`；`check_buy_quantity(code: str, qty: int) -> list[dict[str, str]]`；
  `check_sell_quantity(code: str, qty: int, available: int) -> list[dict[str, str]]`；常量 `EPS = 1e-9`。

- [ ] **Step 1: 写失败用例**

```python
# tests/test_ledger.py
from __future__ import annotations

import pytest

from backend import ledger
from backend.ledger import LedgerError, check_buy_quantity, check_sell_quantity, lot_rule


@pytest.mark.parametrize(
    ("code", "qty"),
    [("600519", 100), ("600519", 1200), ("300750", 300), ("688111", 200), ("688111", 201), ("830799", 101)],
)
def test_buy_quantity_accepts_board_rules(code: str, qty: int) -> None:
    assert check_buy_quantity(code, qty) == []


@pytest.mark.parametrize(
    ("code", "qty"),
    [("600519", 150), ("600519", 0), ("600519", -100), ("300750", 250), ("688111", 199), ("830799", 99)],
)
def test_buy_quantity_rejects_board_rules(code: str, qty: int) -> None:
    with pytest.raises(LedgerError) as exc:
        check_buy_quantity(code, qty)
    assert exc.value.code == "QTY_NOT_LOT"
    assert "股" in exc.value.message


def test_etf_lot_is_soft_warning() -> None:
    assert check_buy_quantity("510300", 100) == []
    warnings = check_buy_quantity("510300", 150)
    assert [w["code"] for w in warnings] == ["LOT_WARNING"]
    assert lot_rule("510300").t1 is False


def test_convertible_bond_and_unknown_code_rejected() -> None:
    for code in ("113001", "123456", "999999"):
        with pytest.raises(LedgerError) as exc:
            lot_rule(code)
        assert exc.value.code == "CODE_UNSUPPORTED"


def test_sell_cannot_exceed_available() -> None:
    with pytest.raises(LedgerError) as exc:
        check_sell_quantity("600519", 200, 100)
    assert exc.value.code == "SELL_EXCEEDS_POSITION"
    assert "100" in exc.value.message


def test_odd_lot_must_be_sold_in_one_order() -> None:
    # 北交所持仓 50（不足 100）→ 只能一次卖完
    with pytest.raises(LedgerError) as exc:
        check_sell_quantity("830799", 40, 50)
    assert exc.value.code == "QTY_NOT_LOT"
    assert check_sell_quantity("830799", 50, 50) == []
    # 持仓 150 属正常余额，可取整卖出
    assert check_sell_quantity("830799", 100, 150) == []
```

- [ ] **Step 2: 跑用例确认失败**

Run: `python -m pytest tests/test_ledger.py -v`
Expected: FAIL（`ModuleNotFoundError: backend.ledger`）

- [ ] **Step 3: 最小实现**

```python
# backend/ledger.py
"""成交台账纯函数层：A 股申报规则、数量校验、成交重放。

契约：docs/superpowers/specs/2026-10-25-trade-ledger-design.md §2/§3。
只做纯计算，不碰 DB、不碰行情；金额单位元、数量单位股/份。
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.data_source import classify_code

EPS = 1e-9
# 沪深京可转债前缀（classify_code 会把 11x/12x 误判为深市主板股票，台账层显式挡住）
_CONVERTIBLE_PREFIXES = ("110", "111", "113", "118", "123", "127", "128")


class LedgerError(Exception):
    """台账语义错误：code 供 API 映射，message 直接面向用户（中文）。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class LotRule:
    min_qty: int
    step: int
    strict: bool  # True=硬校验（股票）；False=软提示（ETF 品种差异大）
    t1: bool  # 是否受 T+1 约束


def lot_rule(code: str) -> LotRule:
    normalized = (code or "").strip()
    if normalized.startswith(_CONVERTIBLE_PREFIXES):
        raise LedgerError("CODE_UNSUPPORTED", "可转债的申报单位与 T+0 规则未建模，暂不支持记录")
    profile = classify_code(normalized)
    board = profile["board"]
    if profile["securityType"] == "股票":
        if board == "科创板":
            return LotRule(200, 1, True, True)
        if board == "北交所":
            return LotRule(100, 1, True, True)
        if board in {"沪深主板", "创业板"}:
            return LotRule(100, 100, True, True)
    if profile["securityType"] == "ETF":
        return LotRule(100, 100, False, False)
    raise LedgerError("CODE_UNSUPPORTED", "该品种的交易规则未建模（当前仅支持沪深京股票与 ETF）")


def _require_positive_int(qty: int) -> None:
    if not isinstance(qty, int) or qty <= 0:
        raise LedgerError("QTY_NOT_LOT", "成交数量必须是正整数")


def check_buy_quantity(code: str, qty: int) -> list[dict[str, str]]:
    rule = lot_rule(code)
    _require_positive_int(qty)
    if rule.strict:
        if qty < rule.min_qty or (qty - rule.min_qty) % rule.step != 0:
            if rule.step == 1:
                hint = f"最小 {rule.min_qty} 股，超过部分按 1 股递增"
            else:
                hint = f"最小 {rule.min_qty} 股，且为 {rule.step} 股整数倍"
            raise LedgerError("QTY_NOT_LOT", f"{classify_code(code)['board']}买入须满足：{hint}")
        return []
    if qty % rule.step != 0:
        return [
            {
                "code": "LOT_WARNING",
                "message": f"{code} 申报单位可能不是 {rule.step} 的整数倍（ETF 品种规则未建模，仅提示）",
            }
        ]
    return []


def check_sell_quantity(code: str, qty: int, available: int) -> list[dict[str, str]]:
    rule = lot_rule(code)
    _require_positive_int(qty)
    if qty > available + EPS:
        raise LedgerError("SELL_EXCEEDS_POSITION", f"卖出 {qty} 股超过可用持仓 {int(available)} 股")
    if rule.strict and available < rule.min_qty and qty != available:
        raise LedgerError("QTY_NOT_LOT", f"持仓不足 {rule.min_qty} 股，零股须一次性全部卖出")
    return []
```

- [ ] **Step 4: 跑用例确认通过**

Run: `python -m pytest tests/test_ledger.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add backend/ledger.py tests/test_ledger.py
git commit -m "feat: 新增成交台账申报规则与数量校验"
```

---

### Task 2: 成交重放（持仓 / 摊薄成本 / 已实现盈亏 / 超卖 / T+1）

**Files:**
- Modify: `backend/ledger.py`
- Test: `tests/test_ledger.py`

**Interfaces:**
- Consumes: Task 1 的 `check_buy_quantity` / `check_sell_quantity` / `lot_rule` / `EPS` / `LedgerError`。
- Produces:
  - `Fill(id, code, direction, price, qty, fee=0.0, traded_at_ms=0, created_at_ms=0, plan_id=None, note="", voided_at_ms=None)`，类方法 `Fill.from_row(row: dict) -> Fill`
  - `PositionState(code, qty, cost_basis, realized_pnl)`，属性 `avg_cost: float`
  - `LedgerState(positions: dict[str, PositionState], warnings: list[dict[str, str]])`
  - `replay_fills(fills: Iterable[Fill]) -> LedgerState`
  - `shanghai_date_key(ms: int) -> str`

- [ ] **Step 1: 写失败用例**

```python
# 追加到 tests/test_ledger.py
from datetime import datetime, timedelta, timezone

from backend.ledger import Fill, replay_fills

CST = timezone(timedelta(hours=8))


def cst_ms(text: str) -> int:
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=CST).timestamp() * 1000)


def mk(code="600519", direction="buy", price=10.0, qty=100, fee=0.0, ms=None, **kw):
    stamp = cst_ms("2026-10-23 10:00") if ms is None else ms
    return Fill(
        id=kw.pop("id", f"{code}-{direction}-{stamp}-{qty}"),
        code=code,
        direction=direction,
        price=price,
        qty=qty,
        fee=fee,
        traded_at_ms=stamp,
        created_at_ms=kw.pop("created_at_ms", stamp),
        **kw,
    )


def test_weighted_cost_includes_buy_fee() -> None:
    state = replay_fills([mk(price=10.0, fee=5.0)])
    pos = state.positions["600519"]
    assert pos.qty == 100
    assert pos.cost_basis == pytest.approx(1005.0)
    assert pos.avg_cost == pytest.approx(10.05)


def test_partial_sell_realizes_pnl_with_sell_fee() -> None:
    day1, day2 = cst_ms("2026-10-23 10:00"), cst_ms("2026-10-26 10:00")
    state = replay_fills(
        [
            mk(price=10.0, qty=100, fee=5.0, ms=day1),
            mk(price=12.0, qty=100, fee=5.0, ms=day1, id="b2"),
            mk(direction="sell", price=13.0, qty=150, fee=7.0, ms=day2),
        ]
    )
    pos = state.positions["600519"]
    assert pos.qty == 50
    assert pos.realized_pnl == pytest.approx(150 * (13.0 - 11.05) - 7.0)
    assert pos.cost_basis == pytest.approx(2210.0 - 150 * 11.05)


def test_full_close_zeroes_position() -> None:
    state = replay_fills(
        [mk(price=10.0), mk(direction="sell", price=9.0, ms=cst_ms("2026-10-26 10:00"))]
    )
    pos = state.positions["600519"]
    assert pos.qty == 0 and pos.cost_basis == pytest.approx(0.0)
    assert pos.realized_pnl == pytest.approx(-100.0)


def test_sell_exceeding_position_rejected() -> None:
    with pytest.raises(LedgerError) as exc:
        replay_fills([mk(price=10.0, qty=100), mk(direction="sell", qty=200, ms=cst_ms("2026-10-26 10:00"))])
    assert exc.value.code == "SELL_EXCEEDS_POSITION"


def test_t1_blocks_same_day_sell_for_stock() -> None:
    day = cst_ms("2026-10-23 10:00")
    with pytest.raises(LedgerError) as exc:
        replay_fills([mk(price=10.0, ms=day), mk(direction="sell", price=11.0, ms=day + 3_600_000)])
    assert exc.value.code == "T1_VIOLATION"
    assert "次日" in exc.value.message


def test_etf_allows_same_day_round_trip() -> None:
    day = cst_ms("2026-10-23 10:00")
    state = replay_fills(
        [
            mk(code="510300", price=4.0, qty=100, ms=day),
            mk(code="510300", direction="sell", price=4.1, qty=100, ms=day + 3_600_000),
        ]
    )
    assert state.positions["510300"].qty == 0


def test_voided_fill_not_replayed() -> None:
    day1, day2 = cst_ms("2026-10-23 10:00"), cst_ms("2026-10-26 10:00")
    state = replay_fills(
        [mk(price=10.0, ms=day1), mk(direction="sell", qty=100, ms=day2, voided_at_ms=day2 + 1)]
    )
    assert state.positions["600519"].qty == 100


def test_odd_lot_rules_apply_on_replay() -> None:
    day1, day2 = cst_ms("2026-10-23 10:00"), cst_ms("2026-10-26 10:00")
    base = [mk(code="830799", price=10.0, qty=150, ms=day1)]
    with pytest.raises(LedgerError) as exc:
        replay_fills(base + [mk(code="830799", direction="sell", qty=40, ms=day2)])
    assert exc.value.code == "QTY_NOT_LOT"
    state = replay_fills(base + [mk(code="830799", direction="sell", qty=50, ms=day2)])
    assert state.positions["830799"].qty == 100


def test_replay_orders_by_traded_at_then_created_at() -> None:
    day1, day2 = cst_ms("2026-10-23 10:00"), cst_ms("2026-10-26 10:00")
    # 输入乱序：卖出在前，仍应按时间重放成功
    state = replay_fills([mk(direction="sell", qty=100, ms=day2), mk(price=10.0, ms=day1)])
    assert state.positions["600519"].qty == 0
```

- [ ] **Step 2: 跑用例确认失败**

Run: `python -m pytest tests/test_ledger.py -v -k "replay or weighted or t1 or voided or odd_lot or partial"`
Expected: FAIL（`ImportError: cannot import name 'Fill'`）

- [ ] **Step 3: 实现**

```python
# 追加到 backend/ledger.py
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone
from typing import Any

SHANGHAI = timezone(timedelta(hours=8))


def shanghai_date_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, SHANGHAI).date().isoformat()


@dataclass(frozen=True)
class Fill:
    id: str
    code: str
    direction: str  # buy | sell
    price: float
    qty: int
    fee: float = 0.0
    traded_at_ms: int = 0
    created_at_ms: int = 0
    plan_id: str | None = None
    note: str = ""
    voided_at_ms: int | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> Fill:
        return cls(
            id=str(row["id"]),
            code=str(row["code"]),
            direction=str(row["direction"]),
            price=float(row["price"]),
            qty=int(row["qty"]),
            fee=float(row.get("fee") or 0.0),
            traded_at_ms=int(row.get("tradedAtMs") or row.get("traded_at_ms") or 0),
            created_at_ms=int(row.get("createdAtMs") or row.get("created_at_ms") or 0),
            plan_id=row.get("planId") or row.get("plan_id") or None,
            note=str(row.get("note") or ""),
            voided_at_ms=row.get("voidedAtMs") or row.get("voided_at_ms") or None,
        )


@dataclass
class PositionState:
    code: str
    qty: int = 0
    cost_basis: float = 0.0
    realized_pnl: float = 0.0

    @property
    def avg_cost(self) -> float:
        return self.cost_basis / self.qty if self.qty else 0.0


@dataclass
class LedgerState:
    positions: dict[str, PositionState]
    warnings: list[dict[str, str]]


def replay_fills(fills: Iterable[Fill]) -> LedgerState:
    """按 (traded_at_ms, created_at_ms, id) 重放未作废成交。

    硬约束（抛 LedgerError）：数量合法性、卖出不超可用、股票 T+1、零股一次性。
    ETF 申报单位仅软提示（warnings）。
    """
    positions: dict[str, PositionState] = {}
    warnings: list[dict[str, str]] = []
    bought_by_day: dict[tuple[str, str], int] = {}
    ordered = sorted(
        (f for f in fills if not f.voided_at_ms), key=lambda f: (f.traded_at_ms, f.created_at_ms, f.id)
    )
    for fill in ordered:
        if fill.direction not in {"buy", "sell"}:
            raise LedgerError("VALIDATION_ERROR", "成交方向只能是买入或卖出")
        if fill.price <= 0:
            raise LedgerError("VALIDATION_ERROR", "成交价必须大于 0")
        if fill.fee < 0:
            raise LedgerError("VALIDATION_ERROR", "费用不能为负数")
        pos = positions.setdefault(fill.code, PositionState(fill.code))
        rule = lot_rule(fill.code)
        day = shanghai_date_key(fill.traded_at_ms)
        if fill.direction == "buy":
            warnings.extend(check_buy_quantity(fill.code, fill.qty))
            pos.qty += fill.qty
            pos.cost_basis += fill.qty * fill.price + fill.fee
            bought_by_day[(fill.code, day)] = bought_by_day.get((fill.code, day), 0) + fill.qty
            continue
        same_day_bought = bought_by_day.get((fill.code, day), 0)
        available = pos.qty - same_day_bought
        if rule.t1 and fill.qty > available + EPS:
            raise LedgerError(
                "T1_VIOLATION",
                f"当日买入的 {same_day_bought} 股不可卖出（T+1），当日可用 {max(available, 0)} 股；请核对成交日期",
            )
        warnings.extend(check_sell_quantity(fill.code, fill.qty, available))
        avg = pos.avg_cost
        pos.realized_pnl += fill.qty * (fill.price - avg) - fill.fee
        pos.qty -= fill.qty
        pos.cost_basis -= fill.qty * avg
        if pos.qty <= 0 or abs(pos.qty) < EPS:  # 清仓：归零浮点尾差
            pos.qty = 0
            pos.cost_basis = 0.0
    return LedgerState(positions=positions, warnings=warnings)
```

- [ ] **Step 4: 跑用例**

Run: `python -m pytest tests/test_ledger.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
git add backend/ledger.py tests/test_ledger.py
git commit -m "feat: 成交重放引擎推导持仓与已实现盈亏"
```

---

### Task 3: `trade_fills` 模型 / 存储函数 / Alembic 迁移

**Files:**
- Modify: `backend/storage.py`（模型加在 `TradePlan` 之后；函数加在计划存取函数附近）
- Create: `backend/migrations/versions/tf20261025_trade_fills.py`
- Test: `tests/test_ledger_api.py`

**Interfaces:**
- Produces（storage 层，均返回 camelCase dict）：
  - `_fill_row_to_dict(row: TradeFill) -> dict[str, Any]`
  - `list_trade_fills(*, code="", plan_id="", include_voided=False, limit=500, workspace_id="default") -> list[dict]`
  - `get_trade_fill(fill_id: str) -> dict | None`
  - `find_trade_fill_by_request(request_id: str) -> dict | None`
  - `create_trade_fill(data: dict) -> dict`
  - `update_trade_fill(fill_id: str, patch: dict, now_ms: int) -> dict | None`
  - `void_trade_fill(fill_id: str, reason: str, now_ms: int) -> dict | None`

- [ ] **Step 1: 写失败用例**

```python
# tests/test_ledger_api.py
from __future__ import annotations

import pytest
from backend import storage
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def factory(monkeypatch):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    storage.Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(storage, "SessionLocal", factory)
    return factory


def _fill(**kw):
    data = {
        "id": "fill_a1",
        "clientRequestId": "req_a1",
        "code": "600519",
        "direction": "buy",
        "price": 10.0,
        "qty": 100,
        "fee": 5.0,
        "tradedAtMs": 1_760_000_000_000,
        "planId": None,
        "note": "",
    }
    data.update(kw)
    return data


def test_create_and_list_fill(factory):
    row = storage.create_trade_fill(_fill())
    assert row["id"] == "fill_a1" and row["tradedAtMs"] == 1_760_000_000_000
    assert row["voidedAtMs"] is None and row["planId"] is None
    rows = storage.list_trade_fills()
    assert [r["id"] for r in rows] == ["fill_a1"]
    assert storage.find_trade_fill_by_request("req_a1")["id"] == "fill_a1"


def test_update_fill_fields(factory):
    storage.create_trade_fill(_fill())
    updated = storage.update_trade_fill("fill_a1", {"price": 10.5, "qty": 200, "note": "改"}, 1_760_000_100_000)
    assert updated["price"] == 10.5 and updated["qty"] == 200 and updated["note"] == "改"


def test_void_fill_is_idempotent_and_hidden_by_default(factory):
    storage.create_trade_fill(_fill())
    first = storage.void_trade_fill("fill_a1", "录错", 1_760_000_200_000)
    second = storage.void_trade_fill("fill_a1", "再点一次", 1_760_000_300_000)
    assert first["voidedAtMs"] == second["voidedAtMs"] == 1_760_000_200_000
    assert first["voidReason"] == "录错"
    assert storage.list_trade_fills() == []
    assert [r["id"] for r in storage.list_trade_fills(include_voided=True)] == ["fill_a1"]


def test_missing_fill_returns_none(factory):
    assert storage.update_trade_fill("nope", {"price": 1.0}, 1) is None
    assert storage.void_trade_fill("nope", "", 1) is None
```

- [ ] **Step 2: 跑用例确认失败**

Run: `python -m pytest tests/test_ledger_api.py -v`
Expected: FAIL（`AttributeError: module 'backend.storage' has no attribute 'create_trade_fill'`）

- [ ] **Step 3: 加模型**

```python
# backend/storage.py：imports 增加 BigInteger / CheckConstraint / Index
class TradeFill(Base):
    """真实成交（append + 作废语义）。独立表：绝不并入 workspace 全量快照。"""

    __tablename__ = "trade_fills"
    __table_args__ = (
        UniqueConstraint("client_request_id", name="uq_trade_fills_request_id"),
        CheckConstraint("qty > 0", name="ck_trade_fills_qty_positive"),
        CheckConstraint("direction IN ('buy','sell')", name="ck_trade_fills_direction"),
        Index("ix_trade_fills_ws_code_time", "workspace_id", "code", "traded_at_ms"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    client_request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    workspace_id: Mapped[str] = mapped_column(String(64), index=True, default="default")
    code: Mapped[str] = mapped_column(String(32), index=True)
    direction: Mapped[str] = mapped_column(String(8))
    price: Mapped[float] = mapped_column(Float)
    qty: Mapped[int] = mapped_column(Integer)
    fee: Mapped[float] = mapped_column(Float, default=0.0)
    traded_at_ms: Mapped[int] = mapped_column(BigInteger, index=True)
    plan_id: Mapped[str | None] = mapped_column(String(96), nullable=True, index=True)
    note: Mapped[str] = mapped_column(String(500), default="")
    voided_at_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    void_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at_ms: Mapped[int] = mapped_column(BigInteger, default=0)
    updated_at_ms: Mapped[int] = mapped_column(BigInteger, default=0)
```

- [ ] **Step 4: 加存储函数**

```python
# backend/storage.py（放在计划相关函数之后）
def _fill_row_to_dict(row: TradeFill) -> dict[str, Any]:
    return {
        "id": row.id,
        "clientRequestId": row.client_request_id,
        "code": row.code,
        "direction": row.direction,
        "price": row.price,
        "qty": row.qty,
        "fee": row.fee,
        "tradedAtMs": row.traded_at_ms,
        "planId": row.plan_id,
        "note": row.note,
        "voidedAtMs": row.voided_at_ms,
        "voidReason": row.void_reason,
        "createdAtMs": row.created_at_ms,
        "updatedAtMs": row.updated_at_ms,
    }


def list_trade_fills(
    *,
    code: str = "",
    plan_id: str = "",
    include_voided: bool = False,
    limit: int = 500,
    workspace_id: str = "default",
) -> list[dict[str, Any]]:
    limit = max(1, min(int(limit or 500), 2000))
    with SessionLocal() as session:
        stmt = select(TradeFill).where(TradeFill.workspace_id == workspace_id)
        if code:
            stmt = stmt.where(TradeFill.code == code)
        if plan_id:
            stmt = stmt.where(TradeFill.plan_id == plan_id)
        if not include_voided:
            stmt = stmt.where(TradeFill.voided_at_ms.is_(None))
        rows = session.scalars(
            stmt.order_by(TradeFill.traded_at_ms.desc(), TradeFill.created_at_ms.desc(), TradeFill.id.desc()).limit(limit)
        ).all()
        return [_fill_row_to_dict(r) for r in rows]


def get_trade_fill(fill_id: str) -> dict[str, Any] | None:
    with SessionLocal() as session:
        row = session.get(TradeFill, fill_id)
        return _fill_row_to_dict(row) if row else None


def find_trade_fill_by_request(request_id: str) -> dict[str, Any] | None:
    if not request_id:
        return None
    with SessionLocal() as session:
        row = session.scalar(select(TradeFill).where(TradeFill.client_request_id == request_id))
        return _fill_row_to_dict(row) if row else None


def create_trade_fill(data: dict[str, Any]) -> dict[str, Any]:
    now_ms = int(data.get("nowMs") or 0)
    row = TradeFill(
        id=str(data["id"]),
        client_request_id=data.get("clientRequestId") or None,
        workspace_id=str(data.get("workspaceId") or "default"),
        code=str(data["code"]),
        direction=str(data["direction"]),
        price=float(data["price"]),
        qty=int(data["qty"]),
        fee=float(data.get("fee") or 0.0),
        traded_at_ms=int(data["tradedAtMs"]),
        plan_id=data.get("planId") or None,
        note=str(data.get("note") or ""),
        created_at_ms=now_ms,
        updated_at_ms=now_ms,
    )
    with SessionLocal.begin() as session:
        session.add(row)
    return _fill_row_to_dict(row)


def update_trade_fill(fill_id: str, patch: dict[str, Any], now_ms: int) -> dict[str, Any] | None:
    with SessionLocal.begin() as session:
        row = session.get(TradeFill, fill_id)
        if row is None:
            return None
        if row.voided_at_ms is not None:  # 已作废不可改
            raise ValueError("voided")
        for key, column in (
            ("price", "price"),
            ("qty", "qty"),
            ("fee", "fee"),
            ("tradedAtMs", "traded_at_ms"),
            ("planId", "plan_id"),
            ("note", "note"),
        ):
            if key in patch:
                value = patch[key]
                if key == "fee":
                    value = float(value or 0.0)
                setattr(row, column, value)
        row.updated_at_ms = now_ms
        session.flush()
        return _fill_row_to_dict(row)


def void_trade_fill(fill_id: str, reason: str, now_ms: int) -> dict[str, Any] | None:
    with SessionLocal.begin() as session:
        row = session.get(TradeFill, fill_id)
        if row is None:
            return None
        if row.voided_at_ms is None:  # 重复作废保持首次时间与原因
            row.voided_at_ms = now_ms
            row.void_reason = reason or None
            row.updated_at_ms = now_ms
            session.flush()
        return _fill_row_to_dict(row)
```

- [ ] **Step 5: 加迁移**

```python
# backend/migrations/versions/tf20261025_trade_fills.py
"""trade fills ledger

Revision ID: tf20261025
Revises: c9edit20261003
Create Date: 2026-10-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "tf20261025"
down_revision: str | None = "c9edit20261003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "trade_fills",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("client_request_id", sa.String(64), nullable=True),
        sa.Column("workspace_id", sa.String(64), nullable=False, server_default="default"),
        sa.Column("code", sa.String(32), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("qty", sa.Integer(), nullable=False),
        sa.Column("fee", sa.Float(), nullable=False, server_default="0"),
        sa.Column("traded_at_ms", sa.BigInteger(), nullable=False),
        sa.Column("plan_id", sa.String(96), nullable=True),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("voided_at_ms", sa.BigInteger(), nullable=True),
        sa.Column("void_reason", sa.String(200), nullable=True),
        sa.Column("created_at_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column("updated_at_ms", sa.BigInteger(), nullable=False, server_default="0"),
        sa.UniqueConstraint("client_request_id", name="uq_trade_fills_request_id"),
        sa.CheckConstraint("qty > 0", name="ck_trade_fills_qty_positive"),
        sa.CheckConstraint("direction IN ('buy','sell')", name="ck_trade_fills_direction"),
    )
    op.create_index("ix_trade_fills_workspace_id", "trade_fills", ["workspace_id"])
    op.create_index("ix_trade_fills_code", "trade_fills", ["code"])
    op.create_index("ix_trade_fills_traded_at_ms", "trade_fills", ["traded_at_ms"])
    op.create_index("ix_trade_fills_plan_id", "trade_fills", ["plan_id"])
    op.create_index("ix_trade_fills_ws_code_time", "trade_fills", ["workspace_id", "code", "traded_at_ms"])


def downgrade() -> None:
    op.drop_table("trade_fills")
```

- [ ] **Step 6: 跑用例 + 迁移自检**

Run: `python -m pytest tests/test_ledger_api.py -v`
Expected: PASS

Run: `python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; print(ScriptDirectory.from_config(Config('alembic.ini')).get_current_head())"`
Expected: 打印 `tf20261025`（单头，无分叉）

- [ ] **Step 7: 提交**

```bash
git add backend/storage.py backend/migrations/versions/tf20261025_trade_fills.py tests/test_ledger_api.py
git commit -m "feat: 新增成交台账表与存储层"
```

---

### Task 4: `/api/fills` 端点（CRUD / 幂等 / 作废）

**Files:**
- Modify: `backend/schemas.py`（`FillIn`）、`backend/app.py`（端点 + import）
- Test: `tests/test_ledger_api.py`

**Interfaces:**
- Consumes: Task 2 的 `Fill.from_row` / `replay_fills` / `LedgerError`；Task 3 的 storage 函数。
- Produces: `FillIn`（`id/clientRequestId/code/direction/price/qty/fee/tradedAtMs/planId/note`）；
  路由 `GET/POST /api/fills`、`PUT /api/fills/{id}`、`POST /api/fills/{id}/void`。

- [ ] **Step 1: 写失败用例**

```python
# 追加到 tests/test_ledger_api.py
from fastapi.testclient import TestClient

from backend import app as app_module


@pytest.fixture()
def client(factory, monkeypatch):
    monkeypatch.setattr(storage, "SessionLocal", factory)
    with TestClient(app_module.create_app()) as test_client:
        yield test_client


def _post(client, **kw):
    payload = {
        "code": "600519",
        "direction": "buy",
        "price": 10.0,
        "qty": 100,
        "fee": 5.0,
        "tradedAtMs": 1_760_000_000_000,
        "clientRequestId": "req_x",
    }
    payload.update(kw)
    return client.post("/api/fills", json=payload)


def test_create_fill_returns_row(client):
    res = _post(client)
    assert res.status_code == 201
    body = res.json()
    assert body["fill"]["code"] == "600519" and body["fill"]["qty"] == 100
    assert body["warnings"] == []


def test_duplicate_request_id_is_idempotent(client):
    first = _post(client).json()["fill"]
    second = _post(client).json()["fill"]
    assert second["id"] == first["id"]
    assert len(client.get("/api/fills").json()["items"]) == 1


def test_request_id_payload_mismatch_rejected(client):
    _post(client)
    res = _post(client, qty=200)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "IDEMPOTENCY_MISMATCH"


def test_board_lot_violation_is_chinese_422(client):
    res = _post(client, qty=150)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert detail["code"] == "QTY_NOT_LOT" and "100 股" in detail["error"]


def test_sell_without_position_rejected(client):
    res = _post(client, direction="sell", qty=100)
    assert res.status_code == 422
    assert res.json()["detail"]["code"] == "SELL_EXCEEDS_POSITION"


def test_update_and_void_flow(client):
    fill = _post(client).json()["fill"]
    updated = client.put(f"/api/fills/{fill['id']}", json={"price": 11.0, "note": "改价"})
    assert updated.status_code == 200 and updated.json()["fill"]["price"] == 11.0
    voided = client.post(f"/api/fills/{fill['id']}/void", json={"reason": "录错"})
    assert voided.status_code == 200 and voided.json()["fill"]["voidReason"] == "录错"
    again = client.put(f"/api/fills/{fill['id']}", json={"price": 12.0})
    assert again.status_code == 422 and again.json()["detail"]["code"] == "FILL_VOIDED"
    assert client.get("/api/fills").json()["items"] == []
    assert len(client.get("/api/fills?includeVoided=true").json()["items"]) == 1


def test_unknown_fill_is_404(client):
    res = client.put("/api/fills/nope", json={"price": 1.0})
    assert res.status_code == 404 and res.json()["detail"]["code"] == "FILL_NOT_FOUND"
```

- [ ] **Step 2: 跑用例确认失败**

Run: `python -m pytest tests/test_ledger_api.py -v -k "create_fill or duplicate or void_flow"`
Expected: FAIL（404，路由未注册）

- [ ] **Step 3: 加请求模型**

```python
# backend/schemas.py
class FillIn(BaseModel):
    """POST/PUT 成交请求体；语义校验在 backend.ledger（中文文案）。"""

    model_config = ConfigDict(extra="ignore")

    id: str | None = None
    clientRequestId: str | None = None
    code: str = ""
    direction: str = "buy"
    price: float = 0.0
    qty: int = 0
    fee: float = 0.0
    tradedAtMs: int = 0
    planId: str | None = None
    note: str = ""

    @field_validator("id", "clientRequestId", "planId", mode="before")
    @classmethod
    def _blank_to_none(cls, v: Any) -> Any:
        return None if v == "" else v
```

- [ ] **Step 4: 加端点（`create_app()` 内，与其它 `@app.*` 同缩进）**

```python
# backend/app.py：import 区加 FillIn；模块级加 from backend import ledger
    def _fill_fields(payload: FillIn) -> dict[str, Any]:
        return {
            "code": (payload.code or "").strip(),
            "direction": payload.direction,
            "price": float(payload.price),
            "qty": int(payload.qty),
            "fee": float(payload.fee or 0.0),
            "tradedAtMs": int(payload.tradedAtMs),
            "planId": payload.planId,
            "note": (payload.note or "").strip()[:500],
        }

    def _replay_with(candidate: dict[str, Any] | None, *, replace_id: str | None = None):
        """把候选成交并入库内全量（含已作废，重放会自己跳过），返回 (state, fills)。"""
        rows = list_trade_fills(include_voided=True, limit=2000)
        merged = [r for r in rows if r["id"] != (replace_id or (candidate or {}).get("id"))]
        if candidate is not None:
            merged.append(candidate)
        try:
            state = ledger.replay_fills([ledger.Fill.from_row(r) for r in merged])
        except ledger.LedgerError as exc:
            raise api_error(422, exc.code, exc.message) from exc
        return state

    def _fill_payload(row: dict[str, Any]) -> dict[str, Any]:
        return {"fill": row, "planMissing": bool(row.get("planId")) and row.get("planId") not in _plan_id_set()}

    @app.get("/api/fills")
    def fills_list(
        code: str = Query(default=""),
        planId: str = Query(default=""),
        includeVoided: bool = Query(default=False),
        limit: int = Query(default=200, ge=1, le=2000),
    ) -> dict[str, Any]:
        try:
            rows = list_trade_fills(code=code, plan_id=planId, include_voided=includeVoided, limit=limit)
        except Exception as exc:
            raise api_error(502, ERR_STORAGE_UNAVAILABLE, f"成交记录读取失败: {exc}") from exc
        return {"items": rows}

    @app.post("/api/fills", status_code=201)
    def fills_create(payload: FillIn) -> dict[str, Any]:
        fields = _fill_fields(payload)
        request_id = payload.clientRequestId
        if request_id:
            existing = find_trade_fill_by_request(request_id)
            if existing is not None:
                same = all(existing.get(k) == v for k, v in fields.items())
                if not same:
                    raise api_error(422, "IDEMPOTENCY_MISMATCH", "同一请求号对应的成交内容不一致，请刷新后重试")
                return {"fill": existing, "warnings": []}
        candidate = {**fields, "id": payload.id or f"fill_{uuid4().hex[:12]}", "workspaceId": "default"}
        try:
            state = _replay_with(candidate)
        except ledger.LedgerError as exc:
            raise api_error(422, exc.code, exc.message) from exc
        try:
            row = create_trade_fill({**candidate, "nowMs": int(time.time() * 1000), "clientRequestId": request_id})
        except IntegrityError as exc:  # 并发同请求号：回读既有记录（幂等）
            existing = find_trade_fill_by_request(request_id or "")
            if existing is None:
                raise api_error(409, "IDEMPOTENCY_MISMATCH", "成交已存在，请刷新后重试") from exc
            return {"fill": existing, "warnings": []}
        except Exception as exc:
            raise api_error(502, ERR_STORAGE_UNAVAILABLE, f"成交保存失败: {exc}") from exc
        return {"fill": row, "warnings": state.warnings}

    @app.put("/api/fills/{fill_id}")
    def fills_update(fill_id: str, payload: FillIn) -> dict[str, Any]:
        current = get_trade_fill(fill_id)
        if current is None:
            raise api_error(404, "FILL_NOT_FOUND", "未知成交记录")
        if current.get("voidedAtMs"):
            raise api_error(422, "FILL_VOIDED", "该成交已作废，不能再修改（如需纠正请重新录入）")
        patch = {k: v for k, v in _fill_fields(payload).items() if k in payload.model_fields_set}
        candidate = {**current, **patch, "id": fill_id}
        try:
            state = _replay_with(candidate, replace_id=fill_id)
        except ledger.LedgerError as exc:
            raise api_error(422, exc.code, exc.message) from exc
        try:
            row = update_trade_fill(fill_id, patch, int(time.time() * 1000))
        except ValueError as exc:
            raise api_error(422, "FILL_VOIDED", "该成交已作废，不能再修改") from exc
        except Exception as exc:
            raise api_error(502, ERR_STORAGE_UNAVAILABLE, f"成交保存失败: {exc}") from exc
        if row is None:
            raise api_error(404, "FILL_NOT_FOUND", "未知成交记录")
        return {"fill": row, "warnings": state.warnings}

    @app.post("/api/fills/{fill_id}/void")
    def fills_void(fill_id: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        reason = str((payload or {}).get("reason") or "").strip()[:200]
        try:
            row = void_trade_fill(fill_id, reason, int(time.time() * 1000))
        except Exception as exc:
            raise api_error(502, ERR_STORAGE_UNAVAILABLE, f"成交作废失败: {exc}") from exc
        if row is None:
            raise api_error(404, "FILL_NOT_FOUND", "未知成交记录")
        return {"fill": row}
```

> `_plan_id_set()` 用 `{p["id"] for p in list_plans("default")}`（storage 既有函数，取不到时返回空集）。
> 注意：`_replay_with` 里 `merged` 需要 `id` 键；`candidate` 已带 `id`。

- [ ] **Step 5: 跑用例**

Run: `python -m pytest tests/test_ledger_api.py -v`
Expected: PASS

- [ ] **Step 6: 提交**

```bash
git add backend/schemas.py backend/app.py tests/test_ledger_api.py
git commit -m "feat: 新增成交台账 API（幂等与作废审计）"
```

---

### Task 5: `/api/positions` 派生持仓与盈亏

**Files:**
- Modify: `backend/app.py`、`backend/ledger.py`（`position_rows`）
- Test: `tests/test_ledger_api.py`

**Interfaces:**
- Produces: `ledger.position_rows(state, prices: dict[str, float], names: dict[str, str]) -> list[dict]`（按市值降序，缺价 `null`）；
  路由 `GET /api/positions` → `{positions, totals, warnings, disclosures}`。

- [ ] **Step 1: 写失败用例**

```python
# 追加到 tests/test_ledger_api.py
def test_positions_derived_with_quote(client, monkeypatch):
    _post(client)
    monkeypatch.setattr(
        app_module,
        "_load_quotes_for_codes",
        lambda codes: ({"600519": {"code": "600519", "name": "贵州茅台", "price": 12.0}}, []),
    )
    body = client.get("/api/positions").json()
    pos = body["positions"][0]
    assert pos["code"] == "600519" and pos["qty"] == 100
    assert pos["avgCost"] == pytest.approx(10.05)
    assert pos["lastPrice"] == 12.0 and pos["marketValue"] == pytest.approx(1200.0)
    assert pos["unrealizedPnl"] == pytest.approx(195.0)
    assert body["totals"]["marketValue"] == pytest.approx(1200.0)
    assert body["disclosures"] == []


def test_positions_without_quote_are_blank(client, monkeypatch):
    _post(client)
    monkeypatch.setattr(app_module, "_load_quotes_for_codes", lambda codes: ({}, ["600519"]))
    body = client.get("/api/positions").json()
    pos = body["positions"][0]
    assert pos["lastPrice"] is None and pos["marketValue"] is None and pos["unrealizedPnl"] is None
    assert body["totals"]["marketValue"] is None
    assert any("600519" in text for text in body["disclosures"])
```

- [ ] **Step 2: 跑用例确认失败**

Run: `python -m pytest tests/test_ledger_api.py -v -k positions`
Expected: FAIL（404）

- [ ] **Step 3: 加纯函数**

```python
# backend/ledger.py
def position_rows(
    state: LedgerState, prices: dict[str, float], names: dict[str, str]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for code, pos in state.positions.items():
        if pos.qty <= 0:
            continue
        price = prices.get(code)
        market_value = None if price is None else pos.qty * price
        rows.append(
            {
                "code": code,
                "name": names.get(code) or "",
                "qty": pos.qty,
                "avgCost": pos.avg_cost,
                "costBasis": pos.cost_basis,
                "lastPrice": price,
                "marketValue": market_value,
                "unrealizedPnl": None if market_value is None else market_value - pos.cost_basis,
                "realizedPnl": pos.realized_pnl,
            }
        )
    rows.sort(key=lambda r: (r["marketValue"] is None, -(r["marketValue"] or 0.0), r["code"]))
    return rows
```

- [ ] **Step 4: 加行情取数与端点**

```python
# backend/app.py（create_app 内，模块级辅助便于测试 monkeypatch）
    def _load_quotes_for_codes(codes: list[str]) -> tuple[dict[str, dict[str, Any]], list[str]]:
        """返回 ({code: quote}, 失败码)。行情失败绝不伪造价格。"""
        if not codes:
            return {}, []
        try:
            settings = get_workspace_settings("default")
            payload, _provider, _failed = _call_with_source_fallback(
                "realtime",
                str(settings.get("realtimeSource", "tencent")),
                bool(settings.get("fallbackEnabled", True)),
                lambda source: source.load_market(codes),
            )
        except Exception:
            return {}, list(codes)
        quotes = {str(row.get("code")): row for row in payload.get("quotes", []) if row.get("code")}
        missing = [code for code in codes if code not in quotes]
        return quotes, missing

    @app.get("/api/positions")
    def positions() -> dict[str, Any]:
        try:
            fills = list_trade_fills(limit=2000)
        except Exception as exc:
            raise api_error(502, ERR_STORAGE_UNAVAILABLE, f"成交记录读取失败: {exc}") from exc
        try:
            state = ledger.replay_fills([ledger.Fill.from_row(r) for r in fills])
        except ledger.LedgerError as exc:
            raise api_error(422, exc.code, f"台账数据不一致：{exc.message}") from exc
        codes = [code for code, pos in state.positions.items() if pos.qty > 0]
        quotes, missing = _load_quotes_for_codes(codes)
        prices = {code: float(q["price"]) for code, q in quotes.items() if q.get("price") not in (None, "")}
        names = {code: str(q.get("name") or "") for code, q in quotes.items()}
        rows = ledger.position_rows(state, prices, names)
        total_mv = sum(r["marketValue"] for r in rows if r["marketValue"] is not None)
        priced = any(r["marketValue"] is not None for r in rows)
        total_unrealized = (
            sum(r["unrealizedPnl"] for r in rows if r["unrealizedPnl"] is not None) if priced else None
        )
        disclosures: list[str] = []
        if missing:
            disclosures.append(f"以下标的最新价获取失败，市值与浮动盈亏显示为 --：{'、'.join(sorted(missing))}")
        if rows:
            disclosures.append("市值为实时不复权价口径；收益口径（含分红拆股）在净值曲线中单独披露")
        return {
            "positions": rows,
            "totals": {
                "marketValue": total_mv if priced else None,
                "unrealizedPnl": total_unrealized,
                "realizedPnl": sum(p.realized_pnl for p in state.positions.values()),
                "costBasis": sum(r["costBasis"] for r in rows),
            },
            "warnings": state.warnings,
            "disclosures": disclosures,
        }
```

> `import`：`from backend.storage import ... list_trade_fills, get_trade_fill, find_trade_fill_by_request, create_trade_fill, update_trade_fill, void_trade_fill`；
> `from sqlalchemy.exc import IntegrityError`；`from backend.ledger import ...` 用 `from backend import ledger`。

- [ ] **Step 5: 跑用例 + 提交**

Run: `python -m pytest tests/test_ledger_api.py -v`
Expected: PASS

```bash
git add backend/ledger.py backend/app.py tests/test_ledger_api.py
git commit -m "feat: 新增持仓派生端点（真实行情口径）"
```

---

### Task 6: 前端类型与 `useLedgerStore`

**Files:**
- Modify: `frontend/src/types/models.ts`
- Create: `frontend/src/stores/useLedgerStore.ts`
- Test: `tests/frontend/useLedgerStore.test.ts`

**Interfaces:**
- Produces: `FillRow`、`PositionRow`、`LedgerTotals`、`LedgerWarning` 类型；
  `useLedgerStore()` → `{ fills, positions, totals, warnings, disclosures, loading, error, load, createFill, updateFill, voidFill, positionFor }`。

- [ ] **Step 1: 写失败用例**

```ts
// tests/frontend/useLedgerStore.test.ts
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { createPinia, setActivePinia } from 'pinia';
import { useLedgerStore } from '@/stores/useLedgerStore';

const FILL = {
  id: 'fill_a1',
  clientRequestId: null,
  code: '600519',
  direction: 'buy',
  price: 10,
  qty: 100,
  fee: 5,
  tradedAtMs: 1760000000000,
  planId: null,
  note: '',
  voidedAtMs: null,
  voidReason: null,
  createdAtMs: 1,
  updatedAtMs: 1,
};

function jsonResponse(body: unknown, status = 200) {
  return { ok: status < 400, status, json: async () => body } as Response;
}

describe('useLedgerStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    vi.restoreAllMocks();
  });

  it('loads fills and positions', async () => {
    const fetchMock = vi.fn((url: string) =>
      Promise.resolve(
        url.startsWith('/api/positions')
          ? jsonResponse({
              positions: [
                {
                  code: '600519',
                  name: '贵州茅台',
                  qty: 100,
                  avgCost: 10.05,
                  costBasis: 1005,
                  lastPrice: 12,
                  marketValue: 1200,
                  unrealizedPnl: 195,
                  realizedPnl: 0,
                },
              ],
              totals: { marketValue: 1200, unrealizedPnl: 195, realizedPnl: 0, costBasis: 1005 },
              warnings: [],
              disclosures: [],
            })
          : jsonResponse({ items: [FILL] })
      )
    );
    vi.stubGlobal('fetch', fetchMock);
    const store = useLedgerStore();
    await store.load();
    expect(store.fills).toHaveLength(1);
    expect(store.positions[0].avgCost).toBe(10.05);
    expect(store.positionFor('600519')?.qty).toBe(100);
    expect(store.error).toBe('');
  });

  it('createFill posts and reloads', async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === '/api/fills' && init?.method === 'POST') {
        expect(JSON.parse(String(init.body)).qty).toBe(100);
        return Promise.resolve(jsonResponse({ fill: FILL, planMissing: false }, 201));
      }
      return Promise.resolve(
        url.startsWith('/api/positions')
          ? jsonResponse({ positions: [], totals: {}, warnings: [], disclosures: [] })
          : jsonResponse({ items: [FILL] })
      );
    });
    vi.stubGlobal('fetch', fetchMock);
    const store = useLedgerStore();
    const result = await store.createFill({
      code: '600519',
      direction: 'buy',
      price: 10,
      qty: 100,
      fee: 5,
      tradedAtMs: 1760000000000,
    });
    expect(result.ok).toBe(true);
    expect(store.fills).toHaveLength(1);
  });

  it('surfaces backend chinese error', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(jsonResponse({ detail: { error: '卖出 200 股超过可用持仓 100 股', code: 'SELL_EXCEEDS_POSITION' } }, 422))
      )
    );
    const store = useLedgerStore();
    const result = await store.createFill({
      code: '600519',
      direction: 'sell',
      price: 10,
      qty: 200,
      fee: 0,
      tradedAtMs: 1760000000000,
    });
    expect(result.ok).toBe(false);
    expect(result.message).toContain('超过可用持仓');
  });
});
```

- [ ] **Step 2: 跑用例确认失败**

Run: `npx vitest run tests/frontend/useLedgerStore.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 加类型**

```ts
// frontend/src/types/models.ts
export interface FillRow {
  id: string;
  clientRequestId: string | null;
  code: string;
  direction: 'buy' | 'sell';
  price: number;
  qty: number;
  fee: number;
  tradedAtMs: number;
  planId: string | null;
  note: string;
  voidedAtMs: number | null;
  voidReason: string | null;
  createdAtMs: number;
  updatedAtMs: number;
}

export interface FillInput {
  code: string;
  direction: 'buy' | 'sell';
  price: number;
  qty: number;
  fee: number;
  tradedAtMs: number;
  planId?: string | null;
  note?: string;
  clientRequestId?: string;
}

export interface PositionRow {
  code: string;
  name: string;
  qty: number;
  avgCost: number;
  costBasis: number;
  lastPrice: number | null;
  marketValue: number | null;
  unrealizedPnl: number | null;
  realizedPnl: number;
}

export interface LedgerWarning {
  code: string;
  message: string;
}

export interface LedgerTotals {
  marketValue?: number | null;
  unrealizedPnl?: number | null;
  realizedPnl?: number;
  costBasis?: number;
}
```

- [ ] **Step 4: 加 store**

```ts
// frontend/src/stores/useLedgerStore.ts
import { computed, ref } from 'vue';
import { defineStore } from 'pinia';
import { requestJson } from '@/api/client';
import type { FillInput, FillRow, LedgerTotals, LedgerWarning, PositionRow } from '@/types/models';

type WriteResult = { ok: boolean; message?: string; warnings?: LedgerWarning[] };

export const useLedgerStore = defineStore('ledger', () => {
  const fills = ref<FillRow[]>([]);
  const positions = ref<PositionRow[]>([]);
  const totals = ref<LedgerTotals>({});
  const warnings = ref<LedgerWarning[]>([]);
  const disclosures = ref<string[]>([]);
  const loading = ref(false);
  const error = ref('');

  const positionFor = computed(() => (code: string) => positions.value.find((p) => p.code === code) ?? null);

  async function load() {
    loading.value = true;
    error.value = '';
    try {
      const [fillBody, positionBody] = await Promise.all([
        requestJson<{ items: FillRow[] }>('/api/fills?limit=500'),
        requestJson<{
          positions: PositionRow[];
          totals: LedgerTotals;
          warnings: LedgerWarning[];
          disclosures: string[];
        }>('/api/positions'),
      ]);
      fills.value = fillBody.items ?? [];
      positions.value = positionBody.positions ?? [];
      totals.value = positionBody.totals ?? {};
      warnings.value = positionBody.warnings ?? [];
      disclosures.value = positionBody.disclosures ?? [];
      return { ok: true };
    } catch (exc) {
      error.value = exc instanceof Error ? exc.message : '台账加载失败';
      return { ok: false, message: error.value };
    } finally {
      loading.value = false;
    }
  }

  async function createFill(input: FillInput): Promise<WriteResult> {
    try {
      const body = await requestJson<{ fill: FillRow; warnings?: LedgerWarning[] }>('/api/fills', {
        method: 'POST',
        body: JSON.stringify({ ...input, clientRequestId: input.clientRequestId ?? `ui-${Date.now()}-${Math.random().toString(16).slice(2, 8)}` }),
      });
      await load();
      return { ok: true, warnings: body.warnings ?? [] };
    } catch (exc) {
      return { ok: false, message: exc instanceof Error ? exc.message : '成交保存失败' };
    }
  }

  async function updateFill(id: string, patch: Partial<FillInput>): Promise<WriteResult> {
    try {
      await requestJson<{ fill: FillRow }>(`/api/fills/${encodeURIComponent(id)}`, {
        method: 'PUT',
        body: JSON.stringify(patch),
      });
      await load();
      return { ok: true };
    } catch (exc) {
      return { ok: false, message: exc instanceof Error ? exc.message : '成交保存失败' };
    }
  }

  async function voidFill(id: string, reason = ''): Promise<WriteResult> {
    try {
      await requestJson<{ fill: FillRow }>(`/api/fills/${encodeURIComponent(id)}/void`, {
        method: 'POST',
        body: JSON.stringify({ reason }),
      });
      await load();
      return { ok: true };
    } catch (exc) {
      return { ok: false, message: exc instanceof Error ? exc.message : '作废失败' };
    }
  }

  return { fills, positions, totals, warnings, disclosures, loading, error, positionFor, load, createFill, updateFill, voidFill };
});
```

- [ ] **Step 5: 跑用例 + 提交**

Run: `npx vitest run tests/frontend/useLedgerStore.test.ts`
Expected: PASS

```bash
git add frontend/src/types/models.ts frontend/src/stores/useLedgerStore.ts tests/frontend/useLedgerStore.test.ts
git commit -m "feat: 新增前端台账 store 与类型"
```

---

### Task 7: 「持仓与成交」面板 + 录入对话框

**Files:**
- Create: `frontend/src/components/FillDialog.vue`
- Modify: `frontend/src/views/ViewPlans.vue`、`frontend/src/styles.css`
- Test: `tests/frontend/FillDialog.test.ts`、`tests/frontend/ViewPlans.test.ts`

**Interfaces:**
- Consumes: Task 6 的 store 与类型。
- Produces: `FillDialog` props `{ open: boolean; preset?: Partial<FillInput> }`，emits `update:open`、`saved`。

- [ ] **Step 1: 写失败用例**

```ts
// tests/frontend/FillDialog.test.ts
import { describe, expect, it, vi } from 'vitest';
import { mount } from '@vue/test-utils';
import FillDialog from '@/components/FillDialog.vue';

function mountDialog(props: Record<string, unknown> = {}) {
  return mount(FillDialog, {
    props: { open: true, ...props },
    global: { stubs: { teleport: true } },
  });
}

describe('FillDialog', () => {
  it('renders chinese labels and prefilled plan values', () => {
    const wrapper = mountDialog({ preset: { code: '600519', direction: 'buy', price: 10, qty: 100 } });
    expect(wrapper.text()).toContain('录入成交');
    expect((wrapper.get('[data-testid="fill-code"]').element as HTMLInputElement).value).toBe('600519');
    expect((wrapper.get('[data-testid="fill-qty"]').element as HTMLInputElement).value).toBe('100');
  });

  it('blocks empty code or non-positive qty with chinese hint', async () => {
    const wrapper = mountDialog();
    await wrapper.get('[data-testid="fill-submit"]').trigger('click');
    expect(wrapper.text()).toContain('请填写证券代码');
    await wrapper.get('[data-testid="fill-code"]').setValue('600519');
    await wrapper.get('[data-testid="fill-qty"]').setValue('0');
    await wrapper.get('[data-testid="fill-submit"]').trigger('click');
    expect(wrapper.text()).toContain('成交数量必须是正整数');
  });

  it('emits submit payload with ms timestamp', async () => {
    const wrapper = mountDialog({ preset: { code: '600519', price: 10, qty: 100 } });
    await wrapper.get('[data-testid="fill-submit"]').trigger('click');
    const payload = wrapper.emitted('submit')?.[0]?.[0] as { code: string; tradedAtMs: number };
    expect(payload.code).toBe('600519');
    expect(typeof payload.tradedAtMs).toBe('number');
  });
});
```

- [ ] **Step 2: 跑用例确认失败**

Run: `npx vitest run tests/frontend/FillDialog.test.ts`
Expected: FAIL（组件不存在）

- [ ] **Step 3: 实现对话框**

要点（照 `PlanDraftDialog.vue` 的对话框外壳与 `useOverlayA11y` 用法写）：
- 字段：方向（买/卖 `select`）、代码、价格、数量、总费用、成交时间（`datetime-local`，默认当前本地时间）、关联计划（可选，来自 `workspace.plans`）、备注。
- 「按费率估算」按钮：佣金 `max(5, 金额×0.0003)` + 卖出股票印花税 `金额×0.0005` + 沪市股票过户费 `金额×0.00001`，只填建议值不自动覆盖；旁边注明「估算仅供参考，以券商账单为准」。
- 前端内联校验（中文、不提交）：代码必填、价格 > 0、数量为正整数；其余交后端（含板块规则）。
- `data-testid`：`fill-code` / `fill-qty` / `fill-price` / `fill-fee` / `fill-time` / `fill-submit`。

```vue
<!-- frontend/src/components/FillDialog.vue（关键脚本部分） -->
<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { FillInput } from '@/types/models';

const props = defineProps<{ open: boolean; preset?: Partial<FillInput> }>();
const emit = defineEmits<{ 'update:open': [boolean]; submit: [FillInput] }>();

const code = ref('');
const direction = ref<'buy' | 'sell'>('buy');
const price = ref<number | ''>('');
const qty = ref<number | ''>('');
const fee = ref<number | ''>(0);
const localTime = ref('');
const note = ref('');
const planId = ref('');
const hint = ref('');

function toLocalInput(ms: number) {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

watch(
  () => props.open,
  (open) => {
    if (!open) return;
    code.value = props.preset?.code ?? '';
    direction.value = props.preset?.direction ?? 'buy';
    price.value = props.preset?.price ?? '';
    qty.value = props.preset?.qty ?? '';
    fee.value = props.preset?.fee ?? 0;
    planId.value = props.preset?.planId ?? '';
    localTime.value = toLocalInput(props.preset?.tradedAtMs ?? Date.now());
    note.value = '';
    hint.value = '';
  },
  { immediate: true }
);

const amount = computed(() => Number(price.value || 0) * Number(qty.value || 0));

function estimateFee() {
  const value = amount.value;
  if (!value) return;
  const commission = Math.max(5, value * 0.0003);
  const stamp = direction.value === 'sell' && code.value.startsWith('6') ? value * 0.0005 : 0;
  const transfer = code.value.startsWith('6') ? value * 0.00001 : 0;
  fee.value = Number((commission + stamp + transfer).toFixed(2));
}

function submit() {
  hint.value = '';
  if (!code.value.trim()) return void (hint.value = '请填写证券代码');
  if (!(Number(price.value) > 0)) return void (hint.value = '成交价必须大于 0');
  if (!Number.isInteger(Number(qty.value)) || Number(qty.value) <= 0)
    return void (hint.value = '成交数量必须是正整数');
  if (!localTime.value) return void (hint.value = '请选择成交时间');
  const tradedAtMs = new Date(localTime.value).getTime();
  if (!Number.isFinite(tradedAtMs) || tradedAtMs > Date.now() + 86_400_000)
    return void (hint.value = '成交时间不能晚于明天');
  emit('submit', {
    code: code.value.trim(),
    direction: direction.value,
    price: Number(price.value),
    qty: Number(qty.value),
    fee: Number(fee.value || 0),
    tradedAtMs,
    planId: planId.value || null,
    note: note.value.trim(),
  });
}
</script>
```

- [ ] **Step 4: 跑用例**

Run: `npx vitest run tests/frontend/FillDialog.test.ts`
Expected: PASS

- [ ] **Step 5: 加 ViewPlans 面板（含断言）**

在 `ViewPlans.vue` 的 `<section class="review-panel surface">` **之前**插入：

```vue
<section class="ledger-panel surface" data-testid="ledger-panel">
  <div class="surface-heading">
    <div><h2>持仓与成交</h2><p class="surface-subtitle">真实成交推导；市值为实时不复权价口径</p></div>
    <button class="ghost-button" type="button" data-testid="fill-new" @click="openFillDialog()">录入成交</button>
  </div>
  <div v-if="ledger.positions.length" class="ledger-table" data-testid="ledger-positions">
    <div class="ledger-row ledger-row-head">
      <span>标的</span><span>数量</span><span>摊薄成本</span><span>现价</span><span>浮动盈亏</span><span>已实现</span>
    </div>
    <div v-for="row in ledger.positions" :key="row.code" class="ledger-row">
      <span>{{ row.name || row.code }} · {{ row.code }}</span>
      <span>{{ row.qty }}</span>
      <span>{{ row.avgCost.toFixed(3) }}</span>
      <span>{{ row.lastPrice === null ? '--' : row.lastPrice.toFixed(2) }}</span>
      <span :class="row.unrealizedPnl === null ? '' : row.unrealizedPnl >= 0 ? 'is-up' : 'is-down'">
        {{ row.unrealizedPnl === null ? '--' : formatSigned(row.unrealizedPnl) }}
      </span>
      <span :class="row.realizedPnl >= 0 ? 'is-up' : 'is-down'">{{ formatSigned(row.realizedPnl) }}</span>
    </div>
  </div>
  <p v-else class="empty-hint">还没有成交记录。录入第一笔成交后，这里会显示真实持仓与盈亏。</p>
  <div class="ledger-table" data-testid="ledger-fills">
    <div class="ledger-row ledger-row-head">
      <span>时间</span><span>方向</span><span>代码</span><span>价格</span><span>数量</span><span>费用</span><span>操作</span>
    </div>
    <div v-for="fill in ledger.fills" :key="fill.id" :class="['ledger-row', fill.voidedAtMs ? 'is-voided' : '']">
      <span>{{ formatTime(fill.tradedAtMs) }}</span>
      <span>{{ fill.direction === 'buy' ? '买入' : '卖出' }}</span>
      <span>{{ fill.code }}</span>
      <span>{{ fill.price.toFixed(2) }}</span>
      <span>{{ fill.qty }}</span>
      <span>{{ fill.fee.toFixed(2) }}</span>
      <span>
        <button v-if="!fill.voidedAtMs" class="link-button" type="button" data-testid="fill-void" @click="voidFill(fill.id)">作废</button>
        <span v-else>已作废</span>
      </span>
    </div>
  </div>
  <p v-for="text in ledger.disclosures" :key="text" class="muted-note">{{ text }}</p>
  <p v-for="warn in ledger.warnings" :key="warn.message" class="muted-note is-warn">{{ warn.message }}</p>
</section>
<FillDialog :open="fillDialogOpen" :preset="fillPreset" @update:open="fillDialogOpen = $event" @submit="saveFill" />
```

脚本追加（`<script setup>` 内）：

```ts
import { useLedgerStore } from '@/stores/useLedgerStore';
import FillDialog from '@/components/FillDialog.vue';
import type { FillInput } from '@/types/models';

const ledger = useLedgerStore();
const { positions: ledgerPositions, fills: ledgerFills, disclosures: ledgerDisclosures, warnings: ledgerWarnings } =
  storeToRefs(ledger);
const fillDialogOpen = ref(false);
const fillPreset = ref<Partial<FillInput>>({});

function openFillDialog(preset: Partial<FillInput> = {}) {
  fillPreset.value = preset;
  fillDialogOpen.value = true;
}

async function saveFill(input: FillInput) {
  const result = await ledger.createFill(input);
  if (!result.ok) return showToast(result.message || '成交保存失败', 'error');
  fillDialogOpen.value = false;
  showToast('成交已保存');
}

async function voidFill(id: string) {
  const result = await ledger.voidFill(id, '用户作废');
  showToast(result.ok ? '成交已作废' : result.message || '作废失败', result.ok ? 'info' : 'error');
}

function formatSigned(value: number) {
  return `${value >= 0 ? '+' : ''}${value.toFixed(2)}`;
}

onMounted(() => {
  void ledger.load();
});
```

`ViewPlans.test.ts` 追加：mock `useLedgerStore().load` 为 noop（避免真 fetch），断言 `[data-testid="ledger-panel"]` 存在且空态文案含「还没有成交记录」。

- [ ] **Step 6: 跑用例 + 提交**

Run: `npx vitest run tests/frontend/ViewPlans.test.ts tests/frontend/FillDialog.test.ts`
Expected: PASS

```bash
git add frontend/src/components/FillDialog.vue frontend/src/views/ViewPlans.vue frontend/src/styles.css tests/frontend
git commit -m "feat: ViewPlans 新增持仓与成交面板"
```

---

### Task 8: 计划「确认成交」桥接 + 台账 CSV

**Files:**
- Modify: `frontend/src/views/ViewPlans.vue`、`frontend/src/modules/ledgerCsv.ts`（新建）
- Test: `tests/frontend/ledgerCsv.test.ts`（新建）、`tests/frontend/ViewPlans.test.ts`

**Interfaces:**
- Produces: `buildFillsCsv(rows: FillRow[]): string`；计划卡片按钮 `data-testid="plan-fill"` 打开预填对话框。

- [ ] **Step 1: 写失败用例**

```ts
// tests/frontend/ledgerCsv.test.ts
import { describe, expect, it } from 'vitest';
import { buildFillsCsv } from '@/modules/ledgerCsv';

const ROW = {
  id: 'fill_a1',
  clientRequestId: null,
  code: '600519',
  direction: 'buy' as const,
  price: 10,
  qty: 100,
  fee: 5,
  tradedAtMs: 1760000000000,
  planId: 'plan-1',
  note: '=cmd|calc',
  voidedAtMs: null,
  voidReason: null,
  createdAtMs: 1,
  updatedAtMs: 1,
};

describe('buildFillsCsv', () => {
  it('includes header and localized direction', () => {
    const csv = buildFillsCsv([ROW]);
    expect(csv.split('\n')[0]).toContain('成交时间');
    expect(csv).toContain('买入');
  });

  it('neutralizes spreadsheet formula injection', () => {
    expect(buildFillsCsv([ROW])).toContain("'=cmd|calc");
  });
});
```

- [ ] **Step 2: 跑用例确认失败**

Run: `npx vitest run tests/frontend/ledgerCsv.test.ts`
Expected: FAIL（模块不存在）

- [ ] **Step 3: 实现**

```ts
// frontend/src/modules/ledgerCsv.ts
import { buildCsv, csvCell } from './csv';
import type { FillRow } from '@/types/models';

function stamp(ms: number): string {
  const d = new Date(ms);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

export function buildFillsCsv(rows: FillRow[]): string {
  const header = ['成交时间', '方向', '代码', '价格', '数量', '费用', '金额', '关联计划', '状态', '备注'];
  const body = rows.map((row) => [
    stamp(row.tradedAtMs),
    row.direction === 'buy' ? '买入' : '卖出',
    row.code,
    row.price.toFixed(2),
    String(row.qty),
    row.fee.toFixed(2),
    (row.price * row.qty).toFixed(2),
    row.planId ?? '',
    row.voidedAtMs ? '已作废' : '有效',
    csvCell(row.note),
  ]);
  return buildCsv(header, body);
}
```

> `buildCsv` 已对每个单元格调用 `csvCell`（含公式注入防护），因此备注不要重复包裹——若 `buildCsv` 内部已转义，则 `body` 里直接传 `row.note`。实现时以 `csv.ts` 现有行为为准，用例断言 `'=cmd|calc` 即可。

按钮（计划卡片操作区）：

```vue
<button
  class="ghost-button"
  type="button"
  data-testid="plan-fill"
  @click="openFillDialog({ code: plan.code, direction: plan.direction, price: plan.entry, qty: plannedQty(plan) })"
>
  确认成交
</button>
```

```ts
function plannedQty(plan: Plan) {
  const budget = (Number(plan.capital) * Number(plan.position)) / 100;
  return Math.max(100, Math.floor(budget / Math.max(plan.entry, 0.01) / 100) * 100);
}
```

台账区导出按钮：`<button class="ghost-button" @click="exportFills">导出 CSV</button>` → `downloadCsv('成交台账.csv', buildFillsCsv(ledger.fills))`。

- [ ] **Step 4: 跑用例 + 提交**

Run: `npx vitest run tests/frontend/ledgerCsv.test.ts tests/frontend/ViewPlans.test.ts`
Expected: PASS

```bash
git add frontend/src/modules/ledgerCsv.ts frontend/src/views/ViewPlans.vue tests/frontend
git commit -m "feat: 计划确认成交入口与台账 CSV 导出"
```

---

### Task 9: 文档与本批门禁

**Files:**
- Modify: `CHANGELOG.md`（`## [未发布]` 追加）、`ROADMAP.md`（记录 M1 已做 / M2–M4 待做）、`AGENTS.md`（表数量与新增模块）

- [ ] **Step 1: 文档更新**

- `CHANGELOG.md` → `## [未发布]` 下加「新增：真实成交台账（录入/作废/持仓与已实现盈亏派生）」。
- `ROADMAP.md` → 在「已知限制」中把「复盘/组合风险无成交记录」改写为**带日期**的进展注记：M1 已补台账，M2–M4 待做。
- `AGENTS.md` → `backend/ledger.py` 进项目布局；`storage.py` 表数量 18 → 19。

- [ ] **Step 2: 全量门禁**

Run: `npm run verify`
Expected: exit 0（vitest / vue-tsc / pytest / 覆盖率 ≥80%）

Run: `python -m ruff check backend tests server.py && python -m ruff format --check backend tests server.py && python -m mypy backend`
Expected: 全部通过

- [ ] **Step 3: 提交**

```bash
git add CHANGELOG.md ROADMAP.md AGENTS.md
git commit -m "docs: 补记成交台账 M1 交付与后续里程碑"
```

---

## Self-Review

**Spec 覆盖（M1 范围）**

| spec 条目 | 落点 |
| --- | --- |
| §1.1 `trade_fills` 字段/索引/约束 | Task 3 |
| §2 摊薄成本 / 部分卖出 / 清仓尾差 / 超卖 | Task 2 |
| §3 板块规则 / ETF 软校验 / 股票 T+1 / 零股 / 代码范围 | Task 1 + 2 |
| §5 `GET/POST/PUT/void /api/fills`、幂等、`planMissing`、错误码 | Task 4 |
| §5 `GET /api/positions`（行情缺失 `--` + 披露） | Task 5 |
| §8 前端 store / 面板 / 录入对话框 / 确认成交 / CSV | Task 6–8 |
| §9 M1 验收（纯函数矩阵、API 中文、679 测试零改动） | Task 1–9 |

**明确不在本计划**：§1.2 `cash_flows`、§4 现金与 NAV、§6 复盘 `actual`、§7 组合风险 `actual`（M2–M4 另出计划）。

**类型一致性自检**：`Fill` 字段名（`traded_at_ms`/`created_at_ms`/`voided_at_ms`）↔ storage dict（`tradedAtMs`/`createdAtMs`/`voidedAtMs`）由 `Fill.from_row` 双向兜底；store 的 `FillInput.tradedAtMs` ↔ `FillIn.tradedAtMs` 一致；`position_rows` 输出键与 `PositionRow` 一致。

**已知取舍**：`_replay_with` 每次写操作重放全表（单用户、量级数百笔，O(n) 可接受）；不引入增量维护，避免第二份事实源。
