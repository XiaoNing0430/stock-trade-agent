"""成交台账纯函数层：A 股申报规则、数量校验、成交重放。

契约：docs/superpowers/specs/2026-10-25-trade-ledger-design.md §2/§3。
只做纯计算，不碰 DB、不碰行情；金额单位元、数量单位股/份。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.data_source import classify_code

EPS = 1e-9
SHANGHAI = timezone(timedelta(hours=8))
# 沪深京可转债前缀（classify_code 会把 11x/12x 判成深市主板股票，台账层显式挡住）
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
        raise LedgerError("QTY_NOT_LOT", "成交数量必须是正整数（单位：股/份）")


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
    ordered = sorted((f for f in fills if not f.voided_at_ms), key=lambda f: (f.traded_at_ms, f.created_at_ms, f.id))
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
        available = pos.qty if not rule.t1 else pos.qty - same_day_bought
        if fill.qty > pos.qty + EPS:
            # 超卖优先报（T+1 只在「有持仓但当日不可卖」时才有意义）
            check_sell_quantity(fill.code, fill.qty, available)
        if rule.t1 and fill.qty > available + EPS:
            raise LedgerError(
                "T1_VIOLATION",
                f"当日买入的 {same_day_bought} 股当日不可卖出（T+1，需次日才可卖），当日可用 {max(available, 0)} 股；"
                "请核对成交日期",
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
