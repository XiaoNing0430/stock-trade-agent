"""成交台账纯函数层：A 股申报规则、数量校验、成交重放。

契约：docs/superpowers/specs/2026-10-25-trade-ledger-design.md §2/§3。
只做纯计算，不碰 DB、不碰行情；金额单位元、数量单位股/份。
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.data_source import classify_code

EPS = 1e-9
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
