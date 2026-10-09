"""上游护栏与运行时降级（2026-10-03）。

覆盖：
1. `SourceGuard`：token bucket 节流 + 连接级连败熔断 + 半开单探测（假时钟，零等待）；
2. `EastMoneySource._http_get`：连接失败计入熔断、熔断开启后**不再打上游**（快速失败）；
3. `DataSourceRouter.source_chain`：降级链**有序**返回，`fallbackEnabled=False` 时只给首选。

离线纪律：monkeypatch HTTP，绝不触真东财。
"""

from __future__ import annotations

import pytest
import requests
from backend.sources import eastmoney as em_module
from backend.sources.eastmoney import EastMoneySource
from backend.sources.guard import SourceCircuitOpen, SourceGuard
from backend.sources.router import DataSourceRouter


class FakeSource:
    """最小可用源替身：只实现能力位与 load_market。"""

    def __init__(self, sid: str, capabilities: set[str], *, available: bool = True, fail: bool = False) -> None:
        self.id = sid
        self.capabilities = frozenset(capabilities)
        self.available = available
        self.provider_label = f"{sid}-label"
        self.fail = fail
        self.calls = 0

    def load_market(self, codes: list[str]) -> dict:
        self.calls += 1
        if self.fail:
            raise requests.exceptions.ConnectionError("reset")
        return {"quotes": [], "indices": [], "fetchedAt": 0, "errors": []}


# ---------- 1. 护栏本体 ----------


def test_guard_throttles_min_interval() -> None:
    sleeps: list[float] = []
    guard = SourceGuard(min_interval_s=0.25, clock=lambda: 100.0, sleeper=sleeps.append)

    guard.acquire()
    guard.acquire()

    assert sleeps == [0.25]  # 第二次调用需等待最小间隔


def test_guard_opens_after_threshold_and_recovers_via_half_open() -> None:
    now = [1000.0]
    guard = SourceGuard(failure_threshold=3, open_seconds=300.0, clock=lambda: now[0])

    for _ in range(3):
        guard.record_connection_failure()
    assert guard.state() == "open"
    with pytest.raises(SourceCircuitOpen):
        guard.before_call()  # 熔断期内快速失败

    now[0] += 301
    assert guard.state() == "half-open"
    guard.before_call()  # 半开放行单次探测
    with pytest.raises(SourceCircuitOpen):
        guard.before_call()  # 探测在途：并发不再放行
    guard.record_success()
    assert guard.state() == "closed"


def test_guard_success_resets_failure_count() -> None:
    guard = SourceGuard(failure_threshold=3, clock=lambda: 0.0)
    guard.record_connection_failure()
    guard.record_connection_failure()
    guard.record_success()  # 一次成功即清零，不累积到熔断
    guard.record_connection_failure()

    assert guard.state() == "closed"


# ---------- 2. 东财 _http_get 接护栏 ----------


def test_eastmoney_http_get_opens_breaker_and_stops_hitting_upstream(monkeypatch: pytest.MonkeyPatch) -> None:
    em_module._GUARD.reset()
    em_module._GUARD._min_interval_s = 0.0  # 免节流等待，专注熔断语义
    hits: list[str] = []

    def boom(url: str, **kwargs: object) -> object:
        hits.append(url)
        raise requests.exceptions.ConnectionError("Remote end closed connection without response")

    monkeypatch.setattr(em_module.requests, "get", boom)
    src = EastMoneySource()

    for _ in range(3):
        with pytest.raises(requests.exceptions.ConnectionError):
            src._http_get(src.QUOTE_URL, {})

    assert em_module.breaker_state() == "open"
    with pytest.raises(SourceCircuitOpen):
        src._http_get(src.QUOTE_URL, {})
    assert len(hits) == 3  # 熔断后不再打上游


def test_eastmoney_http_get_http_error_does_not_trip_breaker(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 状态错误说明连通性正常：如实上抛，但不算连接级失败、不触发熔断。"""
    em_module._GUARD.reset()
    em_module._GUARD._min_interval_s = 0.0

    class _Resp:
        def raise_for_status(self) -> None:
            raise requests.HTTPError("502 Bad Gateway")

    monkeypatch.setattr(em_module.requests, "get", lambda url, **kwargs: _Resp())
    src = EastMoneySource()

    for _ in range(4):
        with pytest.raises(requests.HTTPError):
            src._http_get(src.QUOTE_URL, {})

    assert em_module.breaker_state() == "closed"


# ---------- 3. 降级链有序 ----------


def test_source_chain_prefers_then_appends_fallbacks() -> None:
    router = DataSourceRouter(
        {"em": FakeSource("em", {"realtime"}), "tx": FakeSource("tx", {"realtime"}), "no": FakeSource("no", set())}
    )

    chain = [source.id for source in router.source_chain("em", "realtime", True)]

    assert chain[0] == "em" and "tx" in chain and "no" not in chain


def test_source_chain_disabled_returns_only_preferred() -> None:
    router = DataSourceRouter({"em": FakeSource("em", {"realtime"}), "tx": FakeSource("tx", {"realtime"})})

    assert [source.id for source in router.source_chain("em", "realtime", False)] == ["em"]


def test_source_chain_disabled_and_preferred_unavailable_raises() -> None:
    router = DataSourceRouter(
        {"em": FakeSource("em", {"realtime"}, available=False), "tx": FakeSource("tx", {"realtime"})}
    )

    with pytest.raises(ValueError):
        router.source_chain("em", "realtime", False)
