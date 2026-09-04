"""混合选股管道：粗筛（screener 能力）→ 本地精筛（history 能力）→ 财务增强（fundamental 能力）→ 结果缓存。

五轮评审落地的硬性保证（详见 docs/superpowers/plans/2026-09-02-screener-pipeline.md）：
1. 缓存键 = screener:{strategy_id}:{mode}:{market}（market 取路由源 calendar.market）
2. history 拉取：ThreadPoolExecutor(max_workers=5) 即并发上限 + 工作线程内 min-interval 限速
   （≤10 req/s 默认）+ 阶段 deadline（超时 cancel + 部分结果），无 future 级单票超时
3. reference_date 截断 bars，杜绝未来函数；默认上一交易日
4. 缓存互斥锁 + 双重检查，防击穿
5. 全源失败降级：返回过期缓存 + stale=True；无旧缓存才抛错
6. 结构化观测：trace_id + stageTimings + counts
"""

from __future__ import annotations

import logging
import re
import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import date
from typing import Any

from backend.screener.factors import FactorLibrary
from backend.screener.loader import ScreenerStrategyConfig, load_strategy

logger = logging.getLogger("screener.pipeline")

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# 拉取 60 根 + 2 根缓冲（截断 reference_date 之后仍够因子预热）
_HISTORY_LIMIT = 62
_CLOSED_BARS = 60
# 粗筛行数质量告警阈值
_MIN_HEALTHY_ROWS = 50
# 财务增强上限（避免 N 次请求触发限频）
_ENRICH_CAP = 10


class ScreenerPipeline:
    """无状态引擎实例可复用；缓存/锁/限速状态在实例内。"""

    def __init__(
        self,
        router: Any,
        settings_getter: Callable[[], dict[str, Any]] | None = None,
        rate_interval_s: float = 0.1,
        cache_ttl_s: float = 1800.0,  # 30 分钟
    ) -> None:
        self._router = router
        self._settings_getter = settings_getter or self._default_settings
        self._rate_interval_s = rate_interval_s
        self._cache_ttl_s = cache_ttl_s
        # 缓存：key -> (payload, computed_at)；过期不删除（降级需要旧值）
        self._cache: dict[str, tuple[dict[str, Any], float]] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._rate_lock = threading.Lock()
        self._last_rate_ts = 0.0
        self._factors = FactorLibrary()

    # ---- 入口 ----

    def run(
        self,
        strategy_id: str,
        mode: str = "quick",
        refresh: bool = False,
        reference_date: str | None = None,
    ) -> dict[str, Any]:
        cfg = load_strategy(strategy_id)
        if mode not in ("quick", "deep"):
            raise ValueError(f"invalid mode: {mode!r}")
        if reference_date is not None and not _DATE_RE.match(reference_date):
            raise ValueError(f"invalid reference_date: {reference_date!r} (expected YYYY-MM-DD)")
        trace_id = uuid.uuid4().hex[:12]

        settings = self._settings_getter()
        try:
            screener_source = self._router.route_with_fallback(
                str(settings.get("screenerSource", "tencent")),
                "screener",
                bool(settings.get("fallbackEnabled", True)),
            )
            market = str(screener_source.calendar.market)
        except Exception:
            # 路由本身失败：有旧缓存则降级返回（缓存键缺 market，按前缀匹配）
            if not refresh:
                stale = self._stale_by_prefix(f"screener:{cfg.id}:{mode}:", trace_id)
                if stale is not None:
                    return stale
            raise

        cache_key = f"screener:{cfg.id}:{mode}:{market}"
        lock = self._locks.setdefault(cache_key, threading.Lock())
        with lock:
            if not refresh:
                entry = self._cache.get(cache_key)
                if entry is not None and time.monotonic() - entry[1] < self._cache_ttl_s:
                    return {**entry[0], "cached": True, "stale": False}
            try:
                payload = self._compute(cfg, mode, reference_date, screener_source, settings, trace_id)
            except Exception:
                entry = self._cache.get(cache_key)
                if entry is not None:
                    logger.warning(
                        "screener.degraded_stale",
                        extra={"trace_id": trace_id, "strategy": cfg.id, "mode": mode, "market": market},
                    )
                    return {**entry[0], "cached": True, "stale": True}
                raise
            self._cache[cache_key] = (payload, time.monotonic())
            return {**payload, "cached": False, "stale": False}

    # ---- 计算主体 ----

    def _compute(
        self,
        cfg: ScreenerStrategyConfig,
        mode: str,
        reference_date: str | None,
        screener_source: Any,
        settings: dict[str, Any],
        trace_id: str,
    ) -> dict[str, Any]:
        t_start = time.monotonic()
        ref_date = reference_date or str(screener_source.calendar.previous_trading_day(date.today()).isoformat())

        # 1. 粗筛
        t_screen0 = time.monotonic()
        payload = screener_source.load_screener("全部", page_size=500)
        raw_rows: list[dict[str, Any]] = list(payload.get("rows") or [])
        counts: dict[str, int] = {"raw": len(raw_rows)}
        if len(raw_rows) < _MIN_HEALTHY_ROWS:
            logger.warning(
                "screener.quality_low_rows",
                extra={"trace_id": trace_id, "strategy": cfg.id, "rows": len(raw_rows)},
            )
        alive = [r for r in raw_rows if not self._is_excluded(r)]
        counts["afterExclude"] = len(alive)
        filtered = [r for r in alive if self._passes_quick_filters(r, cfg.quick_filters)]
        counts["afterQuick"] = len(filtered)
        filtered.sort(key=lambda r: self._sort_key(r, cfg.sort_by), reverse=True)
        screener_ms = int((time.monotonic() - t_screen0) * 1000)

        # 2. 精筛（deep）/ 直取 top_n（quick）
        history_ms = 0
        factor_ms = 0
        if mode == "deep":
            candidates = filtered[: cfg.deep_cap]
            scored, history_ms, factor_ms = self._score_with_history(candidates, cfg, ref_date, settings, trace_id)
            scored.sort(key=lambda r: (-float(r.get("score", 0.0)), -self._sort_key(r, cfg.sort_by)))
            top = scored[: cfg.top_n]
            counts["scored"] = len(scored)
        else:
            top = [dict(r) for r in filtered[: cfg.top_n]]
            counts["scored"] = len(top)

        # 3. 财务增强（top_n，≤10 次请求）
        t_enrich0 = time.monotonic()
        self._enrich_fundamentals(top, settings)
        enrich_ms = int((time.monotonic() - t_enrich0) * 1000)

        result: dict[str, Any] = {
            "strategy": cfg.id,
            "name": cfg.name,
            "mode": mode,
            "referenceDate": ref_date,
            "provider": screener_source.provider_label,
            "rows": top,
            "total": len(top),
            "elapsedMs": int((time.monotonic() - t_start) * 1000),
        }
        if bool(settings.get("debugScreener", True)):
            result["traceId"] = trace_id
            result["debug"] = {
                "stageTimings": {
                    "screenerMs": screener_ms,
                    "historyMs": history_ms,
                    "factorMs": factor_ms,
                    "enrichMs": enrich_ms,
                },
                "counts": counts,
            }
        return result

    # ---- 深度精筛 ----

    def _score_with_history(
        self,
        candidates: list[dict[str, Any]],
        cfg: ScreenerStrategyConfig,
        ref_date: str,
        settings: dict[str, Any],
        trace_id: str,
    ) -> tuple[list[dict[str, Any]], int, int]:
        history_source = self._router.route_with_fallback(
            str(settings.get("historySource", "tencent")),
            "history",
            bool(settings.get("fallbackEnabled", True)),
        )
        t0 = time.monotonic()
        executor = ThreadPoolExecutor(max_workers=5, thread_name_prefix="screener-hist")
        code_by_future: dict[Future[tuple[dict[str, Any], float, float] | None], str] = {}
        try:
            for row in candidates:
                fut = executor.submit(self._fetch_and_score, history_source, row, cfg, ref_date)
                code_by_future[fut] = str(row.get("code"))
            done, not_done = wait(code_by_future.keys(), timeout=cfg.history_deadline_s)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

        results: list[dict[str, Any]] = []
        factor_ms = 0.0
        for fut in done:
            code = code_by_future.get(fut, "?")
            try:
                out = fut.result()
            except Exception:
                logger.warning("screener.history_fetch_failed", extra={"trace_id": trace_id, "code": code})
                continue
            if out is None:
                continue
            row, _fetch_ms, fa_ms = out
            factor_ms += fa_ms
            results.append(row)
        for fut in not_done:
            fut.cancel()
            logger.warning(
                "screener.history_deadline_skipped",
                extra={"trace_id": trace_id, "code": code_by_future.get(fut, "?"), "deadline_s": cfg.history_deadline_s},
            )
        if candidates and not results:
            raise RuntimeError("精筛阶段全部失败")
        history_ms = int((time.monotonic() - t0) * 1000)
        return results, history_ms, int(factor_ms)

    def _fetch_and_score(
        self,
        history_source: Any,
        row: dict[str, Any],
        cfg: ScreenerStrategyConfig,
        ref_date: str,
    ) -> tuple[dict[str, Any], float, float] | None:
        code = str(row.get("code"))
        self._rate_gate()
        t0 = time.monotonic()
        bars = history_source.load_history(code, limit=_HISTORY_LIMIT)
        fetch_ms = (time.monotonic() - t0) * 1000
        t1 = time.monotonic()
        closed = [b for b in bars if str(b.get("date", "")) <= ref_date][-_CLOSED_BARS:]
        out = dict(row)
        if len(closed) >= 2:
            scored = self._factors.score_candidate(closed, [f.model_dump() for f in cfg.advanced_factors])
            out["score"] = scored["score"]
            out["factors"] = scored["factors"]
        else:
            out["score"] = 0.0
            out["factors"] = {}
        factor_ms = (time.monotonic() - t1) * 1000
        return out, fetch_ms, factor_ms

    # ---- 财务增强 ----

    def _enrich_fundamentals(self, rows: list[dict[str, Any]], settings: dict[str, Any]) -> None:
        if not rows:
            return
        try:
            fund_source = self._router.route_with_fallback(
                str(settings.get("fundamentalSource", "eastmoney")),
                "fundamental",
                bool(settings.get("fallbackEnabled", True)),
            )
        except Exception:
            return  # 无 fundamental 源（如 mock_us / tencent）→ 静默跳过
        loader = getattr(fund_source, "load_fundamentals", None)
        if loader is None:
            return
        for row in rows[:_ENRICH_CAP]:
            try:
                data = loader(str(row.get("code")))
            except Exception:
                continue  # 单票失败不影响整体
            if isinstance(data, dict):
                for key in ("roe", "totalMarketCap", "peg"):
                    if data.get(key) is not None:
                        row[key] = data[key]

    # ---- 缓存 / 限速 / 过滤工具 ----

    def _stale_by_prefix(self, prefix: str, trace_id: str) -> dict[str, Any] | None:
        for key, (payload, _ts) in self._cache.items():
            if key.startswith(prefix):
                logger.warning(
                    "screener.degraded_stale_route_failure",
                    extra={"trace_id": trace_id, "cache_key": key},
                )
                return {**payload, "cached": True, "stale": True}
        return None

    def _rate_gate(self) -> None:
        """共享锁 min-interval 限速：相邻 HTTP 请求间隔 ≥ rate_interval_s。"""
        if self._rate_interval_s <= 0:
            return
        with self._rate_lock:
            now = time.monotonic()
            wait_s = self._last_rate_ts + self._rate_interval_s - now
            if wait_s > 0:
                time.sleep(wait_s)
            self._last_rate_ts = time.monotonic()

    @staticmethod
    def _is_excluded(row: dict[str, Any]) -> bool:
        """排除 ST/*ST（名称含 ST）、停牌（volume<=0）、无价（price=None）。绝不造数。"""
        name = str(row.get("name") or "").upper()
        if "ST" in name:
            return True
        if row.get("price") is None:
            return True
        volume = row.get("volume")
        if volume is not None and float(volume) <= 0:
            return True
        return False

    @staticmethod
    def _passes_quick_filters(row: dict[str, Any], quick_filters: dict[str, tuple[float | None, float | None]]) -> bool:
        for field, (lo, hi) in quick_filters.items():
            value = row.get(field)
            if value is None:
                return False  # 缺数据不通过（绝不猜测）
            try:
                v = float(value)
            except (TypeError, ValueError):
                return False
            if lo is not None and v < lo:
                return False
            if hi is not None and v > hi:
                return False
        return True

    @staticmethod
    def _sort_key(row: dict[str, Any], field: str) -> float:
        value = row.get(field)
        try:
            return float(value) if value is not None else float("-inf")
        except (TypeError, ValueError):
            return float("-inf")

    @staticmethod
    def _default_settings() -> dict[str, Any]:
        from backend.storage import get_workspace_settings

        return get_workspace_settings("default")
