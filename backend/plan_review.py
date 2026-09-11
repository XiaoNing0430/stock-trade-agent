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
    prior = [b for b in bars if b["date"] <= start_date]  # ≤ 创建日：当日 bar 可作 prevClose（brief 用例钉死）
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
        low = float(bar["low"])
        high = float(bar["high"])
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
