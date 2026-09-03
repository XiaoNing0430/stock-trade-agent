"""ScreenerPipeline 测试：全 mock Router/源，覆盖五轮评审的全部硬性要求。"""

import threading
import time
from datetime import date, timedelta
from typing import Any

import backend.screener.pipeline as pipeline_module
import pytest
from backend.screener.loader import load_strategy
from backend.screener.pipeline import ScreenerPipeline


class FakeCalendar:
    def __init__(self, market: str = "CN") -> None:
        self.market = market

    def previous_trading_day(self, day: date) -> date:
        return day - timedelta(days=1)


class FakeScreenerSource:
    id = "fake_scr"
    capabilities = frozenset({"screener"})
    provider_label = "Fake Screener"

    def __init__(self, rows: list[dict[str, Any]], market: str = "CN", sleep_s: float = 0.0) -> None:
        self.rows = rows
        self.calendar = FakeCalendar(market)
        self.calls = 0
        self.sleep_s = sleep_s
        self.raises: Exception | None = None

    def load_screener(self, market: str, page_size: int = 300) -> dict[str, Any]:
        self.calls += 1
        if self.raises:
            raise self.raises
        if self.sleep_s:
            time.sleep(self.sleep_s)
        return {"total": len(self.rows), "rows": self.rows[:page_size]}


class FakeHistorySource:
    id = "fake_hist"
    capabilities = frozenset({"history"})
    provider_label = "Fake History"

    def __init__(
        self, bars_by_code: dict[str, list[dict[str, Any]]], sleep_by_code: dict[str, float] | None = None
    ) -> None:
        self.bars = bars_by_code
        self.sleep_by_code = sleep_by_code or {}
        self.calendar = FakeCalendar("CN")
        self.calls: list[tuple[str, float]] = []
        self._conc = 0
        self.peak = 0
        self._lock = threading.Lock()

    def load_history(self, code: str, limit: int = 40, is_index: bool = False) -> list[dict[str, Any]]:
        with self._lock:
            self._conc += 1
            self.peak = max(self.peak, self._conc)
        self.calls.append((code, time.monotonic()))
        time.sleep(self.sleep_by_code.get(code, 0.0))
        bars = self.bars.get(code, [])
        with self._lock:
            self._conc -= 1
        return bars[:limit]


class FakeFundSource:
    id = "fake_fund"
    capabilities = frozenset({"fundamental"})
    provider_label = "Fake Fund"

    def load_fundamentals(self, code: str) -> dict[str, Any]:
        return {"code": code, "roe": 15.0, "totalMarketCap": 123.4}


class FakeRouter:
    def __init__(self) -> None:
        self.sources: dict[str, Any] = {}

    def register(self, source: Any) -> Any:
        self.sources[source.id] = source
        return source

    def route_with_fallback(self, source_id: str, capability: str, fallback_enabled: bool = True) -> Any:
        source = self.sources[source_id]
        if capability not in source.capabilities:
            raise ValueError(f"{source_id} lacks capability {capability}")
        return source


def _settings(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "screenerSource": "fake_scr",
        "historySource": "fake_hist",
        "fundamentalSource": "fake_fund",
        "fallbackEnabled": True,
    }
    base.update(kw)
    return base


def _row(code: str, name: str, **kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "code": code,
        "name": name,
        "price": 10.0,
        "changePct": 1.0,
        "pe": 15.0,
        "pb": 2.0,
        "turnoverRate": 2.0,
        "volume": 1000.0,
        "volumeRatio": 1.0,
        "amount": 1e8,
    }
    base.update(kw)
    return base


def _bars(closes: list[float], start: date = date(2026, 7, 30), extra_future: bool = False) -> list[dict[str, Any]]:
    bars = [
        {
            "date": (start + timedelta(days=i)).isoformat(),
            "open": c,
            "high": c * 1.02,
            "low": c * 0.98,
            "close": c,
            "volume": 1000.0,
        }
        for i, c in enumerate(closes)
    ]
    if extra_future:
        bars.append(
            {"date": "2099-01-01", "open": 0.001, "high": 0.001, "low": 0.001, "close": 0.001, "volume": 1000.0}
        )
    return bars


def _make_pipeline(
    rows: list[dict[str, Any]],
    bars_by_code: dict[str, list[dict[str, Any]]] | None = None,
    *,
    market: str = "CN",
    screener_sleep_s: float = 0.0,
    rate_interval_s: float = 0.0,
    **settings_kw: Any,
) -> tuple[ScreenerPipeline, FakeScreenerSource, FakeHistorySource]:
    router = FakeRouter()
    scr = FakeScreenerSource(rows, market=market, sleep_s=screener_sleep_s)
    hist = FakeHistorySource(bars_by_code or {})
    router.register(scr)
    router.register(hist)
    router.register(FakeFundSource())
    pipeline = ScreenerPipeline(
        router,
        settings_getter=lambda: _settings(**settings_kw),
        rate_interval_s=rate_interval_s,
    )
    return pipeline, scr, hist


# ---------- 模式与过滤 ----------


def test_quick_mode_returns_top_n(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_strategy("oversold_bounce").model_copy(update={"top_n": 3})
    monkeypatch.setattr(pipeline_module, "load_strategy", lambda sid: cfg)
    rows = [_row(f"60000{i}", f"股{i}", changePct=float(i)) for i in range(8)]
    pipeline, _scr, hist = _make_pipeline(rows)
    result = pipeline.run("oversold_bounce", mode="quick")

    assert result["total"] == 3
    assert [r["changePct"] for r in result["rows"]] == [7.0, 6.0, 5.0]  # 按 sort_by 降序
    assert hist.calls == []  # 极速模式绝不拉 history
    assert result["mode"] == "quick"
    assert result["provider"] == "Fake Screener"
    assert result["traceId"]
    assert result["rows"][0]["roe"] == 15.0  # top_n 财务增强


def test_deep_mode_scores_factors() -> None:
    rows = [_row("600001", "超卖A"), _row("600002", "横盘B")]
    bars = {
        "600001": _bars([100.0 - i for i in range(30)]),  # 单调下跌 → rsi<30 达标 weight2
        "600002": _bars([100.0] * 30),  # 全平 → rsi=50 不达标
    }
    pipeline, _scr, hist = _make_pipeline(rows, bars)
    result = pipeline.run("oversold_bounce", mode="deep")

    assert len(hist.calls) == 2
    assert result["rows"][0]["code"] == "600001"
    assert result["rows"][0]["score"] == pytest.approx(
        3.0
    )  # rsi<30（w2）+ bollinger_pos<0.2（w1）达标，ma_slope 未达标
    assert result["rows"][1]["score"] == 0.0
    assert result["rows"][0]["factors"]["rsi"]["met"] is True


def test_reference_date_truncates_bars() -> None:
    """未来 bar（2099）必须被截断：因子值与仅用历史数据算出的一致。"""
    rows = [_row("600001", "A")]
    bars = {"600001": _bars([100.0 - i for i in range(30)], extra_future=True)}
    pipeline, _scr, _hist = _make_pipeline(rows, bars)
    result = pipeline.run("oversold_bounce", mode="deep", reference_date="2026-08-28")

    from backend.screener.factors import FactorLibrary

    expected = FactorLibrary().compute_factor(_bars([100.0 - i for i in range(30)]), {"name": "rsi", "period": 14})
    assert result["referenceDate"] == "2026-08-28"
    assert result["rows"][0]["factors"]["rsi"]["value"] == pytest.approx(expected)


def test_reference_date_defaults_to_previous_trading_day() -> None:
    rows = [_row("600001", "A")]
    pipeline, _scr, hist = _make_pipeline(rows, {"600001": _bars([100.0] * 30)})
    result = pipeline.run("oversold_bounce", mode="deep")
    assert result["referenceDate"] == (date.today() - timedelta(days=1)).isoformat()


def test_reference_date_invalid_format_raises() -> None:
    pipeline, _scr, _hist = _make_pipeline([_row("600001", "A")])
    with pytest.raises(ValueError, match="reference_date"):
        pipeline.run("oversold_bounce", reference_date="2026/08/01")


def test_excludes_st_and_suspended() -> None:
    rows = [
        _row("600001", "正常甲"),
        _row("600002", "ST remix"),
        _row("600003", "*ST 乙"),
        _row("600004", "停牌丙", volume=0.0),
        _row("600005", "无价丁", price=None),
    ]
    pipeline, _scr, _hist = _make_pipeline(rows)
    result = pipeline.run("oversold_bounce", mode="quick")
    assert [r["code"] for r in result["rows"]] == ["600001"]
    assert result["debug"]["counts"]["raw"] == 5
    assert result["debug"]["counts"]["afterExclude"] == 1


# ---------- 缓存与并发 ----------


def test_result_cached_and_refresh_bypasses() -> None:
    pipeline, scr, _hist = _make_pipeline([_row("600001", "A")])
    r1 = pipeline.run("oversold_bounce", mode="quick")
    r2 = pipeline.run("oversold_bounce", mode="quick")
    assert r1["cached"] is False
    assert r2["cached"] is True
    assert r2["stale"] is False
    assert scr.calls == 1
    r3 = pipeline.run("oversold_bounce", mode="quick", refresh=True)
    assert r3["cached"] is False
    assert scr.calls == 2


def test_cache_key_distinguishes_mode_and_market() -> None:
    rows = [_row("600001", "A")]
    pipeline, scr, hist = _make_pipeline(rows, {"600001": _bars([100.0] * 30)})
    pipeline.run("oversold_bounce", mode="quick")
    pipeline.run("oversold_bounce", mode="deep")
    assert scr.calls == 2  # quick/deep 各自缓存，deep 不吃 quick 缓存

    # market 入键：CN 源先跑，US 源再跑；若键未含 market，第二次会误吃缓存（calls==0）
    scr_cn = FakeScreenerSource(rows, market="CN")
    scr_us = FakeScreenerSource(rows, market="US")
    scr_us.id = "fake_scr_us"
    p_cn = ScreenerPipeline(_router_with(scr_cn, hist), settings_getter=lambda: _settings(screenerSource=scr_cn.id))
    p_us = ScreenerPipeline(_router_with(scr_us, hist), settings_getter=lambda: _settings(screenerSource=scr_us.id))
    p_cn.run("oversold_bounce", mode="quick")
    p_us.run("oversold_bounce", mode="quick")
    assert scr_cn.calls == 1
    assert scr_us.calls == 1


def _router_with(source: Any, *more: Any) -> FakeRouter:
    router = FakeRouter()
    router.register(source)
    for s in more:
        router.register(s)
    return router


def test_cache_lock_prevents_stampede() -> None:
    pipeline, scr, _hist = _make_pipeline([_row("600001", "A")], screener_sleep_s=0.2)
    results: list[dict[str, Any]] = []
    errors: list[Exception] = []

    def _worker() -> None:
        try:
            results.append(pipeline.run("oversold_bounce", mode="quick"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_worker) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert errors == []
    assert scr.calls == 1  # 并发 10 线程只触发 1 次计算
    assert len(results) == 10
    assert all(r["rows"][0]["code"] == "600001" for r in results)


def test_degraded_returns_stale_cache() -> None:
    pipeline, scr, _hist = _make_pipeline([_row("600001", "A")])
    r1 = pipeline.run("oversold_bounce", mode="quick")
    # 手动把缓存条目置为过期
    expired = {k: (v, t - 9999) for k, (v, t) in pipeline._cache.items()}
    pipeline._cache.clear()
    pipeline._cache.update(expired)
    scr.raises = RuntimeError("upstream down")
    r2 = pipeline.run("oversold_bounce", mode="quick")
    assert r2["stale"] is True
    assert r2["rows"] == r1["rows"]
    # 无旧缓存 + 全源失败 → 抛错
    fresh, fresh_scr, _h = _make_pipeline([_row("600001", "A")])
    fresh_scr.raises = RuntimeError("upstream down")
    with pytest.raises(RuntimeError, match="upstream down"):
        fresh.run("oversold_bounce", mode="quick")


# ---------- 性能护栏 ----------


def test_deep_cap_limits_history_fetches() -> None:
    rows = [_row(f"6000{i:03d}", f"股{i}") for i in range(500)]
    pipeline, _scr, hist = _make_pipeline(rows, {})
    result = pipeline.run("oversold_bounce", mode="deep")
    assert len(hist.calls) <= 200  # deep_cap=200
    assert result["debug"]["counts"]["afterQuick"] == 500


def test_pool_size_caps_inflight_requests() -> None:
    rows = [_row(f"6000{i:03d}", f"股{i}") for i in range(60)]
    bars = {r["code"]: _bars([100.0] * 30) for r in rows}
    pipeline, _scr, hist = _make_pipeline(rows, bars)
    pipeline.run("oversold_bounce", mode="deep")
    assert hist.peak <= 5  # max_workers=5 即并发上限


def test_rate_limit_enforces_min_interval() -> None:
    rows = [_row(f"6000{i:03d}", f"股{i}") for i in range(6)]
    bars = {r["code"]: _bars([100.0] * 30) for r in rows}
    pipeline, _scr, hist = _make_pipeline(rows, bars, rate_interval_s=0.1)
    pipeline.run("oversold_bounce", mode="deep")
    ts = [t for _, t in hist.calls]
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    assert gaps, "应有多次请求"
    assert min(gaps) >= 0.095  # 相邻请求 ≥0.1s（≤10 req/s）


def test_stage_deadline_returns_partial_results(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = load_strategy("oversold_bounce").model_copy(update={"deep_cap": 10, "history_deadline_s": 0.2})
    monkeypatch.setattr(pipeline_module, "load_strategy", lambda sid: cfg)
    codes = [f"6000{i:03d}" for i in range(4)]
    rows = [_row(c, f"股{i}") for i, c in enumerate(codes)]
    bars = {c: _bars([100.0] * 30) for c in codes}
    sleep_by_code = {codes[0]: 1.0}  # 一只票挂死（1s，足够超 0.2s deadline 且不拖累测试进程退出）
    pipeline, _scr, hist = _make_pipeline(rows, bars)
    hist.sleep_by_code = sleep_by_code  # 注入挂死行为
    result = pipeline.run("oversold_bounce", mode="deep")
    assert result["stale"] is False
    assert {r["code"] for r in result["rows"]}.isdisjoint({codes[0]})  # 挂死票被跳过
    assert len(result["rows"]) == 3  # 其余正常返回（部分结果）
