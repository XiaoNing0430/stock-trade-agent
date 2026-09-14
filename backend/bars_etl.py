"""全市场日线 ETL（P2-M1，spec r3.1 §3）：水位→缺口→回补/日补→批量落库，降级不静默。

设计要点：bfq（adjustment=''）单基线 500 根；上游失败/空响应一律计失败，坏根 DQ 拒收；
消费端（fetch_all_bars 的 7 日新鲜判据）零改动即获零回源。指数不入库（D9：000001 键污染）。
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
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
BATCH_CODES = 500  # 组事务码数（每批一 BEGIN，码级 SAVEPOINT 隔离）

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


def detect_gaps() -> dict[str, Any]:
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


# ── I4：执行流 ───────────────────────────────────────────────────────────────


_RUN_LOCK = threading.Lock()  # 跨 job 互斥（三独立触发共跑一个 run_full 的进程面保证）
_recheck: set[str] = set()  # DQ 拒收码的下轮强制复核队列（§3.4 自愈通道①；重启丢失由周六 force 审计兜底）
_last_run_at: dict[str, int | None] = {"at": None}
DAILY_MIN_LIMIT = 20


@dataclass
class EtlStats:
    universe: int = 0
    up_to_date: int = 0
    backfill: int = 0
    daily: int = 0
    no_new_bar: int = 0
    rejected: int = 0
    fetched: int = 0
    failed: list[str] = field(default_factory=list)
    watermark: str = ""
    aborted: bool = False
    elapsed_ms: int = 0
    reason: str = ""


def validate_bars(bars: list[dict[str, Any]], watermark: str) -> tuple[list[dict[str, Any]], int]:
    """DQ 逐根断言：坏根不落库（rejected 计数即诚实暴露）。volume=0（停牌）合法。"""
    from backend import data_source

    clean: list[dict[str, Any]] = []
    rejected = 0
    for bar in bars:
        date = str(bar.get("date") or "")
        o, h, lo, c = (data_source.numeric(bar.get(k)) for k in ("open", "high", "low", "close"))
        v = data_source.numeric(bar.get("volume"))
        if o is None or h is None or lo is None or c is None or v is None:  # 缺价先短路（mypy 窄化友好）
            rejected += 1
            continue
        ok = (
            len(date) == 10  # 合法日期串
            and date <= watermark  # 盘中半日 K/未来根双保险
            and min(o, h, lo, c) >= 0
            and v >= 0
            and lo <= min(o, c) + 1e-9
            and h >= max(o, c) - 1e-9
        )
        if ok:
            clean.append(bar)
        else:
            rejected += 1
    return clean, rejected


def _default_fetch(code: str, limit: int) -> list[dict[str, Any]]:
    from backend import data_source

    return data_source.load_history(code, limit=limit, is_index=False, adjustment="")


def run_full(force: bool = False, *, fetch: Callable[[str, int], list[dict[str, Any]]] | None = None) -> EtlStats:
    """一次全量编排：护栏→三档队列（+自愈复核）→批量落库→汇总日志。绝不并发双跑。"""
    t0 = time.time()
    stats = EtlStats()
    if not _RUN_LOCK.acquire(blocking=False):
        logger.warning("bars_etl_skipped_overlap 上一轮仍在执行，本轮跳过")
        stats.aborted, stats.reason, stats.elapsed_ms = True, "overlap", int((time.time() - t0) * 1000)
        return stats
    try:
        _do_run(stats, force, fetch or _default_fetch)
    finally:
        _last_run_at["at"] = int(time.time() * 1000)
        _RUN_LOCK.release()
        stats.elapsed_ms = int((time.time() - t0) * 1000)
        (logger.error if stats.aborted else logger.info)(
            "bars_etl_%s universe=%d up_to_date=%d backfill=%d daily=%d no_new_bar=%d rejected=%d "
            "fetched=%d failed=%d watermark=%s elapsed_ms=%d%s",
            "aborted" if stats.aborted else "ok",
            stats.universe,
            stats.up_to_date,
            stats.backfill,
            stats.daily,
            stats.no_new_bar,
            stats.rejected,
            stats.fetched,
            len(stats.failed),
            stats.watermark,
            stats.elapsed_ms,
            f" reason={stats.reason}" if stats.reason else "",
        )
    return stats


def _do_run(stats: EtlStats, force: bool, fetch: Callable[[str, int], list[dict[str, Any]]]) -> None:
    stats.watermark = authoritative_watermark()
    universe = resolve_universe()
    stats.universe = len(universe)
    if stats.universe < UNIVERSE_MIN:
        stats.aborted, stats.reason = True, "universe_too_small"
        logger.warning(
            "bars_etl_aborted universe_too_small universe=%d（industry 预热未完成？本轮跳过）", stats.universe
        )
        return
    gaps = detect_gaps()
    missing = list(gaps["missing"])
    deep = list(gaps["stale_deep"])
    light = list(gaps["stale_light"])
    stats.up_to_date = int(gaps["up_to_date"])
    backfill = [c for c in universe if c in set(missing) | set(deep)]
    queued = set(backfill) | set(light)
    daily = [c for c in universe if c not in queued] if force else list(light)
    recheck_now = {c for c in _recheck if c not in queued}
    daily = sorted(set(daily) | recheck_now)
    stats.backfill, stats.daily = len(backfill), len(daily)
    mx = _max_map()
    processed = fail_codes = 0

    def _attempt(code: str, limit: int) -> list[dict[str, Any]] | None:
        for _ in range(2):  # 单码重试 1 次（P0-2：空响应与异常同罪）
            try:
                bars = fetch(code, limit)
            except Exception:
                bars = []
            if bars:
                return bars
        return None

    def _flush(queue: list[str], limit_fn: Callable[[str], int]) -> bool:
        nonlocal processed, fail_codes
        for start in range(0, len(queue), BATCH_CODES):
            chunk = queue[start : start + BATCH_CODES]
            try:
                with storage.SessionLocal.begin() as group:
                    for code in chunk:
                        processed += 1
                        bars = _attempt(code, limit_fn(code))
                        if bars is None:
                            stats.failed.append(code)
                            fail_codes += 1
                        else:
                            clean, rejected = validate_bars(bars, stats.watermark)
                            stats.rejected += rejected
                            if rejected:
                                _recheck.add(code)
                            else:
                                _recheck.discard(code)
                            if not clean:
                                stats.failed.append(code)  # 全根皆坏=该码失败（拒收不是数据）
                                fail_codes += 1
                            else:
                                old = mx.get(code)
                                if old and max(str(b["date"]) for b in clean) <= old:
                                    stats.no_new_bar += 1  # 拉回无新根：休市/假日正常档
                                with group.begin_nested():  # 码级 SAVEPOINT（P2-4）
                                    stats.fetched += storage.upsert_market_bars_batch(
                                        code, clean, adjustment="", session=group
                                    )
                        if processed >= MIN_SAMPLES_FOR_ABORT and fail_codes / processed > FAIL_RATE_ABORT:
                            stats.aborted, stats.reason = True, "fail_rate"
                            return True  # 组内已处理码随本事务提交，未处理留给下轮
            except Exception:
                logger.error("bars_etl 组事务异常（chunk %d 码全计失败）", len(chunk), exc_info=True)
                for code in chunk:
                    if code not in stats.failed:
                        stats.failed.append(code)
            if stats.aborted:
                return True
        return False

    if _flush(backfill, lambda code: BACKFILL_LIMIT):
        return
    _flush(daily, lambda code: max(DAILY_MIN_LIMIT, _lag_days(mx.get(code), stats.watermark) + 5))


# ── I11 调度注册 / I5 health 位 ──────────────────────────────────────────────

_h_at = 0.0
_h_value: dict[str, Any] | None = None


def register_jobs(scheduler: Any) -> list[dict]:
    """三独立触发（启动 60s 一次性 / 交易日 15:20 / 周六 10:30）；跨 job 互斥由 _RUN_LOCK 保证。

    APScheduler 3.x 同 id 即替换，多触发必须多 id（r3.1 成文澄清）。注册失败仅日志。
    """
    registered: list[dict] = []
    base: dict[str, Any] = {
        "func": run_full,
        "max_instances": 1,
        "coalesce": True,
        "misfire_grace_time": 300,
        "replace_existing": True,
    }
    specs = [
        {**base, "id": "bars-etl-startup", "trigger": "date", "run_date": datetime.now(SH) + timedelta(seconds=60)},
        {**base, "id": "bars-etl-daily", "trigger": "cron", "day_of_week": "mon-fri", "hour": 15, "minute": 20},
        {**base, "id": "bars-etl-weekly", "trigger": "cron", "day_of_week": "sat", "hour": 10, "minute": 30},
    ]
    for spec in specs:
        try:
            scheduler.add_job(**spec)
            registered.append(spec)
        except Exception:
            logger.warning("bars_etl 任务注册失败 id=%s（跳过，不影响 API）", spec["id"], exc_info=True)
    return registered


def bars_health() -> dict[str, Any] | None:
    """I5：{watermark, freshCount, universeSize, lastRunAt}，60s 进程缓存（GROUP BY 不在轮询热路径逐次跑）。

    查询异常回 None——不造假不阻塞；从未跑过 ETL 时 lastRunAt=None。
    """
    global _h_at, _h_value
    now = time.time()
    with _wm_lock:
        if _h_value is not None and now - _h_at < 60:
            return dict(_h_value)
    try:
        watermark = authoritative_watermark()
        mx = _max_map()
        universe = resolve_universe()
        fresh = sum(1 for code in universe if mx.get(code) == watermark)
    except Exception:
        return None
    value: dict[str, Any] = {
        "watermark": watermark,
        "freshCount": fresh,
        "universeSize": len(universe),
        "lastRunAt": _last_run_at["at"],
    }
    with _wm_lock:
        _h_at, _h_value = now, dict(value)
    return value
