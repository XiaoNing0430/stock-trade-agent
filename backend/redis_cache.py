"""P2-M2 Redis L2 缓存门面（spec r3.1 §4）。

三级：L1 进程 dict（data_source 现状）→ L2 Redis → loader 上游。
纪律：白名单前缀；物理 TTL ≥ STALE_MAX_AGE+60（新鲜/陈旧由封装 ts 判定）；
严格序列化（非 JSON 原生=跳写，绝不 default=str 造型）；仅客户端异常计熔断；
无 client/配置缺失 → down（全部旁路，行为=接管前现状）。
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from typing import Any

logger = logging.getLogger("atlas.redis_cache")

L2_PREFIX = "atlas:q:"
WHITELIST_PREFIXES = ("quotes:", "history:")  # D6 冻结：screener_v2 等永不触 L2
MAX_L2_BYTES = 128_000
STALE_FRESH_GRACE = 5  # get() 新鲜读宽限（双 TTL 漂移防御）
STALE_MAX_AGE = 1800  # 与 data_source 同步的降级窗（物理 TTL 下限依据）
BREAKER_FAILS = 3
BREAKER_SECONDS = 30


class CacheFacade:
    def __init__(
        self,
        client: Any | None,
        ttl_getter: Callable[[], int],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.client = client
        self._ttl = ttl_getter
        self._clock = clock
        self._fails = 0
        self._bypass_until = 0.0
        self._was_bypassed = False
        self.counters = {"skip_unserializable": 0, "skip_oversize": 0, "errors": 0}

    # ── 内部 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _eligible(key: str) -> bool:
        return key.startswith(WHITELIST_PREFIXES)

    def _bypassed(self) -> bool:
        return self.client is None or self._clock() < self._bypass_until

    def _on_error(self, exc: Exception) -> None:
        """仅 Redis 客户端异常/超时进入此路（序列化类跳写不计熔断，P1-3）。"""
        self.counters["errors"] += 1
        if self.client is None:
            return
        self._fails += 1
        if self._fails >= BREAKER_FAILS and self._clock() >= self._bypass_until:
            self._bypass_until = self._clock() + BREAKER_SECONDS
            self._fails = 0
            self._was_bypassed = True
            logger.warning(
                "redis_cache_degraded 连续 %d 次失败，L2 旁路 %ds（纯 L1=现状）: %s",
                BREAKER_FAILS,
                BREAKER_SECONDS,
                exc,
            )

    def _maybe_log_recovery(self) -> None:
        if self._was_bypassed and self._clock() >= self._bypass_until:
            self._was_bypassed = False
            logger.info("redis_cache_recovered L2 旁路窗结束，自动恢复")

    def _read_envelope(self, key: str, max_age: float) -> Any | None:
        if not self._eligible(key) or self._bypassed():
            return None
        self._maybe_log_recovery()
        client: Any = self.client  # _bypassed() 已排除 None（跨方法不可窄化，显式 Any 面）
        try:
            raw = client.get(L2_PREFIX + key)
        except Exception as exc:
            self._on_error(exc)
            return None
        if raw is None:
            return None
        try:
            env = json.loads(raw)
            ts = float(env["ts"])
        except Exception:
            return None  # 坏封装=弃键（TTL 自清），不造假不抛
        if self._clock() - ts > max_age:
            return None
        return env["v"]

    # ── 对外四类（I7） ─────────────────────────────────────────────────────

    def get(self, key: str) -> Any | None:
        """新鲜读：宽限=当前 _cache_ttl + 5s；超窗弃用（take_stale 才有 1800s 语义）。"""
        return self._read_envelope(key, self._ttl() + STALE_FRESH_GRACE)

    def take_stale(self, key: str, max_age: float) -> Any | None:
        """降级读：只按 max_age（STALE_MAX_AGE）判定——不受新鲜窗复核绞杀（P1-1）。"""
        return self._read_envelope(key, max_age)

    def set(self, key: str, value: Any, ttl: int) -> None:
        if not self._eligible(key) or self._bypassed():
            return
        self._maybe_log_recovery()
        try:
            payload = json.dumps({"ts": self._clock(), "v": value})  # 无 default：类型不转换红线
        except (TypeError, ValueError):
            self.counters["skip_unserializable"] += 1
            logger.debug("redis_cache_skip_unserializable key=%s", key)
            return
        if len(payload.encode("utf-8")) > MAX_L2_BYTES:
            self.counters["skip_oversize"] += 1
            logger.debug("redis_cache_skip_oversize key=%d bytes=%d", len(key), len(payload))
            return
        px = max(STALE_MAX_AGE + 60, ttl + 60) * 1000  # P1-5：物理窗随动，take_stale 必有东西可读
        client: Any = self.client  # 同上：_bypassed() 已排除 None
        try:
            client.set(L2_PREFIX + key, payload, px=px)
            self._fails = 0
        except Exception as exc:
            self._on_error(exc)

    def state(self) -> str:
        if self.client is None:
            return "down"
        if self._clock() < self._bypass_until:
            return "bypassed"
        return "connected"


def build_facade(
    settings: Any,
    *,
    client: Any | None = None,
    ttl_getter: Callable[[], int] = lambda: 8,
) -> CacheFacade:
    """I6：构造 facade。client 注入面（测试/定制）；未配置或探测失败 → down facade（永久旁路=现状）。"""
    if client is None:
        host = getattr(settings, "redis_host", "") or ""
        if not host:
            return CacheFacade(None, ttl_getter)
        try:
            from redis import Redis

            probe = Redis(
                host=host,
                port=int(getattr(settings, "redis_port", 6379)),
                password=getattr(settings, "redis_password", None) or None,
                db=int(getattr(settings, "redis_db", 0)),
                decode_responses=True,
                socket_connect_timeout=1,
                socket_timeout=0.5,
            )
            probe.ping()
            client = probe
        except Exception:
            logger.warning("redis_cache 连接探测失败，L2 永久旁路（行为=接管前现状）", exc_info=True)
            client = None
    return CacheFacade(client, ttl_getter)
