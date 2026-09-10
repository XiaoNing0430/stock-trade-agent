"""计划绩效复盘：source 归因存储 + bfq 链路 + 回放引擎 + 聚合 API。

沿用 test_storage_coverage.py 的既有模式：真实 PostgreSQL（initialize_storage）+
专用工作区避免污染默认数据；不臆造 fixture。
"""

from __future__ import annotations

import pytest
from backend import storage
from backend import storage as storage_module

# 专用测试工作区，避免覆盖默认工作区真实数据
WS = "pr-ws"


@pytest.fixture(scope="module", autouse=True)
def _ensure_tables():
    storage_module.initialize_storage()


@pytest.fixture(autouse=True)
def _cleanup_test_data():
    yield
    from sqlalchemy import delete

    models = [
        storage_module.WatchlistItem,
        storage_module.TradePlan,
        storage_module.Alert,
        storage_module.WorkspaceState,
    ]
    with storage_module.engine.begin() as connection:
        for model in models:
            connection.execute(delete(model).where(model.workspace_id == WS))


def test_plan_dict_carries_source():
    with storage_module.SessionLocal() as session:
        plan = storage_module.TradePlan(
            id="pr-p1",
            workspace_id=WS,
            code="300750",
            direction="buy",
            entry=10.0,
            stop=9.5,
            target=11.0,
            capital=10000,
            position=50,
            validity="本周内",
            source="scan:trend_breakout",
        )
        session.add(plan)
        session.commit()
        loaded = session.get(storage_module.TradePlan, "pr-p1")
        assert loaded.source == "scan:trend_breakout"
        d = storage_module._plan_dict(loaded)
        assert d["source"] == "scan:trend_breakout"


def test_plan_source_null_is_legacy_ready():
    with storage_module.SessionLocal() as session:
        plan = storage_module.TradePlan(
            id="pr-p2",
            workspace_id=WS,
            code="600519",
            direction="buy",
            entry=10.0,
            stop=9.5,
            target=11.0,
            capital=10000,
            position=50,
            validity="本周内",
        )
        session.add(plan)
        session.commit()
        loaded = session.get(storage_module.TradePlan, "pr-p2")
        assert loaded.source is None
        assert storage_module._plan_dict(loaded)["source"] is None  # 归一为 legacy 在 plan_review 层做


def test_save_workspace_roundtrips_source():
    payload = {
        "plans": [
            {
                "id": "pr-p3",
                "code": "000001",
                "direction": "buy",
                "entry": 10.0,
                "stop": 9.5,
                "target": 11.0,
                "capital": 10000,
                "position": 50,
                "validity": "本月内",
                "status": "执行中",
                "triggered": {},
                "createdAtMs": 1700000000000,
                "source": "manual",
            }
        ],
        "watchlist": [],
        "alerts": [],
    }
    storage_module.save_workspace(payload, WS)
    ws = storage_module.get_workspace(WS)
    plan = next(p for p in ws["plans"] if p["id"] == "pr-p3")
    assert plan["source"] == "manual"
    payload["plans"][0]["source"] = ""  # 空串 → None（存量/清空语义）
    storage_module.save_workspace(payload, WS)
    plan = next(p for p in storage_module.get_workspace(WS)["plans"] if p["id"] == "pr-p3")
    assert plan["source"] is None


# —— Task 2: bfq 原始价链路（brief 测试块原样转录）——
# session_db：brief 第三例的参数名；tests/ 下无同名 fixture，这里给出最小实现，
# 并在前后清理 300750 的 market_bars，避免与其他用例互相污染。

@pytest.fixture()
def session_db():
    from sqlalchemy import delete as _delete

    with storage_module.engine.begin() as connection:
        connection.execute(_delete(storage_module.MarketBar).where(storage_module.MarketBar.code == "300750"))
    yield
    with storage_module.engine.begin() as connection:
        connection.execute(_delete(storage_module.MarketBar).where(storage_module.MarketBar.code == "300750"))


def _row(date: str) -> list:
    return [date, "10.0", "10.2", "10.5", "9.9", "100000", "102000000", "1.5", "2.0", "0.1", "1.1"]


def test_load_history_default_qfq_unchanged(monkeypatch):
    from backend import data_source as ds
    keys: list[str] = []
    seen: dict[str, str] = {}

    def fake_cached(key, fn):
        keys.append(key)
        return fn()

    def fake_fetch_json(url, params):
        seen["param"] = params["param"]
        return {"data": {"sh600519": {"qfqday": [_row("2026-09-01")]}}}

    monkeypatch.setattr(ds, "tencent_symbol", lambda c: "sh600519")
    monkeypatch.setattr(ds, "cached", fake_cached)
    monkeypatch.setattr(ds, "fetch_json", fake_fetch_json)
    rows = ds.load_history("600519", limit=40)
    assert rows[0]["date"] == "2026-09-01"
    assert keys == ["history:sh600519:40:qfq"]          # 默认 qfq：缓存键含 :qfq
    assert seen["param"] == "sh600519,day,,,40,qfq"     # 上游 param 尾字段 qfq（现行为不变）


def test_load_history_bfq_uses_day_rows(monkeypatch):
    from backend import data_source as ds
    keys: list[str] = []
    seen: dict[str, str] = {}

    def fake_cached(key, fn):
        keys.append(key)
        return fn()

    def fake_fetch_json(url, params):
        seen["param"] = params["param"]
        return {"data": {"sh600519": {"day": [_row("2026-09-02")]}}}   # 不复权响应只有 day 键

    monkeypatch.setattr(ds, "tencent_symbol", lambda c: "sh600519")
    monkeypatch.setattr(ds, "cached", fake_cached)
    monkeypatch.setattr(ds, "fetch_json", fake_fetch_json)
    rows = ds.load_history("600519", limit=40, adjustment="")
    assert rows[0]["date"] == "2026-09-02"
    assert keys == ["history:sh600519:40:"]             # 空串 fq 的缓存键（与 qfq 键不冲突）
    assert seen["param"] == "sh600519,day,,,40,"        # 尾字段空串 → 上游返回原始价


def test_storage_market_bars_bfq_roundtrip(session_db):
    bars = [{"date": "2026-09-01", "open": 10.0, "close": 10.2, "high": 10.5,
             "low": 9.9, "volume": 100000, "amount": 102000000.0, "change": 1.5}]
    storage.save_market_bars("300750", bars, adjustment="")
    loaded = storage.load_market_bars("300750", adjustment="")
    assert loaded[0]["date"] == "2026-09-01"
    qfq = storage.load_market_bars("300750", adjustment="qfq")  # 互不污染
    assert qfq == []
