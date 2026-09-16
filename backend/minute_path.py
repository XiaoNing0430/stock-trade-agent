"""受保护的按需分钟线读取路径（不落库、不后台轮询）。"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend import bars_etl, data_source

logger = logging.getLogger("atlas.minute_path")

PERIODS = {"1m": "1", "5m": "5", "15m": "15", "30m": "30", "60m": "60"}
MINUTE_MAX_COUNT = 320
MINUTE_L1_TTL = 15.0
MINUTE_L1_MAX_KEYS = 512
MINUTE_L1_SWEEP_EVERY = 50
MINUTE_RPS = 1.0
MINUTE_BURST = 3
MINUTE_BREAKER = 900.0


@dataclass
class MinuteFetch:
    bars: list[dict[str, Any]]
    source: str | None
    state: str
    degraded: bool
    updated_at_ms: int | None = None


_lock = threading.RLock()
_tokens = float(MINUTE_BURST)
_last_refill = 0.0
_fails = 0
_open_until = 0.0
_probe_inflight = False
_l1: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_writes = 0


def reset_for_test() -> None:
    global _tokens, _last_refill, _fails, _open_until, _probe_inflight, _writes
    with _lock:
        _tokens = float(MINUTE_BURST)
        _last_refill = 0.0
        _fails = 0
        _open_until = 0.0
        _probe_inflight = False
        _l1.clear()
        _writes = 0


def _now(now: Callable[[], float] | None = None) -> float:
    return (now or time.time)()


def _bucket_take(now: float) -> bool:
    global _tokens, _last_refill
    with _lock:
        if _last_refill == 0.0:
            _last_refill = now
        _tokens = min(float(MINUTE_BURST), _tokens + max(0.0, now - _last_refill) * MINUTE_RPS)
        _last_refill = now
        if _tokens < 1:
            return False
        _tokens -= 1
        return True


def breaker_state(now: float | None = None) -> str:
    return "open" if _now(now if callable(now) else (lambda: now)) < _open_until else "closed"


def _cache_facade() -> Any | None:
    return getattr(data_source, "_facade", None)


def _cache_get(key: str, now: float) -> MinuteFetch | None:
    with _lock:
        item = _l1.get(key)
        if item and now - item[0] <= MINUTE_L1_TTL:
            return MinuteFetch(item[1], "cache_l1", "ok", True, int(item[0] * 1000))
        if item:
            _l1.pop(key, None)
    facade = _cache_facade()
    if facade is not None:
        value = facade.get(key)
        if value is not None:
            return MinuteFetch(value, "cache_l2", "ok", True, int(now * 1000))
    return None


def _cache_only(key: str, state: str, now: float) -> MinuteFetch:
    hit = _cache_get(key, now)
    if hit:
        hit.state, hit.degraded = state, True
        return hit
    return MinuteFetch([], None, state, True)


def _cache_set(key: str, bars: list[dict[str, Any]], now: float) -> None:
    global _writes
    with _lock:
        _l1[key] = (now, bars)
        _writes += 1
        if _writes % MINUTE_L1_SWEEP_EVERY == 0:
            for k, (ts, _) in list(_l1.items()):
                if now - ts > MINUTE_L1_TTL:
                    _l1.pop(k, None)
        if len(_l1) > MINUTE_L1_MAX_KEYS:
            oldest = min(_l1, key=lambda k: _l1[k][0])
            _l1.pop(oldest, None)
    facade = _cache_facade()
    if facade is not None:
        facade.set(key, bars, int(MINUTE_L1_TTL))


def _parse_rows(payload: Any, symbol: str) -> list[dict[str, Any]]:
    data = (payload or {}).get("data") or {}
    node = data.get(symbol) or {}
    rows = node.get("m1") or node.get("m5") or node.get("m15") or node.get("m30") or node.get("m60") or []
    out = []
    for row in rows:
        if len(row) < 6:
            continue
        stamp = str(row[0])
        if len(stamp) == 12 and stamp.isdigit():
            stamp = f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[8:10]}:{stamp[10:12]}"
        out.append({"date": stamp, "open": data_source.numeric(row[1]), "close": data_source.numeric(row[2]), "high": data_source.numeric(row[3]), "low": data_source.numeric(row[4]), "volume": data_source.numeric(row[5]), "amount": data_source.numeric(row[6]) if len(row) > 6 else None})
    return out


def load_minute_kline(code: str, period: str, count: int, index: bool = False) -> list[dict[str, Any]]:
    symbol = data_source.index_symbol(code) if index else data_source.tencent_symbol(code)
    payload = data_source.fetch_json(data_source.KLINE_URL, {"param": f"{symbol},{PERIODS[period]},,,{count}"}, retry_http_error=False)
    return _parse_rows(payload, symbol)


def fetch_minute(code: str, period: str, count: int, index: bool = False, *, now: Callable[[], float] = time.time) -> MinuteFetch:
    global _fails, _open_until, _probe_inflight
    code = str(code).strip()
    if period not in PERIODS:
        raise ValueError("period 仅支持 1m/5m/15m/30m/60m")
    if not code or not code.isdigit() or len(code) != 6:
        raise ValueError("code 须为 6 位证券代码")
    count = max(10, min(int(count), MINUTE_MAX_COUNT))
    ts = _now(now)
    key = f"minute:{'idx:' if index else ''}{data_source.tencent_symbol(code)}:{period}:{count}"
    if bars_etl._RUN_LOCK.locked():
        return _cache_only(key, "etl_busy", ts)
    hit = _cache_get(key, ts)
    if hit:
        return hit
    if not _bucket_take(ts):
        return MinuteFetch([], None, "rate_limited", False)
    probe = False
    with _lock:
        if ts < _open_until:
            if not _probe_inflight:
                _probe_inflight = True
                probe = True
            else:
                return _cache_only(key, "circuit_open", ts)
    try:
        bars = load_minute_kline(code, period, count, index)
    except Exception:
        with _lock:
            _probe_inflight = False
            _fails += 1
            if probe or _fails >= 3:
                _open_until = ts + MINUTE_BREAKER
                _fails = 0
        logger.warning("minute_fail code=%s period=%s", code, period)
        return _cache_only(key, "circuit_open" if ts < _open_until else "unavailable", ts)
    with _lock:
        _fails = 0
        _open_until = 0.0
        _probe_inflight = False
    _cache_set(key, bars, ts)
    return MinuteFetch(bars, "upstream", "ok", False, int(ts * 1000))
