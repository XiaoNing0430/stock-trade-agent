"""草案计算核心测试：closed_bars / 限频 / 纯函数 sizing（Task 1-3 逐段补充）。"""

from __future__ import annotations

from backend.indicators import closed_bars


def _bar(day: str, close: float) -> dict:
    return {"date": day, "open": close, "close": close, "high": close, "low": close, "volume": 100}


def test_closed_bars_truncates_future_dates() -> None:
    bars = [_bar("2026-09-01", 10.0), _bar("2026-09-02", 11.0), _bar("2026-09-03", 12.0)]
    closed = closed_bars(bars, "2026-09-02", limit=60)
    assert [b["date"] for b in closed] == ["2026-09-01", "2026-09-02"]


def test_closed_bars_keeps_last_limit() -> None:
    bars = [_bar(f"2026-08-{d:02d}", 10.0) for d in range(1, 11)]
    assert len(closed_bars(bars, "2026-08-31", limit=5)) == 5


def test_closed_bars_empty() -> None:
    assert closed_bars([], "2026-09-02", limit=60) == []


from backend.assist.limiter import SlidingWindowLimiter  # noqa: E402


class _FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_limiter_allows_burst_then_blocks() -> None:
    clock = _FakeClock()
    limiter = SlidingWindowLimiter(max_events=3, window_seconds=60.0, clock=clock)
    assert limiter.check() == (True, 0.0)
    assert limiter.check() == (True, 0.0)
    assert limiter.check() == (True, 0.0)
    allowed, retry_after = limiter.check()
    assert not allowed
    assert 59.0 <= retry_after <= 60.0


def test_limiter_window_slides() -> None:
    clock = _FakeClock()
    limiter = SlidingWindowLimiter(max_events=2, window_seconds=60.0, clock=clock)
    limiter.check()
    limiter.check()
    clock.now += 61.0
    allowed, _ = limiter.check()
    assert allowed


from backend.assist.calculator import IndicatorLevels, indicator_levels, sizing  # noqa: E402

# 基准场景截面：A=10.0、ATR=0.5、MA20=9.8（止损候选在 sizing 内按 entry 现算）
LEVELS = IndicatorLevels(reference_date="2026-09-03", closed_count=60, atr14=0.5, ma20=9.8, last_close=10.0)


def test_indicator_levels_computes_atr_and_ma() -> None:
    bars = [
        {
            "date": f"2026-08-{d:02d}",
            "open": 10,
            "close": 10 + (d % 3) * 0.2,
            "high": 10.5 + (d % 3) * 0.2,
            "low": 9.5,
            "volume": 100,
        }
        for d in range(1, 31)
    ]
    levels = indicator_levels(bars, "2026-08-30")
    assert levels.closed_count == 30
    assert levels.atr14 is not None and levels.atr14 > 0
    assert levels.ma20 is not None
    assert levels.last_close == 10.0
    # 与 indicators 直算一致
    from backend.indicators import atr, ma

    closes = [float(b["close"]) for b in bars]
    assert levels.atr14 == atr(bars, period=14)[-1]
    assert levels.ma20 == ma(closes, 20)[-1]


def test_indicator_levels_insufficient_bars() -> None:
    bars = [_bar("2026-08-01", 10.0), _bar("2026-08-02", 10.1)]
    levels = indicator_levels(bars, "2026-08-30")
    assert levels.atr14 is None and levels.ma20 is None


def test_sizing_default_scenario() -> None:
    r = sizing(
        10.0, LEVELS, stop_mode="atr", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10
    )
    assert r.stop == 9.0 and r.stop_distance == 1.0
    assert r.target == 12.0 and r.risk_amount == 1000.0  # target = entry + stop_distance*rr（公式唯一事实）
    assert r.suggested_shares == 1000 and r.position_pct == 10.0


def test_sizing_insufficient_equity() -> None:
    r = sizing(10.0, LEVELS, stop_mode="atr", equity=9000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10)
    assert r.suggested_shares == 0 and any("不足一手" in w for w in r.warnings)


def test_sizing_cap_truncates() -> None:
    r = sizing(
        10.0, LEVELS, stop_mode="atr", equity=100000.0, risk_pct=5.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10
    )
    assert r.suggested_shares == 2500 and any("上限" in w for w in r.warnings)


def test_sizing_ma20_mode_and_fallback() -> None:
    r = sizing(
        10.0, LEVELS, stop_mode="ma20", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10
    )
    assert r.stop == 9.8  # ma20 优先且有效


def test_sizing_invalid_stop_falls_back_to_none() -> None:
    levels = IndicatorLevels(reference_date="d", closed_count=60, atr14=0.5, ma20=10.5, last_close=10.0)
    r = sizing(
        10.0, levels, stop_mode="ma20", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10
    )
    assert r.stop == 9.0  # ma20 无效回退 atr


def test_sizing_all_stops_invalid() -> None:
    # 注：修订版语义下 stop_atr = entry − 2·ATR 在 ATR>0 时恒 < entry，
    # 故全无效场景取 atr14=None（数据不足）+ ma20=11.0 ≥ 入场价。
    levels2 = IndicatorLevels(reference_date="d", closed_count=60, atr14=None, ma20=11.0, last_close=10.0)
    r2 = sizing(
        10.0, levels2, stop_mode="atr", equity=100000.0, risk_pct=1.0, rr_ratio=2.0, cap_pct=25.0, limit_ratio=0.10
    )
    assert r2.stop is None and r2.target is None and r2.suggested_shares == 0
    assert any("止损" in w for w in r2.warnings)


def test_sizing_multiday_target_warning() -> None:
    r = sizing(
        10.0, LEVELS, stop_mode="atr", equity=100000.0, risk_pct=1.0, rr_ratio=3.0, cap_pct=25.0, limit_ratio=0.10
    )
    assert any("多日" in w for w in r.warnings)


# ===================== Task 6：POST /api/assist/plan-draft 端点 =====================

import time  # noqa: E402
from datetime import date  # noqa: E402

import pytest  # noqa: E402
from backend import app as app_module  # noqa: E402
from backend.storage import DEFAULT_WORKSPACE_SETTINGS  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def _assist_bars() -> list[dict]:
    return [
        {
            "date": f"2026-08-{d:02d}",
            "open": 10,
            "close": 10 + (d % 3) * 0.2,
            "high": 10.6 + (d % 3) * 0.2,
            "low": 9.4,
            "volume": 1000,
        }
        for d in range(1, 31)
    ]


class _AssistFakeCalendar:
    """固定交易日历：previous_trading_day 恒返回 2026-08-30（bars 末根同日，验证截断收敛）。"""

    market = "CN"

    def previous_trading_day(self, day: date) -> date:
        return date(2026, 8, 30)


def _assist_client(monkeypatch, **settings_overrides):
    settings = dict(DEFAULT_WORKSPACE_SETTINGS)
    settings.update(settings_overrides)
    monkeypatch.setattr(app_module, "get_workspace_settings", lambda workspace_id="default": dict(settings))
    return TestClient(app_module.create_app())  # 每测试新 app → 新限频器，天然隔离


def test_assist_plan_draft_happy_path(monkeypatch) -> None:
    """默认流程：显式入场价 + 60 根 bars → 草案各字段与包裹形状 {"data": ...}。"""
    from backend.sources import tencent as tx_module

    bars = [
        {
            "date": f"2026-07-{d:02d}" if d <= 31 else f"2026-08-{d - 31:02d}",
            "open": 10,
            "close": 10 + (d % 3) * 0.2,
            "high": 10.6 + (d % 3) * 0.2,
            "low": 9.4,
            "volume": 1000,
        }
        for d in range(1, 61)
    ]
    monkeypatch.setattr(tx_module.TencentSource, "load_history", lambda self, code, limit, is_index=False: bars)
    monkeypatch.setattr(tx_module.TencentSource, "calendar", property(lambda self: _AssistFakeCalendar()))
    with _assist_client(monkeypatch) as client:
        resp = client.post(
            "/api/assist/plan-draft",
            json={"code": "600519", "entryPrice": 10.0, "entryAsOfMs": int(time.time() * 1000), "name": "贵州茅台"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == {"data"}  # 包裹习惯与 /api/settings 一致
    data = body["data"]
    assert data["code"] == "600519" and data["name"] == "贵州茅台"
    assert data["direction"] == "buy" and data["entry"] == 10.0
    assert data["referenceDate"] == "2026-08-30"
    assert data["stale"] is False and data["fallbackUsed"] is False
    assert data["provider"] == "Tencent public quote API"
    assert data["suggestedShares"] > 0 and data["suggestedShares"] % 100 == 0
    assert data["stop"] == data["stopAtr"]  # 默认 stopMode=atr
    assert data["stopAtr"] == pytest.approx(10.0 - 2 * data["atr14"], abs=0.01)
    assert data["stopMa20"] is not None and data["ma20"] is not None
    assert any("T+1" in w for w in data["warnings"])
    assert data["disclaimer"]
    assert data["entryAsOf"] is not None


def test_assist_plan_draft_rate_limited(monkeypatch) -> None:
    """31 次请求 → 429 + Retry-After；先计数后校验（422 也计入窗口）。"""
    with _assist_client(monkeypatch) as client:
        for _ in range(30):
            resp = client.post("/api/assist/plan-draft", json={"code": "abc"})
            assert resp.status_code == 422
        limited = client.post("/api/assist/plan-draft", json={"code": "abc"})
    assert limited.status_code == 429
    assert limited.json()["detail"]["code"] == "RATE_LIMITED"
    assert "retry-after" in {k.lower() for k in limited.headers}
    assert int(limited.headers["retry-after"]) >= 1


def test_assist_plan_draft_upstream_502(monkeypatch) -> None:
    """两个历史源 load_history 全部失败 → 502 UPSTREAM_UNAVAILABLE（绝不造数）。"""
    from backend.sources import eastmoney as em_module
    from backend.sources import tencent as tx_module

    def _boom(self, code, limit, is_index=False):
        raise RuntimeError("network down")

    monkeypatch.setattr(tx_module.TencentSource, "load_history", _boom)
    monkeypatch.setattr(em_module.EastMoneySource, "load_history", _boom)
    with _assist_client(monkeypatch) as client:
        resp = client.post("/api/assist/plan-draft", json={"code": "600519", "entryPrice": 10.0})
    assert resp.status_code == 502
    assert resp.json()["detail"]["code"] == "UPSTREAM_UNAVAILABLE"


def test_assist_plan_draft_fallback_flag(monkeypatch) -> None:
    """腾讯 history 失败 → 降级东财成功 → fallbackUsed=True（降级透明化）。"""
    from backend.sources import eastmoney as em_module
    from backend.sources import tencent as tx_module

    def _tx_boom(self, code, limit, is_index=False):
        raise RuntimeError("tencent down")

    monkeypatch.setattr(tx_module.TencentSource, "load_history", _tx_boom)
    monkeypatch.setattr(
        em_module.EastMoneySource, "load_history", lambda self, code, limit, is_index=False: _assist_bars()
    )
    monkeypatch.setattr(em_module.EastMoneySource, "calendar", property(lambda self: _AssistFakeCalendar()))
    with _assist_client(monkeypatch) as client:
        resp = client.post("/api/assist/plan-draft", json={"code": "600519", "entryPrice": 10.0})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["fallbackUsed"] is True
    assert data["provider"] == "东方财富实时行情"


def test_assist_plan_draft_limit_up_warning(monkeypatch) -> None:
    """entry == 末根收盘 10.0 × 1.10 == 11.0（沪深主板涨停价）→ 警告不阻断；无快照时间 → stale。"""
    from backend.sources import tencent as tx_module

    monkeypatch.setattr(
        tx_module.TencentSource, "load_history", lambda self, code, limit, is_index=False: _assist_bars()
    )
    monkeypatch.setattr(tx_module.TencentSource, "calendar", property(lambda self: _AssistFakeCalendar()))
    with _assist_client(monkeypatch) as client:
        resp = client.post("/api/assist/plan-draft", json={"code": "600519", "entryPrice": 11.0})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert any("涨停" in w for w in data["warnings"])
    assert data["stale"] is True and any("快照" in w for w in data["warnings"])


def test_assist_plan_draft_stop_mode_ma20(monkeypatch) -> None:
    """stopMode=ma20 透传 sizing：entry=10.5 > ma20=10.2 → 止损取 MA20 而非 ATR。"""
    from backend.sources import tencent as tx_module

    monkeypatch.setattr(
        tx_module.TencentSource, "load_history", lambda self, code, limit, is_index=False: _assist_bars()
    )
    monkeypatch.setattr(tx_module.TencentSource, "calendar", property(lambda self: _AssistFakeCalendar()))
    with _assist_client(monkeypatch) as client:
        resp = client.post(
            "/api/assist/plan-draft",
            json={"code": "600519", "entryPrice": 10.5, "stopMode": "ma20", "entryAsOfMs": int(time.time() * 1000)},
        )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["stop"] == data["stopMa20"]
    assert data["stop"] != data["stopAtr"]
    assert data["target"] == pytest.approx(data["entry"] + data["stopDistance"] * 2.0, abs=0.01)


def test_assist_plan_draft_quote_fetch(monkeypatch) -> None:
    """entryPrice 省略 → 实时报价路由取价（entryAsOf / provider 来自报价源）。"""
    from backend.sources import tencent as tx_module

    now_ms = int(time.time() * 1000)
    monkeypatch.setattr(
        tx_module.TencentSource,
        "load_quotes",
        lambda self, codes: [{"code": "600519", "name": "贵州茅台", "price": 10.0, "updatedAt": now_ms}],
    )
    monkeypatch.setattr(
        tx_module.TencentSource, "load_history", lambda self, code, limit, is_index=False: _assist_bars()
    )
    monkeypatch.setattr(tx_module.TencentSource, "calendar", property(lambda self: _AssistFakeCalendar()))
    with _assist_client(monkeypatch) as client:
        resp = client.post("/api/assist/plan-draft", json={"code": "600519"})
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["entry"] == 10.0 and data["entryAsOf"] == now_ms
    assert data["name"] == "贵州茅台"
    assert data["stale"] is False and data["fallbackUsed"] is False
    assert data["provider"] == "Tencent public quote API"


def test_assist_plan_draft_validation_422(monkeypatch) -> None:
    """无法识别代码 → service 语义 422；entryPrice=0 → pydantic 422。"""
    with _assist_client(monkeypatch) as client:
        unknown = client.post("/api/assist/plan-draft", json={"code": "abc", "entryPrice": 10.0})
        halted = client.post("/api/assist/plan-draft", json={"code": "600519", "entryPrice": 0})
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "VALIDATION_ERROR"
    assert halted.status_code == 422
