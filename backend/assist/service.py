"""交易计划草案编排：Router 取数 + 指标/仓位计算 + 组装响应（无状态，绝不落库）。"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import date
from typing import Any

from backend.assist.calculator import indicator_levels, sizing
from backend.data_source import classify_code, price_limit_ratio

DISCLAIMER = "算法生成的建议，非投资建议；止损 / 目标 / 仓位均基于公开行情计算，请自行判断。"
_T1_WARNING = "A 股 T+1：当日买入次交易日方可卖出，止损自次一交易日生效"
_STALE_MAX_AGE_MS = 60_000
_HISTORY_LIMIT = 62


class UpstreamError(Exception):
    """行情 / 历史数据不可用（→ 502，绝不返回造数草案）。

    注：backend/sources 内无既有上游异常类型（router 仅抛 ValueError），
    故按任务简报在此定义端点层的上游异常。
    """


def entry_staleness(entry_as_of_ms: int | None, now_ms: int) -> tuple[bool, list[str]]:
    """入场价快照时效：未知或超过 60s 视为过期，须核实现价。"""
    if entry_as_of_ms is None:
        return True, ["入场价快照时间未知，请核实现价"]
    if now_ms - entry_as_of_ms > _STALE_MAX_AGE_MS:
        return True, ["入场价为过期快照，请核实现价"]
    return False, []


def _limit_up_warning(entry: float, last_close: float | None, code: str) -> list[str]:
    """入场价触及涨停价提示（封板不可买入的成交风险，不阻断）。"""
    if last_close is None:
        return []
    limit_price = round(last_close * (1 + price_limit_ratio(code)), 2)
    if entry >= limit_price:
        return ["入场价已达涨停价位附近，注意封板成交风险"]
    return []


def _preferred_source(router: Any, source_id: str, capability: str) -> Any:
    """首选源（不降级）：仅用于 fallbackUsed 对照；不可用时返回 None。"""
    try:
        return router.route(source_id, capability)
    except Exception:
        return None


def _load_with_fallback(
    router: Any, source_id: str, capability: str, loader: Callable[[Any], Any], fallback_enabled: bool
) -> tuple[Any, Any, Any]:
    """按降级链逐源尝试 loader，首个成功者胜出。

    返回 (实际源, 结果, 首选源)。现场 route_with_fallback 仅按可用性路由、
    不在加载失败时重试，故此处用同一 Router 的 fallback_chain 实现加载级降级。
    全部源失败 → UpstreamError（502）。
    """
    preferred = _preferred_source(router, source_id, capability)
    if fallback_enabled:
        candidates = list(router.fallback_chain(capability, [source_id]))
    else:
        candidates = [preferred] if preferred is not None else []
    if not candidates:
        raise UpstreamError(f"没有可用于 {capability} 的数据源")
    last_exc: Exception | None = None
    for source in candidates:
        try:
            return source, loader(source), preferred
        except Exception as exc:  # 上游任何失败都降级到下一源
            last_exc = exc
    raise UpstreamError(f"行情数据不可用: {last_exc}")


def build_plan_draft(
    router: Any, payload: dict[str, Any], settings_getter: Callable[[], dict[str, Any]]
) -> dict[str, Any]:
    """编排一次草案计算：路由取数（含降级）→ 指标 → sizing → 组装 Out 字段 dict。"""
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
            quote_source, rows, _preferred = _load_with_fallback(
                router,
                str(settings.get("realtimeSource", "tencent")),
                "realtime",
                lambda s: s.load_quotes([code]),
                fallback_enabled,
            )
            row = next((q for q in rows if str(q.get("code")) == code), None)
            if row is None or not row.get("price"):
                raise UpstreamError(f"暂无 {code} 实时报价")
            entry = float(row["price"])
            as_of = row.get("updatedAt")
            name = name or str(row.get("name") or "")
            provider = str(quote_source.provider_label)
        history_source, bars, preferred_history = _load_with_fallback(
            router,
            str(settings.get("historySource", "tencent")),
            "history",
            lambda s: s.load_history(code, limit=_HISTORY_LIMIT, is_index=False),
            fallback_enabled,
        )
        # fallbackUsed 判定：实际取数源 ≠ 设置首选源（对象同一性；同一注册表内的单例）
        fallback_used = history_source is not preferred_history
        ref_date = str(history_source.calendar.previous_trading_day(date.today()).isoformat())
        if not provider:
            provider = str(history_source.provider_label)
    except UpstreamError:
        raise
    except Exception as exc:  # 上游网络 / 解析失败 → 502
        raise UpstreamError(str(exc)) from exc

    entry = float(entry)
    if entry <= 0:
        raise ValueError("入场价必须为正数")
    equity = float(payload.get("accountEquity") or settings["defaultCapital"])
    if equity <= 0:
        raise ValueError("账户权益必须为正数")
    levels = indicator_levels(bars, ref_date)
    result = sizing(
        entry,
        levels,
        stop_mode=str(payload.get("stopMode") or settings["stopMode"]),
        equity=equity,
        risk_pct=float(payload["riskPct"])
        if payload.get("riskPct") is not None
        else float(settings["riskPerTradePct"]),
        rr_ratio=float(payload["rrRatio"]) if payload.get("rrRatio") is not None else float(settings["rrRatio"]),
        cap_pct=float(settings["positionCapPct"]),
        limit_ratio=price_limit_ratio(code),
    )
    stale, stale_warnings = entry_staleness(int(as_of) if as_of is not None else None, int(time.time() * 1000))
    warnings = [
        _T1_WARNING,
        *stale_warnings,
        *_limit_up_warning(entry, levels.last_close, code),
        *result.warnings,
    ]
    return {
        "code": code,
        "name": name,
        "direction": "buy",
        "entry": entry,
        "stopAtr": round(entry - 2 * levels.atr14, 2) if levels.atr14 is not None else None,
        "stopMa20": round(levels.ma20, 2) if levels.ma20 is not None else None,
        "stop": result.stop,
        "target": result.target,
        "stopDistance": result.stop_distance,
        "atr14": levels.atr14,
        "ma20": levels.ma20,
        "riskAmount": result.risk_amount,
        "suggestedShares": result.suggested_shares,
        "positionPct": result.position_pct,
        "referenceDate": levels.reference_date,
        "entryAsOf": int(as_of) if as_of is not None else None,
        "stale": stale,
        "fallbackUsed": fallback_used,
        "provider": provider,
        "warnings": warnings,
        "disclaimer": DISCLAIMER,
    }
