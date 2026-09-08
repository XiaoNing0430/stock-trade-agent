"""策略定时扫描：去重引擎 + 编排 + 调度注册（spec 2026-09-07，方案 A）。"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import UTC, datetime
from typing import Any

from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from backend.grid_scheduler import TIMEZONE
from backend.storage import (
    get_scan_config,
    insert_scan_history,
    list_enabled_scan_configs,
    redis_client,
    update_scan_state,
)

logger = logging.getLogger("screener.scan")


def merge_hits(
    prev_hits: list[dict[str, Any]], rows: list[dict[str, Any]], today: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """跌出再报去重（FR-4）：返回 (新进入命中, 新滞留状态)。

    - 新进入：当前 rows 中存在、prev 中不存在的代码，firstSeen=today
    - 滞留：两轮都在，保留原 firstSeen、更新 name/score
    - 跌出：prev 有、rows 无 → 从状态中移除（下次再进算新）
    """
    prev_by_code = {str(p.get("code")): p for p in prev_hits if p.get("code")}
    new_state: list[dict[str, Any]] = []
    newly: list[dict[str, Any]] = []
    for row in rows:
        code = row.get("code")
        if not code:
            continue
        code = str(code)
        entry = {"code": code, "name": str(row.get("name") or ""), "score": row.get("score")}
        prev_entry = prev_by_code.pop(code, None)
        if prev_entry is None:
            entry["firstSeen"] = today
            newly.append(entry)
        else:
            entry["firstSeen"] = str(prev_entry.get("firstSeen") or today)
        new_state.append(entry)
    return newly, new_state


# ---- 编排（Task 3 追加区） ----


def _get_scheduler() -> Any:
    """惰性获取调度器实例：从源头杜绝 grid_scheduler ↔ scan 循环导入（评审决议）。"""
    from backend.grid_scheduler import scheduler

    return scheduler


_LOCK_KEY = "scan:lock"
_LOCK_TTL_MS = 15 * 60 * 1000
_LOCK_TOKEN = uuid.uuid4().hex
_RELEASE_LUA = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end"
_pipeline: Any | None = None
_pipeline_lock = threading.Lock()


def _get_pipeline() -> Any:
    """单例管道：与 app.py _strategy_pipeline 同模式（懒建，测试可 monkeypatch 本函数）。"""
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            from backend.screener.pipeline import ScreenerPipeline
            from backend.sources import build_router
            from backend.storage import get_workspace_settings

            _pipeline = ScreenerPipeline(build_router(), settings_getter=lambda: get_workspace_settings("default"))
        return _pipeline


def _try_acquire_lock() -> tuple[bool, Any]:
    try:
        client = redis_client()
        got = client.set(_LOCK_KEY, _LOCK_TOKEN, nx=True, px=_LOCK_TTL_MS)
        if not got:
            return False, client
        return True, client
    except Exception:
        logger.warning("screener.scan_lock_unavailable", extra={"reason": "redis 不可用，降级无锁"})
        return True, None


def _release_lock(client: Any) -> None:
    if client is None:
        return
    try:
        client.eval(_RELEASE_LUA, 1, _LOCK_KEY, _LOCK_TOKEN)
    except Exception:
        logger.warning("screener.scan_lock_release_failed", extra={"reason": "锁释放失败，等 TTL 到期"})


def run_scan(
    strategy_id: str,
    mode: str = "quick",
    pipeline: Any | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """单策略扫描：管道 → 去重 → 状态/历史写入（含 enabled 前置校验 FR-13⑤）。"""
    started = time.monotonic()
    trace_id = uuid.uuid4().hex[:12]
    now = now or datetime.now(UTC)
    today = now.astimezone(TIMEZONE).date().isoformat()
    engine = pipeline or _get_pipeline()
    try:
        result = engine.run(strategy_id, mode=mode, refresh=False)
        rows = list(result.get("rows") or [])
        stale = bool(result.get("stale"))
    except Exception as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        logger.error(
            "screener.scan_failed",
            extra={"trace_id": trace_id, "strategy_id": strategy_id, "mode": mode, "error": str(exc)[:200]},
        )
        update_scan_state(strategy_id, "failed", [], now)  # require_enabled 默认 True
        insert_scan_history(strategy_id, "failed", 0, 0, elapsed, trace_id)
        return {
            "strategyId": strategy_id,
            "status": "failed",
            "hitCount": 0,
            "newCount": 0,
            "elapsedMs": elapsed,
            "traceId": trace_id,
            "stale": False,
        }
    try:
        prev_hits = (get_scan_config(strategy_id) or {}).get("lastHits") or []
        newly, new_state = merge_hits(prev_hits, rows, today=today)
        elapsed = int((time.monotonic() - started) * 1000)
        written = update_scan_state(strategy_id, "ok", new_state, now, new_count=len(newly))
        insert_scan_history(strategy_id, "ok", len(new_state), len(newly), elapsed, trace_id)
    except Exception as exc:
        # FR-13④：状态/历史写入失败仅日志（DB 故障不炸批量/调度线程）；结果未落库 → 如实报 failed
        elapsed = int((time.monotonic() - started) * 1000)
        logger.error(
            "screener.scan_state_write_failed",
            extra={"trace_id": trace_id, "strategy_id": strategy_id, "mode": mode, "error": str(exc)[:200]},
        )
        return {
            "strategyId": strategy_id,
            "status": "failed",
            "hitCount": 0,
            "newCount": 0,
            "elapsedMs": elapsed,
            "traceId": trace_id,
            "stale": stale,
        }
    if not written:
        # 扫描中途被关闭（FR-13⑤）：状态不覆盖，结果仅入历史
        return {
            "strategyId": strategy_id,
            "status": "skipped",
            "hitCount": len(new_state),
            "newCount": len(newly),
            "elapsedMs": elapsed,
            "traceId": trace_id,
            "stale": stale,
        }
    logger.info(
        "screener.scan",
        extra={
            "trace_id": trace_id,
            "strategy_id": strategy_id,
            "mode": mode,
            "hit_count": len(new_state),
            "new_count": len(newly),
            "elapsed_ms": elapsed,
            "stale": stale,
        },
    )
    return {
        "strategyId": strategy_id,
        "status": "ok",
        "hitCount": len(new_state),
        "newCount": len(newly),
        "elapsedMs": elapsed,
        "traceId": trace_id,
        "stale": stale,
    }


def _schedule_retry(strategy_id: str) -> None:
    from datetime import timedelta

    _get_scheduler().add_job(
        run_scan_retry,
        DateTrigger(run_date=datetime.now(TIMEZONE) + timedelta(minutes=10)),
        args=[strategy_id],
        id=f"scan:retry:{strategy_id}",
        replace_existing=True,
    )


def run_scan_retry(strategy_id: str) -> dict[str, Any] | None:
    """单次重试（FR-13②）：触发时先校验 enabled，已关闭直接跳过（不跑管道）。"""
    cfg = get_scan_config(strategy_id)
    if cfg is None or not cfg["enabled"]:
        logger.info("screener.scan_retry_skipped", extra={"strategy_id": strategy_id, "reason": "已关闭"})
        return None
    return run_scan(strategy_id)


def run_all_scans() -> list[dict[str, Any]]:
    """顺序扫描全部启用策略；Redis 锁互斥（FR-13①）；失败隔离 + 单次重试武装。"""
    acquired, client = _try_acquire_lock()
    if not acquired:
        logger.info("screener.scan_skipped_locked", extra={"reason": "其他 worker 持锁"})
        return []
    try:
        results: list[dict[str, Any]] = []
        for cfg in list_enabled_scan_configs():
            strategy_id = cfg["strategyId"]
            try:
                result = run_scan(strategy_id, mode=str(cfg.get("mode") or "quick"))
                results.append(result)
                if result["status"] == "failed":
                    _schedule_retry(strategy_id)
            except Exception as exc:
                # FR-13④ 失败隔离：单策略异常（含重试武装失败）仅日志，继续下一策略，不炸调度线程
                logger.error(
                    "screener.scan_batch_item_failed",
                    extra={"strategy_id": strategy_id, "error": str(exc)[:200]},
                )
                continue
        return results
    finally:
        _release_lock(client)


def _on_job_missed(event: Any) -> None:
    logger.warning("screener.scan_job_missed", extra={"job_id": getattr(event, "job_id", "")})


def register_scan_jobs() -> None:
    """两个 cron（FR-2）+ misfire 监听（FR-13③）；幂等（replace_existing）。"""
    _get_scheduler().add_job(
        run_all_scans,
        CronTrigger(day_of_week="mon-fri", hour=15, minute=40, timezone=TIMEZONE),
        id="scan:weekday",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _get_scheduler().add_job(
        run_all_scans,
        CronTrigger(day_of_week="sat,sun", hour=10, minute=0, timezone=TIMEZONE),
        id="scan:weekend",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    from apscheduler.events import EVENT_JOB_MISSED

    _get_scheduler().add_listener(_on_job_missed, EVENT_JOB_MISSED)
