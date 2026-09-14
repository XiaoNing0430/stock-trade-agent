"""全市场日线 ETL（P2-M1，spec r3.1 §3）：水位→缺口→回补/日补→批量落库，降级不静默。

设计要点：bfq（adjustment=''）单基线 500 根；上游失败/空响应一律计失败，坏根 DQ 拒收；
消费端（fetch_all_bars 的 7 日新鲜判据）零改动即获零回源。指数不入库（D9：000001 键污染）。
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from backend import storage

logger = logging.getLogger("atlas.bars_etl")

SH = ZoneInfo("Asia/Shanghai")
CLOSE_MINUTES = 15 * 60 + 5  # 15:05 后当日 bar 视为可得（收盘缓冲）
BACKFILL_LIMIT = 500
STALE_DEEP_LAG = 10
UNIVERSE_MIN = 2000  # 小分母护栏（industry 预热竞态/上游单点故障面）
FAIL_RATE_ABORT = 0.2
MIN_SAMPLES_FOR_ABORT = 50

_wm_lock = threading.Lock()
_wm_at = 0.0
_wm_value = ""


def _watermark_uncached(t: datetime) -> str:
    """时刻粒度水位：t（上海时区）为 weekday 且 ≥15:05 才计当日，否则回溯最近 weekday。

    已知盲区（§9-L3）：日历无节假日表，法定假日（weekday）会误判为交易日——后果仅为
    一轮空转日补（拉回数据全部 ≤ 库内 max，幂等重写，数据不为错）。
    """
    d = t.date()
    if d.weekday() >= 5 or t.hour * 60 + t.minute < CLOSE_MINUTES:
        d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.isoformat()


def authoritative_watermark(now: datetime | None = None) -> str:
    """I2：最近一个"应已收盘交易日"。now 注入（测试面）时绕过缓存。"""
    global _wm_at, _wm_value
    if now is not None:
        return _watermark_uncached(now.astimezone(SH))
    with _wm_lock:
        if _wm_value and time.time() - _wm_at < 60:
            return _wm_value
    value = _watermark_uncached(datetime.now(SH))
    with _wm_lock:
        _wm_at, _wm_value = time.time(), value
    return value


def resolve_universe() -> list[str]:
    """I1：industry_map 全表 ∪ 工作区自选/计划码（含北交所工作区码——腾讯 bj 链路可拉）。

    不含指数（D9）。纯查询零副作用。
    """
    with storage.SessionLocal() as session:
        codes: set[str] = set(session.scalars(select(storage.IndustryMap.code)).all())
        codes |= set(session.scalars(select(storage.WatchlistItem.code).distinct()).all())
        codes |= set(session.scalars(select(storage.TradePlan.code).distinct()).all())
    return sorted(codes)


def _max_map() -> dict[str, str]:
    """bfq 桶各码最新落库日（索引覆盖 GROUP BY；ETL 唯一水位事实源）。"""
    with storage.SessionLocal() as session:
        rows = session.execute(
            select(storage.MarketBar.code, func.max(storage.MarketBar.trade_date))
            .where(storage.MarketBar.adjustment == "")
            .group_by(storage.MarketBar.code)
        ).all()
    return {code: mx for code, mx in rows}


def _lag_days(last: str | None, watermark: str) -> int:
    """近似交易日落后数：区间内 weekday 天数（无假日表——与 L3 同源近似，宁多判不漏判）。"""
    if not last:
        return 10_000
    try:
        a = datetime.strptime(last, "%Y-%m-%d").date()
        b = datetime.strptime(watermark, "%Y-%m-%d").date()
    except ValueError:
        return 10_000
    if a >= b:
        return 0
    n = 0
    d = a + timedelta(days=1)
    while d <= b:
        if d.weekday() < 5:
            n += 1
        d += timedelta(days=1)
    return n


def detect_gaps() -> dict[str, object]:
    """I3：universe 按落库水位分四档（missing/stale_deep/stale_light/up_to_date）。"""
    watermark = authoritative_watermark()
    mx = _max_map()
    missing: list[str] = []
    deep: list[str] = []
    light: list[str] = []
    up_to_date = 0
    for code in resolve_universe():
        last = mx.get(code)
        if last is None:
            missing.append(code)
            continue
        lag = _lag_days(last, watermark)
        if lag > STALE_DEEP_LAG:
            deep.append(code)
        elif lag >= 1:
            light.append(code)
        else:
            up_to_date += 1
    return {"missing": missing, "stale_deep": deep, "stale_light": light, "up_to_date": up_to_date}
