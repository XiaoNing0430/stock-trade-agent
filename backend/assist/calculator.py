"""交易计划草案纯计算核心（无 IO；与 frontend/src/modules/assistCalc.ts 逐字段一致）。"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from backend.indicators import atr, closed_bars, ma


@dataclass(frozen=True)
class IndicatorLevels:
    """指标截面：截至 reference_date 的已收盘数据计算结果（数据不足相应置 None，绝不造数）。"""

    reference_date: str
    closed_count: int
    atr14: float | None
    ma20: float | None
    last_close: float | None  # 截断末根收盘（涨停价提示用，二轮评审）


@dataclass(frozen=True)
class SizingResult:
    """草案仓位建议：止损 / 盈亏比目标 / 风险额 / 建议股数与仓位占比 + 中文警示。"""

    stop: float | None
    target: float | None
    stop_distance: float | None
    risk_amount: float | None
    suggested_shares: int
    position_pct: float
    warnings: list[str] = field(default_factory=list)


def indicator_levels(bars: list[dict[str, Any]], ref_date: str) -> IndicatorLevels:
    """截断至 ref_date 计算指标截面；历史数据不足时 atr14/ma20/last_close 置 None。"""
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
    last_close = float(closed[-1]["close"]) if closed and closed[-1].get("close") is not None else None
    return IndicatorLevels(
        reference_date=ref_date,
        closed_count=len(closed),
        atr14=atr14,
        ma20=ma20,
        last_close=last_close,
    )


def sizing(
    entry: float,
    levels: IndicatorLevels,
    *,
    stop_mode: str,
    equity: float,
    risk_pct: float,
    rr_ratio: float,
    cap_pct: float,
    limit_ratio: float,
) -> SizingResult:
    """按入场价现算 ATR/MA20 止损候选（≥ 入场价视为无效）、盈亏比目标与风险仓位（市值上限截断）。"""
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
    target: float | None = None
    stop_distance: float | None = None
    risk_amount: float | None = None
    shares, position_pct = 0, 0.0
    if stop is not None:
        stop_distance = round(entry - stop, 2)
        if stop_distance <= 0:
            # 亚分级价差（如 entry=10.004 / stop=10.00）四舍五入后距离为 0，等效止损不低于入场价
            # → 按双候选无效同款处置置空，防 risk_amount / stop_distance 除零 500。
            warnings.append("候选止损价均不低于入场价，已置空止损（强趋势 / 数据不足），请手动设定")
            return SizingResult(
                stop=None,
                target=None,
                stop_distance=None,
                risk_amount=round(equity * risk_pct / 100.0, 2),
                suggested_shares=0,
                position_pct=0.0,
                warnings=warnings,
            )
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
    return SizingResult(
        stop=stop,
        target=target,
        stop_distance=stop_distance,
        risk_amount=risk_amount,
        suggested_shares=max(shares, 0),
        position_pct=position_pct,
        warnings=warnings,
    )
