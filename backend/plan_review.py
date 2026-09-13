"""计划绩效复盘——设计口径回放引擎。纯函数；bars 获取与聚合在编排层（Task 5）。

契约：docs/superpowers/specs/2026-09-09-plan-review-spec.md r3.1（决议 3/4/6/9/10/17/20）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.data_source import price_limit_ratio

SHANGHAI = timezone(timedelta(hours=8))
review_logger = logging.getLogger("atlas.review")  # 与 app 复盘端点同通道：取数失败/成功留痕


def shanghai_date_str(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, SHANGHAI).strftime("%Y-%m-%d")


def validity_expiry_date(created_ms: int, validity: str) -> str:
    """镜像前端 planUtils.validityExpiry：本月内=创建月月末；本周内=ISO 周日；其他未知=创建当日。

    例外（有意分歧，以 spec 边界表为准）：长期/空 → "9999-12-31" 哨兵，
    经 slice_window 的 min(expiry, today) 收口为"窗口终点=今天"（评审非 Blocker ①）。
    """
    base = datetime.fromtimestamp(created_ms / 1000, SHANGHAI)
    if validity == "本月内":
        nxt = (
            base.replace(year=base.year + 1, month=1, day=1)
            if base.month == 12
            else base.replace(month=base.month + 1, day=1)
        )
        end = nxt - timedelta(days=1)
    elif validity == "本周内":
        end = base + timedelta(days=(6 - base.weekday()) % 7)  # Monday=0 → 周日差 (6-wd)
    elif validity in ("长期", ""):
        return "9999-12-31"
    else:
        end = base
    return end.strftime("%Y-%m-%d")


def slice_window(
    bars: list[dict[str, Any]], created_ms: int, validity: str, today: str | None = None
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, bool]:
    """回放窗切片。bars 按 date 升序（编排层保证不含未收盘 bar）。

    返回 (窗口bars, 窗口前一根bar（prevClose 用，可 None）, 窗口是否已闭合)。
    窗口 = 创建日 < barDate ≤ min(过期日, 今天) 且 barDate < 今天（B2：未收盘 bar 一律排除）。
    """
    today = today or shanghai_date_str(int(datetime.now(SHANGHAI).timestamp() * 1000))
    start_date = shanghai_date_str(created_ms)  # 创建当日 bar 不参与（决议 9）
    end_date = validity_expiry_date(created_ms, validity)
    end_date = min(end_date, today)
    prior = [b for b in bars if b["date"] <= start_date]  # ≤ 创建日：当日 bar 可作 prevClose（brief 用例钉死）
    window = [b for b in bars if start_date < b["date"] <= end_date and b["date"] < today]
    closed = end_date < today  # 过期日 < 今天 → 窗口已闭合
    return window, (prior[-1] if prior else None), closed


def _board_pct(code: str) -> float:
    """板块涨跌幅：北交所 30%、创业板/科创板 20%、其他 10%（AGENTS 涨跌幅纪律）。

    经 data_source.price_limit_ratio（classify_code 口径，评审决议 2）单一出处。
    """
    return price_limit_ratio(code or "")


def _limit_prices(prev_close: float | None, pct: float) -> tuple[float, float] | None:
    if prev_close is None or prev_close <= 0:
        return None
    return round(prev_close * (1 + pct), 2), round(prev_close * (1 - pct), 2)


def replay_plan(
    plan: dict[str, Any], bars: list[dict[str, Any]], fee_rate: float, today: str | None = None
) -> dict[str, Any]:
    entry = float(plan.get("entry") or 0)
    stop = float(plan.get("stop") or 0)
    target = float(plan.get("target") or 0)
    direction = plan.get("direction") or "buy"
    rec: dict[str, Any] = {
        "planId": plan.get("id"),
        "code": plan.get("code"),
        "source": plan.get("source") or "legacy",
        "direction": direction,
        "entry": entry,
        "stop": stop,
        "target": target,
        "validity": plan.get("validity") or "",
        "status": plan.get("status") or "执行中",
        "outcome": "invalid",
        "rValue": None,
        "netR": None,
        "costR": None,
        "entryDate": None,
        "exitDate": None,
        "ambiguous": False,
        "gapFill": False,
        "limitDeferred": False,
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

    prev_close = float(prev_bar["close"]) if prev_bar else None  # prev_bar 来自 slice_window
    for bar in window:
        low = float(bar["low"])
        high = float(bar["high"])
        close = float(bar["close"])
        open_ = float(bar["open"])
        volume = float(bar.get("volume") or 0)
        if volume <= 0:  # 停牌：无成交可能，prev_close 不更新
            continue
        limits = _limit_prices(prev_close, _board_pct(str(plan.get("code") or "")))
        one_price = high == low
        limit_up_day = bool(limits and one_price and close >= limits[0])
        limit_down_day = bool(limits and one_price and close <= limits[1])
        prev_close = float(bar["close"])
        if not entered:
            if limit_up_day:  # 涨停一字板：买入不可成交 → 顺延（决议 20）
                rec["limitDeferred"] = True
                continue
            if low <= entry:  # r3.1：跳空穿越亦触及，成交价恒记计划 entry
                entered = True
                rec["entryDate"] = bar["date"]
            else:
                continue
        hit_stop = low <= stop
        hit_target = high >= target
        # 跳空成交模型：离场实际成交价；gapFill 只落在当日真实离场的分支（顺延日不留幻影跳空标记）
        exit_stop = open_ if open_ < stop else stop
        exit_target = open_ if open_ > target else target
        gap_exit = exit_stop != stop or exit_target != target
        if hit_stop and hit_target:  # 同日双触保守记败（决议 3）——跳空模型同样适用（评审 B2）
            exit_price = open_ if open_ < stop else stop
            if gap_exit:
                rec["gapFill"] = True
            rec.update(outcome="loss", rValue=r_of(exit_price), exitDate=bar["date"], ambiguous=True)
            return _finalize(rec)
        if hit_target:
            if limit_down_day:  # 跌停一字板：卖出离场不可成交 → 顺延
                rec["limitDeferred"] = True
                continue
            if gap_exit:  # 单触止盈日 open>target（高开跳空）→ 更优成交价
                rec["gapFill"] = True
            rec.update(outcome="win", rValue=r_of(exit_target), exitDate=bar["date"])
            return _finalize(rec)
        if hit_stop:
            if limit_down_day:
                rec["limitDeferred"] = True
                continue
            if gap_exit:  # 单触止损日 open<stop（低开跳空）→ 更劣成交价
                rec["gapFill"] = True
            rec["rValue"] = r_of(exit_stop)
            rec["outcome"] = "loss"
            rec["exitDate"] = bar["date"]
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


# —— Task 5: bars 批量获取 + 聚合编排（fetch_all_bars/aggregate/review_plans，Task 6 依赖，签名冻结）——

DEFAULT_FEE_RATE = 0.0015
FEE_RATE_MAX = 0.05  # I6：费率校验上限（复盘端点内联 0.05 与组合端点共用，杜绝漂移）
_BARS_LIMIT = 300
BARS_LIMIT = _BARS_LIMIT  # 公开别名（评审 F7）：端点判截断披露用，杜绝跨模块取私有
_STALE_DAYS = 7


class ReviewUpstreamError(Exception):
    def __init__(self, codes: list[str], partial: dict[str, list[dict[str, Any]]] | None = None) -> None:
        super().__init__(f"history fetch failed for {len(codes)} code(s)")
        self.codes = codes
        # 失败前已成功拉取的 bar（真实数据非造数）；外围消费方可吸收（收尾硬化 L1）。
        self.partial = partial or {}


def fetch_all_bars(codes: list[str], router) -> dict[str, list[dict[str, Any]]]:
    """唯一 code 去重预取：DB bfq 缓存优先，缺口/过期走上游并落缓存；失败累积抛错。"""
    from backend import storage  # 局部导入避免环

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
        except Exception as exc:  # noqa: BLE001 —— 任一 code 失败不阻断其他 code 的拉取，最后统一抛
            review_logger.warning("review_fetch_failed code=%s err=%r", code, exc)
            failed.append(code)
    if failed:
        # 携带已成功部分（收尾硬化 L1）：外围消费方（组合端点第二趟自选码）可吸收 partial 防过度
        # 降级；硬依赖消费方（计划码 502 路径/复盘端点）只用 .codes，行为不变。
        raise ReviewUpstreamError(failed, partial=out)
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
        "total": len(records),
        "decided": len(decided),
        "flatCount": len(flats),
        "winRate": round(len(wins) / len(decided), 3) if decided else None,
        "avgWinR": avg_win,
        "avgLossR": avg_loss,
        "payoffRatio": payoff,
        "expectancyR": _mean(_nets(settled)),
        "notEnteredRate": round(len(not_entered) / denom_ne, 3) if denom_ne else None,
        "openCount": len(opens),
        "invalidCount": len(invalids),
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
        "source": group_rows(
            lambda r: r.get("source") or "legacy",
            lambda k: {"legacy": "早期计划", "manual": "手动新建", "screener": "策略命中", "monitor": "盯盘信号"}.get(
                k, k
            ),
        ),
        "direction": group_rows(
            lambda r: r.get("direction") or "buy", lambda k: {"buy": "买入", "sell": "卖出（平仓）"}.get(k, k)
        ),
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

    def nets(rows: list[dict[str, Any]]) -> list[float]:
        return [float(r["netR"]) for r in rows if r.get("netR") is not None]  # None 剔除（评审 B3）

    return {
        "decided": len(decided),
        "flatCount": len(flats),
        "wins": len(wins),
        "winRate": round(len(wins) / len(decided), 3) if decided else None,
        "expectancyR": _mean(nets(settled)),
        "payoffRatio": None,  # 分组行不含 payoff（YAGNI；明细看 kpis）
        "smallSample": (len(decided) + len(flats)) < 5,
    }


def review_plans(plans: list[dict[str, Any]], days: int, fee_rate: float, load_bars) -> dict[str, Any]:
    from datetime import datetime as _dt

    now_ms = int(_dt.now(SHANGHAI).timestamp() * 1000)
    min_created = 0 if days == 0 else now_ms - days * 86_400_000
    scoped = [p for p in plans if int(p.get("createdAtMs") or 0) >= min_created]
    codes = sorted({str(p.get("code")) for p in scoped if p.get("code")})
    bars_map = load_bars(codes) if codes else {}
    records: list[dict[str, Any]] = []
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
